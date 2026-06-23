"""
Navigation endpoint.

Accepts a user's natural language query and station zoneID,
runs the navigation pipeline, and returns step-by-step instructions.
Optionally accepts a base64-encoded image of the user's current position.
"""

from __future__ import annotations

import base64
import logging
from typing import List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from clients.genai_client import GenAIClient
from clients.ris_maps_client import RISMapsClient
from pipeline.orchestrator import NavigationOrchestrator, OrchestratorError

logger = logging.getLogger(__name__)

router = APIRouter()

# Maximum image size: 5 MB (base64 encoded is ~33% larger)
MAX_IMAGE_BASE64_LENGTH = 7_000_000  # ~5MB raw image


class NavigateRequest(BaseModel):
    """Request body for the navigate endpoint."""

    zoneID: str = Field(..., min_length=1, description="Station zone ID")
    query: str = Field(..., description="User's navigation query (max 500 chars)")
    handicapped: bool = Field(False, description="Whether to compute a barrier-free route")
    image: Optional[str] = Field(
        None,
        description="Base64-encoded image of the user's current position",
    )
    image_media_type: Optional[str] = Field(
        None,
        description="MIME type of the image (e.g. image/jpeg, image/png)",
    )

    @field_validator("query")
    @classmethod
    def query_must_be_non_empty_and_within_limit(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Bitte geben Sie eine Beschreibung ein")
        if len(stripped) > 500:
            raise ValueError(
                "Die Beschreibung darf maximal 500 Zeichen lang sein"
            )
        return stripped

    @field_validator("image")
    @classmethod
    def image_must_be_valid_base64(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) > MAX_IMAGE_BASE64_LENGTH:
            raise ValueError("Das Bild ist zu groß (max. 5 MB)")
        # Validate it's valid base64
        try:
            base64.b64decode(v)
        except Exception:
            raise ValueError("Ungültiges Bildformat")
        return v

    @field_validator("image_media_type")
    @classmethod
    def image_media_type_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        if v not in allowed:
            raise ValueError(
                f"Ungültiger Bildtyp. Erlaubt: {', '.join(allowed)}"
            )
        return v


class RoutePoint(BaseModel):
    """A single coordinate in the route."""
    lat: float
    lon: float


class RouteSegmentResponse(BaseModel):
    """A route segment for map display."""
    segment_type: str
    level: str
    points: List[RoutePoint]
    simplified_points: List[RoutePoint] = []


class TurnPointResponse(BaseModel):
    """A detected turn point."""
    lat: float
    lon: float
    angle_change: float
    poi_name: Optional[str] = None


class NavigateResponse(BaseModel):
    """Response body for the navigate endpoint."""

    instructions: List[str] = []
    route: List[RouteSegmentResponse] = []
    turn_points: List[TurnPointResponse] = []
    error: Optional[str] = None


def _map_error_to_status(user_message: str) -> int:
    """Map OrchestratorError user_message to an HTTP status code."""
    if "nicht erkannt" in user_message:
        return 422
    if "nicht" in user_message and "gefunden" in user_message:
        return 422
    if "keine Route berechnet" in user_message:
        return 404
    if "zu lange gedauert" in user_message:
        return 504
    if "nicht verfügbar" in user_message:
        return 503
    if "Authentifizierungsfehler" in user_message:
        return 503
    if "konnte nicht verarbeitet werden" in user_message:
        return 500
    return 500


@router.post("/api/navigate", response_model=NavigateResponse)
async def navigate(body: NavigateRequest, request: Request):
    """
    Process a navigation request.

    Validates the request, runs the navigation pipeline via the orchestrator,
    and returns step-by-step instructions or a user-facing error message.
    """
    settings = request.app.state.settings

    # Construct clients from app settings
    ris_maps_client = RISMapsClient()
    genai_client = GenAIClient(
        api_key=settings.genai_api_key,
        endpoint=settings.genai_endpoint,
    )

    orchestrator = NavigationOrchestrator(
        ris_maps_client=ris_maps_client,
        genai_client=genai_client,
    )

    try:
        instructions, route_segments, enriched_segments = await orchestrator.navigate_with_route(
            query=body.query,
            zone_id=body.zoneID,
            handicapped=body.handicapped,
            image_base64=body.image,
            image_media_type=body.image_media_type,
        )

        from pipeline.turn_detector import detect_turns, _rdp_simplify

        route = []
        turn_points = []
        for seg, es in zip(route_segments, enriched_segments):
            # Original points
            points = [RoutePoint(lat=coord[1], lon=coord[0]) for coord in seg.polyline]

            # Simplified points (RDP)
            simplified_pts: list[RoutePoint] = []
            if seg.segment_type == "WALK" and len(seg.polyline) >= 3:
                indexed = [(i, lon, lat) for i, (lon, lat) in enumerate(seg.polyline)]
                simplified = _rdp_simplify(indexed, 5.0)
                simplified_pts = [RoutePoint(lat=lat, lon=lon) for (_idx, lon, lat) in simplified]
            else:
                simplified_pts = points

            route.append(RouteSegmentResponse(
                segment_type=seg.segment_type,
                level=seg.level,
                points=points,
                simplified_points=simplified_pts,
            ))

            # Collect turn points
            for tl in es.turn_landmarks:
                turn_points.append(TurnPointResponse(
                    lat=tl.lat,
                    lon=tl.lon,
                    angle_change=tl.angle_change,
                    poi_name=tl.poi.name if tl.poi else None,
                ))

        return NavigateResponse(instructions=instructions, route=route, turn_points=turn_points, error=None)

    except OrchestratorError as exc:
        user_message = exc.user_message or "Anfrage konnte nicht verarbeitet werden"
        status_code = _map_error_to_status(user_message)
        logger.error(
            "Navigation failed for zone %s: %s (HTTP %d)",
            body.zoneID,
            exc,
            status_code,
        )
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status_code,
            content=NavigateResponse(
                instructions=[], error=user_message
            ).model_dump(),
        )

    except Exception:
        # Catch-all: never expose internal details
        logger.exception("Unexpected error in navigate endpoint")
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=500,
            content=NavigateResponse(
                instructions=[],
                error="Anfrage konnte nicht verarbeitet werden",
            ).model_dump(),
        )

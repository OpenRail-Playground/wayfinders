"""
ImageLocationResolver — determines start position from a photo.

Uses the LLM's vision capability to analyze a photo of the user's
current position and match it against known POIs in the station.
When an image is provided, this replaces the start position extracted
by the IntentParser from the user's text query.
"""

from __future__ import annotations

import logging
from typing import Optional

from clients.genai_client import GenAIClient, GenAIError
from clients.ris_maps_client import (
    RISMapsClient,
    RISMapsError,
    RISMapsNoContentError,
)
from pipeline.models import Position

import json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a location identification assistant for a train station indoor navigation system.

Your task: Given a photo taken by a user inside a train station, identify where they are \
by matching visible elements (signs, shops, platform numbers, landmarks, architecture) \
to a list of known locations in the station.

Rules:
- Look for visible clues: platform/track numbers, shop names, signage, distinctive features.
- Match these clues to the most likely location from the provided list.
- Consider the level/floor based on visible context (underground passages, ground level, upper floors).
- If you can identify a specific POI (e.g. a shop, service point, or platform), select it.
- If you can only determine a general area, pick the closest matching location.
- If you truly cannot determine the location from the image, set result to null.
- Respond ONLY with a JSON object, no extra text.

Output format (strict JSON):
{"location": {"lat": <number>, "lon": <number>, "level": "<string>"}, "confidence": "<high|medium|low>", "reasoning": "<brief explanation>"}

If location cannot be determined:
{"location": null, "confidence": "none", "reasoning": "<why it could not be determined>"}
"""


class ImageLocationResolverError(Exception):
    """Raised when image-based location resolution fails."""

    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(message)
        self.user_message = user_message or message


class ImageLocationResolver:
    """
    Resolves the user's start position from a photo using LLM vision.

    Fetches available POIs and platforms for the station, then sends the image
    along with the location list to the LLM to determine the user's position.
    """

    def __init__(self, ris_maps_client: RISMapsClient, genai_client: GenAIClient):
        self._ris_maps = ris_maps_client
        self._genai = genai_client

    async def resolve(
        self,
        image_base64: str,
        image_media_type: str,
        zone_id: str,
    ) -> Position:
        """
        Determine the user's start position from a photo.

        Args:
            image_base64: Base64-encoded image data.
            image_media_type: MIME type of the image (e.g. "image/jpeg").
            zone_id: The station's zone ID for fetching POIs/platforms.

        Returns:
            A Position representing the user's estimated location.

        Raises:
            ImageLocationResolverError: If the position cannot be determined.
        """
        # Fetch station locations for context
        location_list = await self._fetch_locations(zone_id)

        if not location_list:
            raise ImageLocationResolverError(
                f"No POIs or platforms found for zone {zone_id}",
                user_message="Bahnhofsdaten konnten nicht abgerufen werden",
            )

        # Build the user message with location list
        user_text = self._build_user_message(location_list)

        # Build message with image and text using AWS Converse format
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": image_media_type.split("/")[-1],  # e.g. "jpeg"
                            "source": {
                                "bytes": image_base64,
                            },
                        },
                    },
                    {
                        "text": user_text,
                    },
                ],
            }
        ]

        try:
            response_text = await self._genai.complete(
                messages=messages,
                system_message=SYSTEM_PROMPT,
            )
        except GenAIError as exc:
            logger.error("LLM call failed during image location resolution: %s", exc)
            raise ImageLocationResolverError(
                f"LLM call failed: {exc}",
                user_message="KI-Service ist vorübergehend nicht verfügbar",
            ) from exc

        return self._parse_response(response_text)

    async def _fetch_locations(self, zone_id: str) -> list[dict]:
        """Fetch POIs and platforms, returning a combined location list."""
        locations: list[dict] = []

        try:
            pois_data = await self._ris_maps.get_pois(zone_id)
            pois = pois_data.get("pois", [])
            for poi in pois:
                lat, lon = self._extract_poi_coordinates(poi)
                if lat is not None and lon is not None:
                    locations.append({
                        "name": poi.get("name", "Unknown"),
                        "category": poi.get("category", "Unknown"),
                        "lat": lat,
                        "lon": lon,
                        "level": poi.get("level", "GROUND_FLOOR"),
                    })
        except RISMapsNoContentError:
            logger.warning("No POIs found for zone %s", zone_id)
        except RISMapsError as exc:
            logger.error("Failed to fetch POIs for zone %s: %s", zone_id, exc)

        try:
            platforms_data = await self._ris_maps.get_platforms(zone_id)
            platforms = platforms_data.get("platforms", [])
            for platform in platforms:
                center = platform.get("center", {})
                lat = center.get("lat")
                lon = center.get("lon")
                if lat is not None and lon is not None:
                    locations.append({
                        "name": f"Gleis {platform.get('name', 'Unknown')}",
                        "category": platform.get("category", "PLATFORM"),
                        "lat": lat,
                        "lon": lon,
                        "level": platform.get("level", "GROUND_FLOOR"),
                    })
        except RISMapsNoContentError:
            logger.warning("No platforms found for zone %s", zone_id)
        except RISMapsError as exc:
            logger.error("Failed to fetch platforms for zone %s: %s", zone_id, exc)

        return locations

    def _extract_poi_coordinates(self, poi: dict) -> tuple[Optional[float], Optional[float]]:
        """Extract lat/lon from a POI entry."""
        display_pos = poi.get("displayPosition")
        if display_pos:
            lat = display_pos.get("lat")
            lon = display_pos.get("lon")
            if lat is not None and lon is not None:
                return lat, lon

        geometry = poi.get("geometry", {})
        if geometry.get("type") == "Point":
            coords = geometry.get("coordinates", [])
            if len(coords) >= 2:
                return coords[1], coords[0]

        return None, None

    def _build_user_message(self, locations: list[dict]) -> str:
        """Build the text portion of the user prompt."""
        location_lines = []
        for loc in locations:
            location_lines.append(
                f"- {loc['name']} (category: {loc['category']}, "
                f"level: {loc['level']}, lat: {loc['lat']}, lon: {loc['lon']})"
            )

        locations_text = "\n".join(location_lines)

        return (
            f"Here is the list of known locations in this train station:\n"
            f"{locations_text}\n\n"
            f"Based on the photo I've provided, determine my current location "
            f"by matching visible signs, shops, platform numbers, or other landmarks "
            f"to one of the locations above.\n\n"
            f"Return the coordinates and level as JSON."
        )

    def _parse_response(self, response_text: str) -> Position:
        """Parse the LLM JSON response into a Position."""
        try:
            parsed = json.loads(response_text.strip())
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse image location response as JSON: %s | Response: %s",
                exc,
                response_text[:200],
            )
            raise ImageLocationResolverError(
                f"LLM returned invalid JSON: {response_text[:100]}",
                user_message="Position konnte nicht aus dem Foto bestimmt werden",
            ) from exc

        location_data = parsed.get("location")
        confidence = parsed.get("confidence", "none")
        reasoning = parsed.get("reasoning", "")

        logger.info(
            "Image location resolution: confidence=%s, reasoning=%s",
            confidence,
            reasoning,
        )

        if location_data is None:
            raise ImageLocationResolverError(
                f"Could not determine location from image: {reasoning}",
                user_message="Position konnte nicht aus dem Foto bestimmt werden. "
                "Bitte versuchen Sie ein deutlicheres Foto oder geben Sie Ihren Standort im Text an.",
            )

        try:
            return Position(
                lat=float(location_data["lat"]),
                lon=float(location_data["lon"]),
                level=str(location_data["level"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ImageLocationResolverError(
                f"Invalid location data from image resolution: {location_data}",
                user_message="Position konnte nicht aus dem Foto bestimmt werden",
            ) from exc

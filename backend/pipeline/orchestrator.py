"""
NavigationOrchestrator — coordinates the full indoor navigation pipeline.

Executes the sequential steps:
1. IntentParser.parse(query) → ParsedIntent
2. POIResolver.resolve(start_desc, dest_desc, zone_id) → (start, destination)
3. RouteComputer.compute_route(start, destination, zone_id) → list[RouteSegment]
4. LandmarkEnricher.enrich(segments, pois, platforms) → list[EnrichedSegment]
5. DescriptionGenerator.generate(enriched_segments) → list[str]

Enforces a 15-second soft target (logs warning if exceeded) and passes through
errors from each stage with their user-facing messages.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from clients.genai_client import GenAIClient
from clients.ris_maps_client import (
    RISMapsClient,
    RISMapsError,
    RISMapsNoContentError,
)
from pipeline.description_generator import DescriptionGenerator, DescriptionGeneratorError
from pipeline.intent_parser import IntentParser, IntentParserError
from pipeline.landmark_enricher import LandmarkEnricher
from pipeline.leg_builder import build_legs
from pipeline.models import POI, Platform, Position, RouteSegment
from pipeline.poi_resolver import POIResolver, POIResolverError
from pipeline.route_computer import RouteComputer, RouteComputerError

logger = logging.getLogger(__name__)

# Soft target: log a warning if the pipeline takes longer than this
SOFT_TARGET_SECONDS = 15.0

# Hard timeout: None = no timeout
HARD_TIMEOUT_SECONDS = None


class OrchestratorError(Exception):
    """Raised when the navigation pipeline fails."""

    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(message)
        self.user_message = user_message or message


class NavigationOrchestrator:
    """
    Coordinates the full indoor navigation pipeline.

    Takes a user query and zone_id, runs all pipeline stages sequentially,
    and returns a list of navigation instruction strings.
    """

    def __init__(self, ris_maps_client: RISMapsClient, genai_client: GenAIClient):
        self._ris_maps = ris_maps_client
        self._genai = genai_client

        # Construct pipeline components
        self._intent_parser = IntentParser(genai_client)
        self._poi_resolver = POIResolver(ris_maps_client, genai_client)
        self._route_computer = RouteComputer(ris_maps_client)
        self._landmark_enricher = LandmarkEnricher()
        self._description_generator = DescriptionGenerator(genai_client)

    async def navigate(self, query: str, zone_id: str) -> list[str]:
        """
        Execute the full navigation pipeline. Returns instructions only.
        """
        instructions, _segments = await self.navigate_with_route(query, zone_id)
        return instructions

    async def navigate_with_route(self, query: str, zone_id: str) -> tuple[list[str], list, list]:
        """
        Execute the full navigation pipeline.

        Returns:
            Tuple of (instructions list, route_segments list, enriched_segments list).

        Raises:
            OrchestratorError: If any pipeline stage fails.
        """
        try:
            if HARD_TIMEOUT_SECONDS is not None:
                return await asyncio.wait_for(
                    self._run_pipeline(query, zone_id),
                    timeout=HARD_TIMEOUT_SECONDS,
                )
            else:
                return await self._run_pipeline(query, zone_id)
        except asyncio.TimeoutError:
            logger.error(
                "Navigation pipeline hard timeout exceeded (%.1fs) for zone %s",
                HARD_TIMEOUT_SECONDS,
                zone_id,
            )
            raise OrchestratorError(
                f"Pipeline exceeded hard timeout of {HARD_TIMEOUT_SECONDS}s",
                user_message="Anfrage hat zu lange gedauert",
            )

    async def _run_pipeline(self, query: str, zone_id: str) -> tuple[list[str], list, list]:
        """
        Internal pipeline execution, wrapped by navigate() with a hard timeout.
        """
        start_time = time.monotonic()

        try:
            # Step 1: Parse intent
            logger.info("[Step 1 IntentParser] Input: query=%r", query)
            parsed_intent = await self._intent_parser.parse(query)
            logger.info("[Step 1 IntentParser] Output: start=%r, dest=%r",
                parsed_intent.start_description, parsed_intent.destination_description)

            # Step 2: Resolve POIs to positions
            logger.info("[Step 2 POIResolver] Input: start=%r, dest=%r, zone=%s",
                parsed_intent.start_description, parsed_intent.destination_description, zone_id)
            start_pos, dest_pos = await self._poi_resolver.resolve(
                start_description=parsed_intent.start_description,
                destination_description=parsed_intent.destination_description,
                zone_id=zone_id,
            )
            logger.info("[Step 2 POIResolver] Output: start=%s, dest=%s", start_pos, dest_pos)

            # Step 3: Compute route
            logger.info("[Step 3 RouteComputer] Input: start=%s, dest=%s, zone=%s", start_pos, dest_pos, zone_id)
            route_segments = await self._route_computer.compute_route(
                start=start_pos,
                destination=dest_pos,
                zone_id=zone_id,
            )
            logger.info("[Step 3 RouteComputer] Output: %d segments", len(route_segments))

            # Step 4: Enrich with landmarks
            pois, platforms = await self._fetch_pois_and_platforms(zone_id)
            logger.info("[Step 4 LandmarkEnricher] Input: %d segments, %d POIs, %d platforms",
                len(route_segments), len(pois), len(platforms))
            enriched_segments = self._landmark_enricher.enrich(
                segments=route_segments,
                pois=pois,
                platforms=platforms,
            )
            logger.info("[Step 4 LandmarkEnricher] Output:")
            for i, es in enumerate(enriched_segments):
                landmark = es.landmark_poi.name if es.landmark_poi else es.fallback_cue
                turns_str = ", ".join(
                    f"{tl.poi.name if tl.poi else tl.fallback_cue} ({tl.angle_change:.0f}°)"
                    for tl in es.turn_landmarks
                ) if es.turn_landmarks else "none"
                logger.info("  Segment %d: landmark=%r, turns=[%s]", i + 1, landmark, turns_str)

            # Step 5: Build navigation legs from enriched segments
            legs = build_legs(enriched_segments)
            logger.info("[Step 5 LegBuilder] Built %d legs:", len(legs))
            for i, leg in enumerate(legs):
                dest = leg.destination_poi.name if leg.destination_poi else leg.destination_fallback
                logger.info("  Leg %d: %s %.0fm, turn=%s, dest=%r",
                    i + 1, leg.leg_type, leg.length_m, leg.turn_direction, dest)

            # Step 6: Generate descriptions from legs
            logger.info("[Step 6 DescriptionGenerator] Input: %d legs", len(legs))
            instructions = await self._description_generator.generate(legs)
            logger.info("[Step 6 DescriptionGenerator] Output:")
            for i, instr in enumerate(instructions):
                logger.info("  %d. %s", i + 1, instr)

        except IntentParserError as exc:
            raise OrchestratorError(
                f"Intent parsing failed: {exc}",
                user_message=exc.user_message,
            ) from exc

        except POIResolverError as exc:
            raise OrchestratorError(
                f"POI resolution failed: {exc}",
                user_message=exc.user_message,
            ) from exc

        except RouteComputerError as exc:
            raise OrchestratorError(
                f"Route computation failed: {exc}",
                user_message=str(exc),
            ) from exc

        except DescriptionGeneratorError as exc:
            raise OrchestratorError(
                f"Description generation failed: {exc}",
                user_message=exc.user_message,
            ) from exc

        except Exception as exc:
            logger.exception("Unexpected error in navigation pipeline")
            raise OrchestratorError(
                f"Unexpected error: {exc}",
                user_message="Anfrage konnte nicht verarbeitet werden",
            ) from exc

        finally:
            elapsed = time.monotonic() - start_time
            if elapsed > SOFT_TARGET_SECONDS:
                logger.warning(
                    "Navigation pipeline exceeded soft target: %.2fs (target: %.1fs)",
                    elapsed,
                    SOFT_TARGET_SECONDS,
                )
            else:
                logger.info("Navigation pipeline completed in %.2fs", elapsed)

        return instructions, route_segments, enriched_segments

    async def _fetch_pois_and_platforms(
        self, zone_id: str
    ) -> tuple[list[POI], list[Platform]]:
        """
        Fetch POIs and platforms from RIS-Maps for landmark enrichment.

        Fetches both in sequence. If either fails, returns an empty list
        for that data type (graceful degradation for enrichment).
        """
        pois: list[POI] = []
        platforms: list[Platform] = []

        # Fetch POIs
        try:
            pois_data = await self._ris_maps.get_pois(zone_id)
            raw_pois = pois_data.get("pois", [])
            for raw in raw_pois:
                lat, lon = self._extract_poi_coordinates(raw)
                if lat is not None and lon is not None:
                    pois.append(
                        POI(
                            poi_id=raw.get("id", ""),
                            name=raw.get("name", "Unknown"),
                            category=raw.get("category", "Unknown"),
                            group=raw.get("group", ""),
                            level=raw.get("level", "GROUND_FLOOR"),
                            lat=lat,
                            lon=lon,
                            tags=raw.get("tags", []),
                            detail=raw.get("detail"),
                        )
                    )
        except RISMapsNoContentError:
            logger.warning("No POIs found for zone %s during enrichment", zone_id)
        except RISMapsError as exc:
            logger.warning("Failed to fetch POIs for enrichment: %s", exc)

        # Fetch platforms
        try:
            platforms_data = await self._ris_maps.get_platforms(zone_id)
            raw_platforms = platforms_data.get("platforms", [])
            for raw in raw_platforms:
                center = raw.get("center", {})
                lat = center.get("lat")
                lon = center.get("lon")
                if lat is not None and lon is not None:
                    platforms.append(
                        Platform(
                            name=raw.get("name", "Unknown"),
                            level=raw.get("level", "GROUND_FLOOR"),
                            center_lat=lat,
                            center_lon=lon,
                            category=raw.get("category", "PLATFORM"),
                        )
                    )
        except RISMapsNoContentError:
            logger.warning("No platforms found for zone %s during enrichment", zone_id)
        except RISMapsError as exc:
            logger.warning("Failed to fetch platforms for enrichment: %s", exc)

        return pois, platforms

    @staticmethod
    def _extract_poi_coordinates(poi: dict) -> tuple[Optional[float], Optional[float]]:
        """Extract lat/lon from a raw POI dict, trying displayPosition then geometry."""
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
                return coords[1], coords[0]  # GeoJSON is [lon, lat]

        return None, None

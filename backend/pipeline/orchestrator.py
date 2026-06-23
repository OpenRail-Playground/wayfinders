"""
NavigationOrchestrator — coordinates the full indoor navigation pipeline.

Executes the sequential steps:
1. IntentParser.parse(query) → ParsedIntent
2. POIResolver.resolve(start_desc, dest_desc, zone_id) → (start, destination)
3. RouteComputer.compute_route(start, destination, zone_id) → list[RouteSegment]
4. LandmarkEnricher.enrich(segments, pois, platforms) → list[EnrichedSegment]
5. DescriptionGenerator.generate(enriched_segments) → list[str]

Passes through errors from each stage with their user-facing messages.
"""

from __future__ import annotations

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
from pipeline.image_location_resolver import ImageLocationResolver, ImageLocationResolverError
from pipeline.intent_parser import IntentParser, IntentParserError
from pipeline.landmark_enricher import LandmarkEnricher
from pipeline.leg_builder import apply_exit_overrides, apply_platform_section_overrides, build_legs
from pipeline.models import BuildingPolygon, POI, Platform, PlatformSector, Position, RouteSegment
from pipeline.poi_resolver import POIResolver, POIResolverError
from pipeline.route_computer import RouteComputer, RouteComputerError

logger = logging.getLogger(__name__)


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
        self._image_location_resolver = ImageLocationResolver(ris_maps_client, genai_client)
        self._poi_resolver = POIResolver(ris_maps_client, genai_client)
        self._route_computer = RouteComputer(ris_maps_client)
        self._landmark_enricher = LandmarkEnricher()
        self._description_generator = DescriptionGenerator(genai_client)

    async def navigate(
        self,
        query: str,
        zone_id: str,
        handicapped: bool = False,
        image_base64: Optional[str] = None,
        image_media_type: Optional[str] = None,
    ) -> list[str]:
        """
        Execute the full navigation pipeline. Returns instructions only.
        """
        instructions, _segments, _enriched = await self.navigate_with_route(
            query, zone_id, handicapped, image_base64, image_media_type
        )
        return instructions

    async def navigate_with_route(
        self,
        query: str,
        zone_id: str,
        handicapped: bool = False,
        image_base64: Optional[str] = None,
        image_media_type: Optional[str] = None,
    ) -> tuple[list[str], list, list]:
        """
        Execute the full navigation pipeline.

        Args:
            query: User's navigation query.
            zone_id: Station zone ID.
            handicapped: Whether to compute a barrier-free route.
            image_base64: Optional base64-encoded image of user's current position.
            image_media_type: MIME type of the image (e.g. "image/jpeg").

        Returns:
            Tuple of (instructions list, route_segments list, enriched_segments list).

        Raises:
            OrchestratorError: If any pipeline stage fails.
        """
        return await self._run_pipeline(query, zone_id, handicapped, image_base64, image_media_type)

    async def _run_pipeline(
        self,
        query: str,
        zone_id: str,
        handicapped: bool = False,
        image_base64: Optional[str] = None,
        image_media_type: Optional[str] = None,
    ) -> tuple[list[str], list, list]:
        """
        Internal pipeline execution, wrapped by navigate() with a hard timeout.

        If an image is provided, the start position is determined from the photo
        using the ImageLocationResolver. The text-based start from IntentParser
        is ignored in that case.
        """
        start_time = time.monotonic()

        try:
            # Step 1: Parse intent from text
            logger.info("[Step 1 IntentParser] Input: query=%r", query)
            try:
                parsed_intent = await self._intent_parser.parse(query)
                logger.info("[Step 1 IntentParser] Output: start=%r, dest=%r",
                    parsed_intent.start_description, parsed_intent.destination_description)
            except IntentParserError as exc:
                # If we have an image and the error is about missing start, try destination-only parsing
                if image_base64 and image_media_type and "Start position" in str(exc):
                    logger.info(
                        "[Step 1 IntentParser] Start not found in text, will use image instead"
                    )
                    # Re-parse allowing null start
                    parsed_intent = await self._intent_parser.parse_destination_only(query)
                    logger.info("[Step 1 IntentParser] Output (dest only): dest=%r",
                        parsed_intent.destination_description)
                else:
                    raise

            # Step 1b: If image provided, resolve start position from photo
            image_start_position: Optional[Position] = None
            if image_base64 and image_media_type:
                logger.info("[Step 1b ImageLocationResolver] Resolving start from image")
                try:
                    image_start_position = await self._image_location_resolver.resolve(
                        image_base64=image_base64,
                        image_media_type=image_media_type,
                        zone_id=zone_id,
                    )
                    logger.info(
                        "[Step 1b ImageLocationResolver] Output: lat=%s, lon=%s, level=%s",
                        image_start_position.lat,
                        image_start_position.lon,
                        image_start_position.level,
                    )
                except ImageLocationResolverError as exc:
                    # If image resolution fails, fall back to text-based start
                    logger.warning(
                        "[Step 1b ImageLocationResolver] Failed, falling back to text: %s",
                        exc,
                    )
                    image_start_position = None

            # Step 2: Resolve POIs to positions
            if image_start_position:
                # Image provided: only resolve the destination via POIResolver
                logger.info(
                    "[Step 2 POIResolver] Using image-based start, resolving destination only: dest=%r, zone=%s",
                    parsed_intent.destination_description, zone_id,
                )
                dest_pos = await self._poi_resolver.resolve_destination_only(
                    destination_description=parsed_intent.destination_description,
                    zone_id=zone_id,
                )
                start_pos = image_start_position
                logger.info("[Step 2 POIResolver] Output: start (from image)=%s, dest=%s", start_pos, dest_pos)
            else:
                # No image: resolve both start and destination from text
                logger.info("[Step 2 POIResolver] Input: start=%r, dest=%r, zone=%s",
                    parsed_intent.start_description, parsed_intent.destination_description, zone_id)
                start_pos, dest_pos = await self._poi_resolver.resolve(
                    start_description=parsed_intent.start_description,
                    destination_description=parsed_intent.destination_description,
                    zone_id=zone_id,
                )
                logger.info("[Step 2 POIResolver] Output: start=%s, dest=%s", start_pos, dest_pos)

            # Step 3: Compute route
            logger.info("[Step 3 RouteComputer] Input: start=%s, dest=%s, zone=%s, handicapped=%s", start_pos, dest_pos, zone_id, handicapped)
            route_segments = await self._route_computer.compute_route(
                start=start_pos,
                destination=dest_pos,
                zone_id=zone_id,
                handicapped=handicapped,
            )
            logger.info("[Step 3 RouteComputer] Output: %d segments", len(route_segments))

            # Step 4: Enrich with landmarks
            pois, platforms, sectors, buildings = await self._fetch_pois_and_platforms(zone_id)
            logger.info("[Step 4 LandmarkEnricher] Input: %d segments, %d POIs, %d platforms, %d sectors, %d buildings",
                len(route_segments), len(pois), len(platforms), len(sectors), len(buildings))
            for b in buildings:
                coords_summary = f"{len(b.polygon)} vertices"
                if b.polygon:
                    lons = [c[0] for c in b.polygon]
                    lats = [c[1] for c in b.polygon]
                    coords_summary += f", bbox=[{min(lons):.6f},{min(lats):.6f} - {max(lons):.6f},{max(lats):.6f}]"
                logger.info("  Building %r (id=%s): %s", b.name, b.building_id, coords_summary)
            enriched_segments = self._landmark_enricher.enrich(
                segments=route_segments,
                pois=pois,
                platforms=platforms,
                sectors=sectors,
                buildings=buildings,
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
            # Apply platform section overrides per-leg (on platforms, always use section directions)
            legs = apply_platform_section_overrides(legs, platforms, sectors)
            # Apply exit overrides per-leg (detects building→outside transitions)
            legs = apply_exit_overrides(legs, pois, buildings)
            logger.info("[Step 5 LegBuilder] Built %d legs:", len(legs))
            for i, leg in enumerate(legs):
                dest = leg.destination_poi.name if leg.destination_poi else leg.destination_fallback
                building_info = self._describe_building_context(leg.polyline, buildings)
                logger.info("  Leg %d: %s %.0fm, turn=%s, dest=%r, building=%s",
                    i + 1, leg.leg_type, leg.length_m, leg.turn_direction, dest, building_info)

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

        except ImageLocationResolverError as exc:
            raise OrchestratorError(
                f"Image location resolution failed: {exc}",
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
            logger.info("Navigation pipeline completed in %.2fs", elapsed)

        return instructions, route_segments, enriched_segments

    async def _fetch_pois_and_platforms(
        self, zone_id: str
    ) -> tuple[list[POI], list[Platform], list[PlatformSector], list[BuildingPolygon]]:
        """
        Fetch POIs, platforms, platform sectors, and buildings from RIS-Maps
        for landmark enrichment.

        Fetches all in sequence. If any fail, returns an empty list
        for that data type (graceful degradation for enrichment).
        """
        pois: list[POI] = []
        platforms: list[Platform] = []
        sectors: list[PlatformSector] = []
        buildings: list[BuildingPolygon] = []

        # Fetch POIs
        try:
            pois_data = await self._ris_maps.get_pois(zone_id)
            raw_pois = pois_data.get("pois", [])
            for raw in raw_pois:
                lat, lon = self._extract_poi_coordinates(raw)
                if lat is not None and lon is not None:
                    # Compute approximate area from polygon geometry
                    geometry_area = self._compute_geometry_area(raw)
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
                            geometry_area_m2=geometry_area,
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
                    platform_polygon = self._extract_polygon_ring(raw.get("geometry", {}))
                    platforms.append(
                        Platform(
                            name=raw.get("name", "Unknown"),
                            level=raw.get("level", "GROUND_FLOOR"),
                            center_lat=lat,
                            center_lon=lon,
                            category=raw.get("category", "PLATFORM"),
                            polygon=platform_polygon,
                        )
                    )
        except RISMapsNoContentError:
            logger.warning("No platforms found for zone %s during enrichment", zone_id)
        except RISMapsError as exc:
            logger.warning("Failed to fetch platforms for enrichment: %s", exc)

        # Fetch platform sectors
        try:
            sectors_data = await self._ris_maps.get_platform_sectors(zone_id)
            raw_features = sectors_data.get("features", [])
            for feature in raw_features:
                props = feature.get("properties", {})
                cube_pos = props.get("cubePosition")
                if cube_pos:
                    sector_lat = cube_pos.get("lat")
                    sector_lon = cube_pos.get("lon")
                else:
                    # Fall back to geometry centroid
                    geometry = feature.get("geometry", {})
                    sector_lat, sector_lon = self._extract_geometry_centroid(geometry)

                if sector_lat is not None and sector_lon is not None:
                    sectors.append(
                        PlatformSector(
                            name=props.get("name", ""),
                            platform_name=props.get("platformName", ""),
                            track_name=props.get("trackName", ""),
                            lat=sector_lat,
                            lon=sector_lon,
                        )
                    )
        except RISMapsNoContentError:
            logger.warning("No platform sectors found for zone %s", zone_id)
        except RISMapsError as exc:
            logger.warning("Failed to fetch platform sectors for enrichment: %s", exc)

        # Fetch buildings (for exit detection)
        try:
            buildings_data = await self._ris_maps.get_buildings(zone_id)
            raw_buildings = buildings_data.get("buildings", [])
            for raw in raw_buildings:
                geometry = raw.get("geometry", {})
                polygon_coords = self._extract_polygon_ring(geometry)
                if polygon_coords:
                    buildings.append(
                        BuildingPolygon(
                            building_id=raw.get("buildingID", ""),
                            name=raw.get("buildingName", ""),
                            polygon=polygon_coords,
                        )
                    )
        except RISMapsNoContentError:
            logger.warning("No buildings found for zone %s", zone_id)
        except RISMapsError as exc:
            logger.warning("Failed to fetch buildings for enrichment: %s", exc)

        return pois, platforms, sectors, buildings

    @staticmethod
    def _describe_building_context(
        polyline: list[tuple[float, float]], buildings: list[BuildingPolygon]
    ) -> str:
        """
        Describe the building context of a leg's polyline for debug logging.

        Returns one of:
        - "leaves <building_name>" if the start is inside and end is outside
        - "inside <building_name>" if both start and end are inside the same building
        - "outside" if neither start nor end is inside a building
        """
        from pipeline.landmark_enricher import _point_in_polygon

        if not polyline or not buildings:
            return "outside"

        start_lon, start_lat = polyline[0]
        end_lon, end_lat = polyline[-1]

        start_building: Optional[str] = None
        end_building: Optional[str] = None

        for b in buildings:
            if _point_in_polygon(start_lon, start_lat, b.polygon):
                start_building = b.name or b.building_id
            if _point_in_polygon(end_lon, end_lat, b.polygon):
                end_building = b.name or b.building_id

        if start_building and not end_building:
            return f"leaves {start_building!r}"
        elif start_building:
            return f"inside {start_building!r}"
        else:
            return "outside"

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

    @staticmethod
    def _compute_geometry_area(poi: dict) -> float:
        """
        Compute approximate area in m² from a POI's polygon geometry.

        Uses the shoelace formula on projected coordinates (local flat-Earth approximation).
        Returns 0.0 for Point geometries or if geometry is missing/invalid.
        """
        geometry = poi.get("geometry", {})
        geo_type = geometry.get("type", "")

        if geo_type != "Polygon":
            return 0.0

        coords = geometry.get("coordinates", [])
        if not coords or not coords[0] or len(coords[0]) < 3:
            return 0.0

        # Use the outer ring (first ring in the coordinates array)
        ring = coords[0]  # list of [lon, lat] pairs

        # Local flat-Earth projection centered on the first point
        import math
        ref_lon, ref_lat = ring[0][0], ring[0][1]
        lat_mid = math.radians(ref_lat)
        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(lat_mid)

        # Project to meters and compute area via shoelace
        projected = []
        for coord in ring:
            x = (coord[0] - ref_lon) * m_per_deg_lon
            y = (coord[1] - ref_lat) * m_per_deg_lat
            projected.append((x, y))

        n = len(projected)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += projected[i][0] * projected[j][1]
            area -= projected[j][0] * projected[i][1]
        return abs(area) / 2.0

    @staticmethod
    def _extract_geometry_centroid(geometry: dict) -> tuple[Optional[float], Optional[float]]:
        """
        Extract centroid (lat, lon) from a GeoJSON geometry.

        Handles Point and Polygon types.
        """
        geo_type = geometry.get("type", "")

        if geo_type == "Point":
            coords = geometry.get("coordinates", [])
            if len(coords) >= 2:
                return coords[1], coords[0]  # GeoJSON is [lon, lat]

        elif geo_type == "Polygon":
            coords = geometry.get("coordinates", [])
            if coords and coords[0]:
                ring = coords[0]
                avg_lon = sum(c[0] for c in ring) / len(ring)
                avg_lat = sum(c[1] for c in ring) / len(ring)
                return avg_lat, avg_lon

        return None, None

    @staticmethod
    def _extract_polygon_ring(geometry: dict) -> list[tuple[float, float]]:
        """
        Extract the outer ring of a polygon geometry as [(lon, lat), ...].

        Handles both Polygon and MultiPolygon (uses the largest polygon).
        Returns an empty list if the geometry type is unsupported or has no coordinates.
        """
        geo_type = geometry.get("type", "")

        if geo_type == "Polygon":
            coords = geometry.get("coordinates", [])
            if not coords or not coords[0] or len(coords[0]) < 3:
                return []
            return [(c[0], c[1]) for c in coords[0]]

        elif geo_type == "MultiPolygon":
            # Use the largest polygon (most vertices as a heuristic for area)
            multi_coords = geometry.get("coordinates", [])
            best_ring: list[tuple[float, float]] = []
            best_size = 0
            for polygon_coords in multi_coords:
                if polygon_coords and polygon_coords[0] and len(polygon_coords[0]) >= 3:
                    if len(polygon_coords[0]) > best_size:
                        best_size = len(polygon_coords[0])
                        best_ring = [(c[0], c[1]) for c in polygon_coords[0]]
            return best_ring

        return []

"""
LandmarkEnricher — enriches route segments with nearby POI landmarks.

For each walk segment endpoint, selects the best recognizable POI within 30m
on the same level using a scoring system that prefers:
- Larger, more visible POIs (based on geometry area and category)
- POIs that are unique within the station (only appear once)
- POIs that are reasonably close (but not strictly the closest)

When on a platform level, provides section-based direction cues (e.g. "Richtung Abschnitt A").
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from typing import Optional

from pipeline.models import BuildingPolygon, EnrichedSegment, Platform, PlatformSector, POI, RouteSegment, TurnLandmark
from pipeline.turn_detector import detect_turns

logger = logging.getLogger(__name__)

# Maximum distance (meters) to consider a POI as a landmark
MAX_LANDMARK_DISTANCE_M = 30.0

# Maximum distance (meters) to consider the user as being on a platform
# Platforms are long (200-400m), so the center can be far from the user
MAX_PLATFORM_PROXIMITY_M = 150.0

# POI groups that are considered recognizable landmarks
LANDMARK_GROUPS = {"SHOPPING", "STATION_FACILITY", "GASTRONOMY_AND_FOOD", "SERVICES"}

# POI group to exclude — these are route infrastructure, not landmarks
EXCLUDED_GROUPS = {"ROUTING"}

# POI categories representing exits — when the route transitions from inside
# a building to outside, the nearest exit is always used as the navigation hint
EXIT_CATEGORIES = {"ENTRANCE_EXIT", "Exit"}

# POI categories that are inherently large/highly visible (scored higher)
HIGH_VISIBILITY_CATEGORIES = {
    "DB_LOUNGE", "DB_INFORMATION", "DB_TRAVEL_CENTER",
    "RESTAURANT", "FAST_FOOD", "COFFEE_SHOP", "SUPERMARKET",
    "SHOPPING_COMMON", "BAKERY", "PRESS",
    "WAITING_AREA",
}

# POI categories that are small and less visible (scored lower)
LOW_VISIBILITY_CATEGORIES = {
    "CASHPOINT", "LETTERBOX", "WIFI", "LOCKER",
    "TOILET", "TOILET_HANDICAPPED",
}

# Earth radius in meters for haversine calculation
EARTH_RADIUS_M = 6_371_000.0


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing in degrees (0=N, 90=E) from point 1 to point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _normalize_angle(angle: float) -> float:
    """Normalize angle to [-180, 180]."""
    while angle > 180:
        angle -= 360
    while angle < -180:
        angle += 360
    return angle


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points using the haversine formula.

    Args:
        lat1: Latitude of point 1 in degrees.
        lon1: Longitude of point 1 in degrees.
        lat2: Latitude of point 2 in degrees.
        lon2: Longitude of point 2 in degrees.

    Returns:
        Distance in meters.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


def _is_recognizable_landmark(poi: POI) -> bool:
    """
    Determine if a POI qualifies as a recognizable landmark.

    Recognizable landmarks include:
    - SHOPPING group (shops, restaurants)
    - STATION_FACILITY group (ticket machines, service points, DB Lounge)
    - GASTRONOMY_AND_FOOD group
    - SERVICES group
    - Named facilities that aren't routing infrastructure
    Excludes:
    - ROUTING group (stairs, escalators, elevators — route infrastructure)
    """
    if poi.group in EXCLUDED_GROUPS:
        return False
    if poi.group in LANDMARK_GROUPS:
        return True
    # Also accept any named facility that isn't routing infrastructure
    if poi.name and poi.group not in EXCLUDED_GROUPS:
        return True
    return False


def _compute_poi_name_counts(pois: list[POI]) -> Counter:
    """
    Count how many times each POI name appears in the station.

    POIs that appear only once are more useful as landmarks because
    they unambiguously identify a location.
    """
    name_counts: Counter = Counter()
    for poi in pois:
        if poi.name and _is_recognizable_landmark(poi):
            name_counts[poi.name] += 1
    return name_counts


def _visibility_score(poi: POI, name_counts: Counter) -> float:
    """
    Compute a visibility/usefulness score for a POI as a navigation landmark.

    Higher score = better landmark. Considers:
    - Geometry area (larger POIs are more visible)
    - Category-based visibility (shops > ATMs)
    - Uniqueness (POIs that appear only once in the station are preferred)

    Returns a score in [0, 1] range (approximately).
    """
    score = 0.0

    # --- Area-based visibility (0 to 0.3) ---
    # POIs with polygon geometry have area > 0
    if poi.geometry_area_m2 > 0:
        # Log scale: 10m² → ~0.1, 50m² → ~0.2, 200m² → ~0.3
        area_score = min(0.3, math.log1p(poi.geometry_area_m2) / 18.0)
        score += area_score
    else:
        # Point POI, no area info — small base score
        score += 0.05

    # --- Category-based visibility (0 to 0.3) ---
    if poi.category in HIGH_VISIBILITY_CATEGORIES:
        score += 0.3
    elif poi.category in LOW_VISIBILITY_CATEGORIES:
        score += 0.05
    else:
        score += 0.15  # medium visibility

    # --- Uniqueness bonus (0 to 0.4) ---
    # A POI that appears only once in the station is a much better landmark
    count = name_counts.get(poi.name, 1)
    if count == 1:
        score += 0.4  # unique — strong bonus
    elif count == 2:
        score += 0.2  # appears twice — moderate
    else:
        score += 0.0  # appears 3+ times — not useful as unambiguous reference

    return score


def _find_nearest_platform(
    lat: float, lon: float, level: str, platforms: list[Platform]
) -> Optional[Platform]:
    """Find the nearest platform on the same level, if any."""
    nearest: Optional[Platform] = None
    nearest_dist = float("inf")

    for platform in platforms:
        if platform.level != level:
            continue
        dist = haversine_distance(lat, lon, platform.center_lat, platform.center_lon)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest = platform

    return nearest


def _find_exit_along_segment(
    segment: RouteSegment,
    pois: list[POI],
    buildings: list[BuildingPolygon],
) -> Optional[POI]:
    """
    Check if the route segment transitions from inside a building to outside.

    If the start of the polyline is inside a building and the end is outside,
    the segment crosses an exit. In that case, find the nearest ENTRANCE_EXIT
    POI to the polyline and return it.

    Returns the exit POI if found, None otherwise.
    """
    if not segment.polyline or len(segment.polyline) < 2:
        return None
    if not buildings:
        return None

    # Check if start is inside any building
    start_lon, start_lat = segment.polyline[0]
    start_inside = _point_in_any_building(start_lat, start_lon, buildings)

    if not start_inside:
        return None

    # Check if end is outside all buildings
    end_lon, end_lat = segment.polyline[-1]
    end_inside = _point_in_any_building(end_lat, end_lon, buildings)

    if end_inside:
        return None

    # The segment goes from inside to outside — find the nearest exit POI
    # to any point on the polyline
    exit_pois = [
        p for p in pois
        if p.category in EXIT_CATEGORIES and p.level == segment.level
    ]
    if not exit_pois:
        return None

    best_exit: Optional[POI] = None
    best_dist = float("inf")

    for exit_poi in exit_pois:
        for lon, lat in segment.polyline:
            dist = haversine_distance(lat, lon, exit_poi.lat, exit_poi.lon)
            if dist < best_dist:
                best_dist = dist
                best_exit = exit_poi

    return best_exit


def _point_in_any_building(
    lat: float, lon: float, buildings: list[BuildingPolygon]
) -> bool:
    """Check if a point (lat, lon) is inside any of the building polygons."""
    for building in buildings:
        if _point_in_polygon(lon, lat, building.polygon):
            return True
    return False


def _point_in_polygon(
    x: float, y: float, polygon: list[tuple[float, float]]
) -> bool:
    """
    Ray-casting point-in-polygon test.

    Args:
        x: Longitude of point.
        y: Latitude of point.
        polygon: List of (lon, lat) vertices forming the polygon ring.

    Returns:
        True if the point is inside the polygon.
    """
    n = len(polygon)
    inside = False

    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i

    return inside


def _find_nearest_sector(
    lat: float, lon: float, platform_name: str, sectors: list[PlatformSector]
) -> Optional[PlatformSector]:
    """
    Find the nearest platform sector for a given platform.

    Matches sectors whose platform_name or track_name corresponds to the platform.
    """
    nearest: Optional[PlatformSector] = None
    nearest_dist = float("inf")

    for sector in sectors:
        # Match by platform name or track name
        if sector.platform_name != platform_name and sector.track_name != platform_name:
            continue
        dist = haversine_distance(lat, lon, sector.lat, sector.lon)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest = sector

    return nearest


class LandmarkEnricher:
    """
    Enriches route segments with landmark POI references.

    For each walk segment, selects the best recognizable POI within 30m
    on the same level at the segment endpoint, using a scoring system that
    considers visibility, size, and uniqueness. Falls back to structural cues
    (platform section, platform number, corridor) when no landmark is found.
    """

    def enrich(
        self,
        segments: list[RouteSegment],
        pois: list[POI],
        platforms: list[Platform],
        sectors: Optional[list[PlatformSector]] = None,
        buildings: Optional[list[BuildingPolygon]] = None,
    ) -> list[EnrichedSegment]:
        """
        Enrich route segments with landmark information.

        Args:
            segments: Ordered list of route segments from the route computer.
            pois: All POIs for the station.
            platforms: All platforms for the station.
            sectors: Platform sectors (A, B, C, ...) for section-based directions.
            buildings: Building footprint polygons for exit detection.

        Returns:
            List of EnrichedSegment with landmark or fallback cue for each segment.
        """
        if sectors is None:
            sectors = []
        if buildings is None:
            buildings = []

        # Pre-compute name occurrence counts for uniqueness scoring
        name_counts = _compute_poi_name_counts(pois)

        enriched: list[EnrichedSegment] = []

        for segment in segments:
            if segment.segment_type == "WALK" and segment.polyline:
                # Get the endpoint of the walk segment (last coordinate)
                endpoint_lon, endpoint_lat = segment.polyline[-1]
                endpoint_level = segment.level

                # Determine the direction of travel for platform section cues
                # Use the segment endpoint as the direction target
                direction_lat, direction_lon = None, None
                if len(segment.polyline) >= 2:
                    direction_lon, direction_lat = segment.polyline[-1]

                # Priority 1: Check if we're on a platform with sections
                platform_section_cue = self._get_platform_section_cue(
                    endpoint_lat, endpoint_lon, endpoint_level,
                    platforms, sectors, direction_lat, direction_lon,
                )

                # Detect significant turns
                turn_landmarks = self._enrich_turns(segment, pois, platforms, sectors, name_counts)

                if platform_section_cue is not None:
                    # On a platform with sections: always use section direction
                    enriched.append(
                        EnrichedSegment(
                            segment=segment,
                            landmark_poi=None,
                            landmark_distance_m=0.0,
                            fallback_cue=platform_section_cue,
                            turn_landmarks=turn_landmarks,
                        )
                    )
                else:
                    # Not on a platform — find best landmark POI at endpoint
                    # Compute travel direction bearing at the endpoint
                    seg_bearing: Optional[float] = None
                    if len(segment.polyline) >= 2:
                        prev_lon, prev_lat = segment.polyline[-2]
                        seg_bearing = _bearing(prev_lat, prev_lon, endpoint_lat, endpoint_lon)

                    landmark, distance = self._find_best_landmark(
                        endpoint_lat, endpoint_lon, endpoint_level, pois, name_counts,
                        direction_bearing=seg_bearing,
                    )

                    if landmark is not None:
                        enriched.append(
                            EnrichedSegment(
                                segment=segment,
                                landmark_poi=landmark,
                                landmark_distance_m=distance,
                                fallback_cue=None,
                                turn_landmarks=turn_landmarks,
                            )
                        )
                    else:
                        # No landmark found — no fallback cue; description generator
                        # will produce a distance-only instruction
                        enriched.append(
                            EnrichedSegment(
                                segment=segment,
                                landmark_poi=None,
                                landmark_distance_m=0.0,
                                fallback_cue=None,
                                turn_landmarks=turn_landmarks,
                            )
                        )
            else:
                # Non-walk segments (stairs, escalator, elevator, ramp)
                # don't need landmark enrichment
                enriched.append(
                    EnrichedSegment(
                        segment=segment,
                        landmark_poi=None,
                        landmark_distance_m=0.0,
                        fallback_cue=None,
                    )
                )

        return enriched

    def _enrich_turns(
        self,
        segment: RouteSegment,
        pois: list[POI],
        platforms: list[Platform],
        sectors: list[PlatformSector],
        name_counts: Counter,
    ) -> list[TurnLandmark]:
        """
        Detect significant direction changes and find nearby POIs at those points.

        On platforms with sections, always uses section-based cues instead of POIs.
        """
        turns = detect_turns(segment, simplify_tolerance_m=5.0, min_angle_change=30.0)
        turn_landmarks: list[TurnLandmark] = []

        for i, turn in enumerate(turns):
            # Determine direction: use the next point after the turn
            next_lat, next_lon = None, None
            if i + 1 < len(turns):
                next_lat, next_lon = turns[i + 1].lat, turns[i + 1].lon
            elif segment.polyline:
                # Use segment endpoint as direction
                next_lon, next_lat = segment.polyline[-1]

            # Check if on a platform with sections
            platform_cue = self._get_platform_section_cue(
                turn.lat, turn.lon, segment.level,
                platforms, sectors, next_lat, next_lon,
            )

            if platform_cue is not None:
                # On platform with sections: always use section direction
                turn_landmarks.append(TurnLandmark(
                    lat=turn.lat,
                    lon=turn.lon,
                    angle_change=turn.angle_change,
                    index=turn.index,
                    poi=None,
                    fallback_cue=platform_cue,
                ))
            else:
                # Not on a platform — find best recognizable POI
                # Compute bearing from turn towards next waypoint
                turn_bearing: Optional[float] = None
                if next_lat is not None and next_lon is not None:
                    turn_bearing = _bearing(turn.lat, turn.lon, next_lat, next_lon)

                poi, _dist = self._find_best_landmark(
                    turn.lat, turn.lon, segment.level, pois, name_counts,
                    direction_bearing=turn_bearing,
                )
                if poi:
                    turn_landmarks.append(TurnLandmark(
                        lat=turn.lat,
                        lon=turn.lon,
                        angle_change=turn.angle_change,
                        index=turn.index,
                        poi=poi,
                        fallback_cue=None,
                    ))
                else:
                    turn_landmarks.append(TurnLandmark(
                        lat=turn.lat,
                        lon=turn.lon,
                        angle_change=turn.angle_change,
                        index=turn.index,
                        poi=None,
                        fallback_cue=None,
                    ))

        return turn_landmarks

    def _get_platform_section_cue(
        self,
        lat: float,
        lon: float,
        level: str,
        platforms: list[Platform],
        sectors: list[PlatformSector],
        direction_lat: Optional[float] = None,
        direction_lon: Optional[float] = None,
    ) -> Optional[str]:
        """
        If the point is on/near a platform that has sections, return a section-based
        direction cue. Returns None if not on a platform or the platform has no sectors.

        When on a platform with sections, this always takes priority over POI landmarks.
        """
        if not sectors:
            return None

        nearest_platform = _find_nearest_platform(lat, lon, level, platforms)
        if nearest_platform is None:
            return None

        dist = haversine_distance(lat, lon, nearest_platform.center_lat, nearest_platform.center_lon)
        if dist > MAX_PLATFORM_PROXIMITY_M:
            return None

        # Check if this platform has any sectors
        platform_sectors = [
            s for s in sectors
            if s.platform_name == nearest_platform.name or s.track_name == nearest_platform.name
        ]
        if not platform_sectors:
            return None

        # Platform has sections — find the section closest to the direction/destination
        target_lat = direction_lat if direction_lat is not None else lat
        target_lon = direction_lon if direction_lon is not None else lon
        nearest_sector = _find_nearest_sector(
            target_lat, target_lon, nearest_platform.name, sectors
        )
        if nearest_sector:
            return f"Richtung Abschnitt {nearest_sector.name}"

        return None

    def _find_best_landmark(
        self,
        lat: float,
        lon: float,
        level: str,
        pois: list[POI],
        name_counts: Counter,
        direction_bearing: Optional[float] = None,
    ) -> tuple[Optional[POI], float]:
        """
        Find the best landmark POI within 30m on the same level.

        Uses a combined score that balances:
        - Proximity (closer is better, but not the only factor)
        - Visibility (larger/more prominent POIs score higher)
        - Uniqueness (POIs that appear only once in the station are preferred)

        Only considers POIs within a 120° field of vision in the direction of travel
        (±60° from the direction_bearing). If no direction is provided, all POIs
        within range are considered.

        The scoring formula:
            combined_score = visibility_score * (1 - distance_penalty)

        Where distance_penalty scales from 0 (at 0m) to 1 (at MAX_LANDMARK_DISTANCE_M).

        Args:
            lat: Latitude of the search point.
            lon: Longitude of the search point.
            level: Level to filter POIs by.
            pois: All available POIs.
            name_counts: Pre-computed occurrence counts for POI names.
            direction_bearing: Bearing of travel direction in degrees (0=N, 90=E).
                If provided, only POIs within ±60° of this bearing are considered.

        Returns:
            Tuple of (best POI or None, distance in meters).
            Returns (None, 0.0) if no qualifying POI is found.
        """
        best_poi: Optional[POI] = None
        best_score = -1.0
        best_distance = 0.0

        for poi in pois:
            # Must be on same level
            if poi.level != level:
                continue

            # Must be a recognizable landmark
            if not _is_recognizable_landmark(poi):
                continue

            distance = haversine_distance(lat, lon, poi.lat, poi.lon)

            # Must be within threshold
            if distance > MAX_LANDMARK_DISTANCE_M:
                continue

            # Field-of-vision filter: POI must be within ±60° of travel direction
            if direction_bearing is not None and distance > 1.0:
                bearing_to_poi = _bearing(lat, lon, poi.lat, poi.lon)
                angle_diff = _normalize_angle(bearing_to_poi - direction_bearing)
                if abs(angle_diff) > 60.0:
                    continue

            # Compute combined score
            vis_score = _visibility_score(poi, name_counts)

            # Distance penalty: 0 at 0m, 0.5 at 15m, 1.0 at 30m
            distance_penalty = distance / MAX_LANDMARK_DISTANCE_M

            # Combined: visibility matters more, distance is a soft penalty
            # A very visible POI at 25m beats a tiny POI at 5m
            combined = vis_score * (1.0 - 0.5 * distance_penalty)

            if combined > best_score:
                best_score = combined
                best_poi = poi
                best_distance = distance

        if best_poi is not None:
            return best_poi, best_distance

        return None, 0.0

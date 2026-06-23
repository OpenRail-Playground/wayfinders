"""
LandmarkEnricher — enriches route segments with nearby POI landmarks.

For each walk segment endpoint, finds the closest recognizable POI within 30m
on the same level. If no suitable landmark is found, produces a fallback
structural cue (e.g., corridor, platform number).
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from pipeline.models import EnrichedSegment, Platform, POI, RouteSegment, TurnLandmark
from pipeline.turn_detector import detect_turns

logger = logging.getLogger(__name__)

# Maximum distance (meters) to consider a POI as a landmark
MAX_LANDMARK_DISTANCE_M = 30.0

# POI groups that are considered recognizable landmarks
LANDMARK_GROUPS = {"SHOPPING", "STATION_FACILITY"}

# POI group to exclude — these are route infrastructure, not landmarks
EXCLUDED_GROUPS = {"ROUTING"}

# Earth radius in meters for haversine calculation
EARTH_RADIUS_M = 6_371_000.0


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
    - Named facilities (Gepäckaufbewahrung, etc.)
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


def _get_fallback_cue(
    lat: float, lon: float, level: str, platforms: list[Platform]
) -> str:
    """
    Generate a fallback structural cue when no landmark POI is available.

    Checks if a platform is nearby and references it by number.
    Otherwise returns a generic structural cue.
    """
    nearest_platform = _find_nearest_platform(lat, lon, level, platforms)
    if nearest_platform is not None:
        dist = haversine_distance(
            lat, lon, nearest_platform.center_lat, nearest_platform.center_lon
        )
        if dist <= MAX_LANDMARK_DISTANCE_M:
            return f"Gleis {nearest_platform.name}"

    return "Korridor"


class LandmarkEnricher:
    """
    Enriches route segments with landmark POI references.

    For each walk segment, identifies the nearest recognizable POI
    within 30m on the same level at the segment endpoint. Falls back
    to structural cues (platform number, corridor) when no landmark is found.
    """

    def enrich(
        self,
        segments: list[RouteSegment],
        pois: list[POI],
        platforms: list[Platform],
    ) -> list[EnrichedSegment]:
        """
        Enrich route segments with landmark information.

        Args:
            segments: Ordered list of route segments from the route computer.
            pois: All POIs for the station.
            platforms: All platforms for the station.

        Returns:
            List of EnrichedSegment with landmark or fallback cue for each segment.
        """
        enriched: list[EnrichedSegment] = []

        for segment in segments:
            if segment.segment_type == "WALK" and segment.polyline:
                # Get the endpoint of the walk segment (last coordinate)
                endpoint_lon, endpoint_lat = segment.polyline[-1]
                endpoint_level = segment.level

                # Find nearest recognizable landmark POI at endpoint
                landmark, distance = self._find_nearest_landmark(
                    endpoint_lat, endpoint_lon, endpoint_level, pois
                )

                # Detect significant turns and find POIs at turn points
                turn_landmarks = self._enrich_turns(segment, pois, platforms)

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
                    # No landmark found — use fallback structural cue
                    fallback = _get_fallback_cue(
                        endpoint_lat, endpoint_lon, endpoint_level, platforms
                    )
                    enriched.append(
                        EnrichedSegment(
                            segment=segment,
                            landmark_poi=None,
                            landmark_distance_m=0.0,
                            fallback_cue=fallback,
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
    ) -> list[TurnLandmark]:
        """
        Detect significant direction changes and find nearby POIs at those points.
        """
        turns = detect_turns(segment, simplify_tolerance_m=5.0, min_angle_change=30.0)
        turn_landmarks: list[TurnLandmark] = []

        for turn in turns:
            # Find nearest recognizable POI at this turn point
            poi, _dist = self._find_nearest_landmark(
                turn.lat, turn.lon, segment.level, pois
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
                fallback = _get_fallback_cue(turn.lat, turn.lon, segment.level, platforms)
                turn_landmarks.append(TurnLandmark(
                    lat=turn.lat,
                    lon=turn.lon,
                    angle_change=turn.angle_change,
                    index=turn.index,
                    poi=None,
                    fallback_cue=fallback,
                ))

        return turn_landmarks

    def _find_nearest_landmark(
        self,
        lat: float,
        lon: float,
        level: str,
        pois: list[POI],
    ) -> tuple[Optional[POI], float]:
        """
        Find the nearest recognizable landmark POI within 30m on the same level.

        Args:
            lat: Latitude of the search point.
            lon: Longitude of the search point.
            level: Level to filter POIs by.
            pois: All available POIs.

        Returns:
            Tuple of (nearest POI or None, distance in meters).
            Returns (None, 0.0) if no qualifying POI is found.
        """
        nearest_poi: Optional[POI] = None
        nearest_distance = float("inf")

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

            if distance < nearest_distance:
                nearest_distance = distance
                nearest_poi = poi

        if nearest_poi is not None:
            return nearest_poi, nearest_distance

        return None, 0.0

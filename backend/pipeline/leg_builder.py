"""
Leg Builder — converts enriched segments into navigation legs.

Splits walk segments at significant turn points so each leg represents
a straight-ish walk to a visible POI. Non-walk segments (stairs, escalator, etc.)
become a single leg each.
"""

from __future__ import annotations

import math
import logging

from pipeline.landmark_enricher import haversine_distance, EXIT_CATEGORIES
from pipeline.models import BuildingPolygon, EnrichedSegment, NavigationLeg, POI, TurnLandmark

logger = logging.getLogger(__name__)


def build_legs(enriched_segments: list[EnrichedSegment]) -> list[NavigationLeg]:
    """
    Convert enriched route segments into navigation legs.

    Walk segments with turn landmarks are split into multiple legs:
    - One leg per straight section between turns
    - Each leg's destination is the POI at the next turn point (or the segment endpoint)

    Non-walk segments become a single leg each.
    """
    legs: list[NavigationLeg] = []

    for enriched in enriched_segments:
        seg = enriched.segment

        if seg.segment_type != "WALK":
            # Level-change segments: single leg
            legs.append(NavigationLeg(
                leg_type=seg.segment_type,
                level=seg.level,
                length_m=seg.length_m,
                target_level=seg.target_level,
                destination_poi=None,
                destination_fallback=None,
                turn_direction=None,
                angle_change=0.0,
                polyline=seg.polyline,
            ))
            continue

        # Walk segment: split at turn points
        if not enriched.turn_landmarks:
            # No turns — single leg to the endpoint
            legs.append(NavigationLeg(
                leg_type="WALK",
                level=seg.level,
                length_m=seg.length_m,
                destination_poi=enriched.landmark_poi,
                destination_fallback=enriched.fallback_cue,
                turn_direction=None,
                angle_change=0.0,
                polyline=seg.polyline,
            ))
            continue

        # Split the walk into legs at each turn point
        # We need approximate distances between waypoints
        # Waypoints: start → turn1 → turn2 → ... → endpoint
        waypoints = _build_waypoints(seg, enriched)

        for i, wp in enumerate(waypoints):
            turn_dir = None
            angle = 0.0
            if i > 0:
                # This leg starts at a turn — determine direction
                angle = waypoints[i - 1].get("angle_to_next", 0.0)
                turn_dir = _angle_to_direction(angle)

            legs.append(NavigationLeg(
                leg_type="WALK",
                level=seg.level,
                length_m=wp["distance_m"],
                destination_poi=wp["poi"],
                destination_fallback=wp["fallback"],
                turn_direction=turn_dir,
                angle_change=angle,
                polyline=wp.get("polyline", []),
            ))

    logger.info("Built %d navigation legs from %d segments", len(legs), len(enriched_segments))
    return legs


def _build_waypoints(seg, enriched: EnrichedSegment) -> list[dict]:
    """
    Build waypoint list: each waypoint represents a leg destination.
    Returns list of dicts with: poi, fallback, distance_m, angle_to_next, polyline.
    """
    polyline = seg.polyline
    turns = enriched.turn_landmarks

    # Collect waypoint indices in the polyline
    # Start is implicit (index 0), turns are at their indices, end is last point
    turn_indices = [tl.index if hasattr(tl, 'index') else _find_closest_index(polyline, tl.lat, tl.lon)
                    for tl in turns]

    # Build ordered list of destination points (turns + final endpoint)
    destinations = []
    prev_idx = 0

    for i, tl in enumerate(turns):
        t_idx = turn_indices[i]
        dist = _polyline_distance(polyline, prev_idx, t_idx)
        destinations.append({
            "poi": tl.poi,
            "fallback": tl.fallback_cue,
            "distance_m": dist,
            "angle_to_next": tl.angle_change,
            "polyline": polyline[prev_idx:t_idx + 1],
        })
        prev_idx = t_idx

    # Final leg: from last turn to endpoint
    end_idx = len(polyline) - 1
    dist = _polyline_distance(polyline, prev_idx, end_idx)
    destinations.append({
        "poi": enriched.landmark_poi,
        "fallback": enriched.fallback_cue,
        "distance_m": dist,
        "angle_to_next": 0.0,
        "polyline": polyline[prev_idx:end_idx + 1],
    })

    return destinations


def _find_closest_index(polyline: list[tuple[float, float]], lat: float, lon: float) -> int:
    """Find the polyline index closest to the given lat/lon."""
    min_dist = float("inf")
    min_idx = 0
    for i, (plon, plat) in enumerate(polyline):
        dist = haversine_distance(lat, lon, plat, plon)
        if dist < min_dist:
            min_dist = dist
            min_idx = i
    return min_idx


def _polyline_distance(polyline: list[tuple[float, float]], from_idx: int, to_idx: int) -> float:
    """Sum of haversine distances along polyline from from_idx to to_idx."""
    total = 0.0
    for i in range(from_idx, min(to_idx, len(polyline) - 1)):
        lon1, lat1 = polyline[i]
        lon2, lat2 = polyline[i + 1]
        total += haversine_distance(lat1, lon1, lat2, lon2)
    return total


def _angle_to_direction(angle_change: float) -> str:
    """Convert a bearing change to a human turn direction."""
    # Normalize to -180..180
    while angle_change > 180:
        angle_change -= 360
    while angle_change < -180:
        angle_change += 360

    if angle_change > 0:
        return "rechts"  # clockwise = right turn
    else:
        return "links"   # counter-clockwise = left turn


def apply_exit_overrides(
    legs: list[NavigationLeg],
    pois: list[POI],
    buildings: list[BuildingPolygon],
) -> list[NavigationLeg]:
    """
    Post-process legs to override the destination with an exit POI
    when a leg transitions from inside a building to outside.

    This runs after build_legs so each leg's polyline is checked individually,
    ensuring that the specific leg crossing the building boundary gets the
    exit hint — not the whole segment.

    Args:
        legs: Built navigation legs (with polylines).
        pois: All POIs for the station.
        buildings: Building footprint polygons.

    Returns:
        The same list of legs, with exit overrides applied in-place.
    """
    if not buildings:
        return legs

    from pipeline.landmark_enricher import _point_in_polygon, _point_in_any_building

    # Collect exit POIs (ENTRANCE_EXIT or Exit category)
    exit_pois = [p for p in pois if p.category in EXIT_CATEGORIES]
    if not exit_pois:
        return legs

    for leg in legs:
        if leg.leg_type != "WALK" or len(leg.polyline) < 2:
            continue

        start_lon, start_lat = leg.polyline[0]
        end_lon, end_lat = leg.polyline[-1]

        start_inside = _point_in_any_building(start_lat, start_lon, buildings)
        end_inside = _point_in_any_building(end_lat, end_lon, buildings)

        if start_inside and not end_inside:
            # This leg leaves a building — find the nearest exit POI on this level
            best_exit = None
            best_dist = float("inf")
            for exit_poi in exit_pois:
                if exit_poi.level != leg.level:
                    continue
                for lon, lat in leg.polyline:
                    dist = haversine_distance(lat, lon, exit_poi.lat, exit_poi.lon)
                    if dist < best_dist:
                        best_dist = dist
                        best_exit = exit_poi

            if best_exit is not None:
                leg.destination_poi = best_exit
                leg.destination_fallback = None

    return legs


def apply_platform_section_overrides(
    legs: list[NavigationLeg],
    platforms: "list",
    sectors: "list",
) -> list[NavigationLeg]:
    """
    Post-process legs to override destination with platform section directions
    when a leg starts on a platform that has sections.

    On a platform with sections, the user should always be told which section
    to walk towards — never a POI name.

    Args:
        legs: Built navigation legs (with polylines).
        platforms: All platforms for the station.
        sectors: Platform sectors (A, B, C, ...).

    Returns:
        The same list of legs, with platform section overrides applied in-place.
    """
    if not sectors:
        return legs

    from pipeline.landmark_enricher import (
        _find_nearest_sector,
        _point_in_polygon,
    )

    for leg in legs:
        if leg.leg_type != "WALK" or len(leg.polyline) < 2:
            continue

        start_lon, start_lat = leg.polyline[0]
        end_lon, end_lat = leg.polyline[-1]

        # Check if the leg starts physically within a platform polygon
        matched_platform = None
        for plat in platforms:
            if plat.level != leg.level:
                continue
            if not plat.polygon:
                continue
            if _point_in_polygon(start_lon, start_lat, plat.polygon):
                matched_platform = plat
                break

        if matched_platform is None:
            continue

        # Check if this platform has sections
        platform_sectors = [
            s for s in sectors
            if s.platform_name == matched_platform.name or s.track_name == matched_platform.name
        ]
        if not platform_sectors:
            continue

        # Platform has sections — find the section closest to the leg's endpoint
        # (i.e., the direction the user should walk)
        nearest_sector = _find_nearest_sector(end_lat, end_lon, matched_platform.name, sectors)

        if nearest_sector:
            leg.destination_poi = None
            leg.destination_fallback = f"Richtung Abschnitt {nearest_sector.name}"

    return legs

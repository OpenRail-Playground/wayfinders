"""
Turn Detector — identifies significant direction changes in a route segment.

Uses Ramer-Douglas-Peucker simplification to reduce the polyline to its
essential shape, then detects points where the bearing changes significantly.
These turn points are candidates for intermediate POI landmark enrichment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pipeline.models import RouteSegment


@dataclass
class TurnPoint:
    """A point where the route changes direction significantly."""
    lat: float
    lon: float
    index: int          # index in the original polyline
    angle_change: float # signed bearing change in degrees (positive=right, negative=left)


def detect_turns(
    segment: RouteSegment,
    simplify_tolerance_m: float = 5.0,
    min_angle_change: float = 30.0,
) -> list[TurnPoint]:
    """
    Detect significant turn points in a walk segment.

    1. Simplify the polyline using Ramer-Douglas-Peucker (tolerance in meters)
    2. Compute bearing change at each interior vertex of the simplified path
    3. Return vertices where the bearing change exceeds min_angle_change

    Args:
        segment: A RouteSegment (only WALK segments make sense here)
        simplify_tolerance_m: RDP tolerance in meters (larger = fewer points kept)
        min_angle_change: Minimum bearing change in degrees to count as a turn

    Returns:
        List of TurnPoint objects for significant direction changes.
    """
    if segment.segment_type != "WALK" or len(segment.polyline) < 3:
        return []

    # Convert to (index, lon, lat) for tracking original indices
    indexed_points = [(i, lon, lat) for i, (lon, lat) in enumerate(segment.polyline)]

    # Simplify
    simplified = _rdp_simplify(indexed_points, simplify_tolerance_m)

    if len(simplified) < 3:
        return []

    # Detect turns at interior vertices of the simplified polyline
    turns: list[TurnPoint] = []
    for i in range(1, len(simplified) - 1):
        _, lon_prev, lat_prev = simplified[i - 1]
        orig_idx, lon_curr, lat_curr = simplified[i]
        _, lon_next, lat_next = simplified[i + 1]

        bearing_in = _bearing(lat_prev, lon_prev, lat_curr, lon_curr)
        bearing_out = _bearing(lat_curr, lon_curr, lat_next, lon_next)

        signed_change = _normalize_angle(bearing_out - bearing_in)

        if abs(signed_change) >= min_angle_change:
            turns.append(TurnPoint(
                lat=lat_curr,
                lon=lon_curr,
                index=orig_idx,
                angle_change=signed_change,
            ))

    return turns


def _rdp_simplify(
    points: list[tuple[int, float, float]],
    tolerance_m: float,
) -> list[tuple[int, float, float]]:
    """
    Ramer-Douglas-Peucker simplification.

    Points are (original_index, lon, lat).
    Tolerance is in meters (converted via perpendicular distance).
    """
    if len(points) <= 2:
        return points

    # Find the point with maximum perpendicular distance from the line
    # connecting the first and last points
    start = points[0]
    end = points[-1]

    max_dist = 0.0
    max_idx = 0

    for i in range(1, len(points) - 1):
        dist = _perpendicular_distance_m(points[i], start, end)
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    if max_dist > tolerance_m:
        # Recurse on both halves
        left = _rdp_simplify(points[:max_idx + 1], tolerance_m)
        right = _rdp_simplify(points[max_idx:], tolerance_m)
        return left[:-1] + right
    else:
        return [start, end]


def _perpendicular_distance_m(
    point: tuple[int, float, float],
    line_start: tuple[int, float, float],
    line_end: tuple[int, float, float],
) -> float:
    """
    Approximate perpendicular distance from a point to a line segment, in meters.

    Uses a local flat-Earth approximation (valid for short distances within a station).
    """
    _, px, py = point   # lon, lat
    _, x1, y1 = line_start
    _, x2, y2 = line_end

    # Convert to meters using local scaling
    lat_mid = math.radians((y1 + y2) / 2)
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(lat_mid)

    # Points in local meter coordinates
    ax = (x1 - x1) * m_per_deg_lon
    ay = (y1 - y1) * m_per_deg_lat
    bx = (x2 - x1) * m_per_deg_lon
    by = (y2 - y1) * m_per_deg_lat
    cx = (px - x1) * m_per_deg_lon
    cy = (py - y1) * m_per_deg_lat

    # Line length squared
    line_len_sq = bx * bx + by * by
    if line_len_sq == 0:
        return math.sqrt(cx * cx + cy * cy)

    # Project point onto line
    t = max(0, min(1, (cx * bx + cy * by) / line_len_sq))
    proj_x = ax + t * bx
    proj_y = ay + t * by

    return math.sqrt((cx - proj_x) ** 2 + (cy - proj_y) ** 2)


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing in degrees (0=N, 90=E) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
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

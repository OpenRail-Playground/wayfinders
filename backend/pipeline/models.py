"""
Shared data models for the navigation pipeline.

Defines dataclasses used across multiple pipeline components:
RouteSegment, POI, EnrichedSegment, Platform, Position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Position:
    """Geographic position with level information."""

    lat: float
    lon: float
    level: str  # LevelEnum value, e.g. "GROUND_FLOOR"


@dataclass
class POI:
    """Point of Interest within a station."""

    poi_id: str
    name: str
    category: str  # e.g. "Stairs", "Escalator", "TravelService", "Exit"
    group: str  # e.g. "ROUTING", "STATION_FACILITY", "SHOPPING"
    level: str  # LevelEnum value
    lat: float
    lon: float
    tags: list[str] = field(default_factory=list)
    detail: Optional[str] = None
    geometry_area_m2: float = 0.0  # approximate area from polygon geometry (0 = point/unknown)


@dataclass
class Platform:
    """A platform within a station."""

    name: str  # e.g. "101/102", "5/6"
    level: str  # LevelEnum value
    center_lat: float
    center_lon: float
    category: str  # "TRACK" or "PLATFORM"
    polygon: list[tuple[float, float]] = field(default_factory=list)  # [(lon, lat), ...] outer ring


@dataclass
class PlatformSector:
    """A named section (A, B, C, ...) on a platform."""

    name: str  # e.g. "A", "B", "C"
    platform_name: str  # e.g. "5", "101/102"
    track_name: str  # e.g. "5"
    lat: float  # cube/center position
    lon: float  # cube/center position


@dataclass
class BuildingPolygon:
    """A building footprint polygon for inside/outside detection."""

    building_id: str
    name: str
    polygon: list[tuple[float, float]]  # [(lon, lat), ...] outer ring coordinates


@dataclass
class RouteSegment:
    """A segment of a computed indoor route."""

    segment_type: str  # "WALK" | "STAIRS" | "ESCALATOR" | "ELEVATOR" | "RAMP"
    level: str  # LevelEnum value for this segment
    length_m: float  # distance in meters
    polyline: list[tuple[float, float]]  # [(lon, lat), ...] coordinate pairs
    target_level: Optional[str] = None  # for level-change segments: destination level


@dataclass
class TurnLandmark:
    """A landmark at an intermediate turn point in a walk segment."""

    lat: float
    lon: float
    angle_change: float  # signed bearing change (positive=right, negative=left)
    index: int  # index in the original polyline
    poi: Optional[POI]   # nearby POI, if found
    fallback_cue: Optional[str]  # structural cue if no POI


@dataclass
class EnrichedSegment:
    """A route segment enriched with landmark information."""

    segment: RouteSegment
    landmark_poi: Optional[POI]  # nearest recognizable POI at segment endpoint
    landmark_distance_m: float  # distance from endpoint to landmark (0 if no landmark)
    fallback_cue: Optional[str]  # structural cue if no landmark found
    turn_landmarks: list[TurnLandmark] = field(default_factory=list)  # intermediate turn POIs


@dataclass
class NavigationLeg:
    """
    A single leg of navigation — a straight-ish walk between two points,
    or a level-change segment. The description generator produces one
    instruction per NavigationLeg.
    """

    leg_type: str  # "WALK" | "STAIRS" | "ESCALATOR" | "ELEVATOR" | "RAMP"
    level: str
    length_m: float
    target_level: Optional[str] = None  # for level-change legs
    destination_poi: Optional[POI] = None  # POI at the end of this leg (turn point or final dest)
    destination_fallback: Optional[str] = None  # fallback cue if no POI
    turn_direction: Optional[str] = None  # "left", "right", or None (for first leg / level changes)
    angle_change: float = 0.0  # bearing change at the start of this leg
    polyline: list[tuple[float, float]] = field(default_factory=list)  # [(lon, lat), ...] slice for this leg

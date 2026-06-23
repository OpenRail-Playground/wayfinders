"""
Route Computer module.

Calls the RIS-Maps indoor routing endpoint with resolved start/destination
positions and parses the GeoJSON FeatureCollection response into an ordered
list of RouteSegment dataclass objects.

Handles:
- 204 No Content (no route found)
- 4xx/5xx errors from RIS-Maps
- Timeout errors
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from clients.ris_maps_client import (
    RISMapsClient,
    RISMapsClientError,
    RISMapsNoContentError,
    RISMapsServerError,
    RISMapsTimeoutError,
)

logger = logging.getLogger(__name__)


class RouteComputerError(Exception):
    """Domain-specific error for route computation failures."""

    def __init__(self, message: str, recoverable: bool = False):
        super().__init__(message)
        self.recoverable = recoverable


@dataclass
class Position:
    """A geographic position within a station."""

    lat: float
    lon: float
    level: str


@dataclass
class RouteSegment:
    """A single segment of a computed indoor route."""

    segment_type: str  # "WALK" | "STAIRS" | "ESCALATOR" | "ELEVATOR" | "RAMP"
    level: str  # LevelEnum value for this segment
    length_m: float  # distance in meters
    polyline: list[tuple[float, float]]  # [(lon, lat), ...] coordinate pairs
    target_level: str | None  # for level-change segments: destination level


class RouteComputer:
    """
    Computes an indoor route between two positions using the RIS-Maps API.

    Takes resolved start and destination positions (lat, lon, level) and a
    station zoneID, calls the RIS-Maps indoor routing endpoint, and parses
    the GeoJSON FeatureCollection response into RouteSegment objects.
    """

    def __init__(self, ris_maps_client: RISMapsClient) -> None:
        self._client = ris_maps_client

    async def compute_route(
        self,
        start: Position,
        destination: Position,
        zone_id: str,
        handicapped: bool = False,
    ) -> list[RouteSegment]:
        """
        Compute an indoor route between start and destination.

        Args:
            start: The starting position (lat, lon, level)
            destination: The destination position (lat, lon, level)
            zone_id: The station's zone ID
            handicapped: Whether to compute a barrier-free route

        Returns:
            Ordered list of RouteSegment objects from start to destination

        Raises:
            RouteComputerError: On any failure (no route, API error, parse error)
        """
        try:
            geojson = await self._client.get_indoor_route(
                zone_id=zone_id,
                from_level=start.level,
                from_lat=start.lat,
                from_lon=start.lon,
                to_level=destination.level,
                to_lat=destination.lat,
                to_lon=destination.lon,
                handicapped=handicapped,
            )
        except RISMapsNoContentError:
            raise RouteComputerError(
                "Es konnte keine Route berechnet werden",
                recoverable=False,
            )
        except RISMapsClientError as exc:
            logger.error(f"RIS-Maps client error during route computation: {exc}")
            raise RouteComputerError(
                "Routing-Service ist nicht verfügbar",
                recoverable=False,
            )
        except RISMapsServerError as exc:
            logger.error(f"RIS-Maps server error during route computation: {exc}")
            raise RouteComputerError(
                "Routing-Service ist vorübergehend nicht verfügbar",
                recoverable=True,
            )
        except RISMapsTimeoutError as exc:
            logger.error(f"RIS-Maps timeout during route computation: {exc}")
            raise RouteComputerError(
                "Routing-Service ist vorübergehend nicht verfügbar",
                recoverable=True,
            )

        return self._parse_geojson(geojson)

    def _parse_geojson(self, geojson: dict[str, Any]) -> list[RouteSegment]:
        """
        Parse a GeoJSON FeatureCollection into an ordered list of RouteSegments.

        The GeoJSON response from the RIS-Maps indoor routing endpoint has the
        structure:
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon, lat], ...]
                    },
                    "properties": {
                        "type": "WALK" | "STAIRS" | ...,
                        "level": "GROUND_FLOOR",
                        "toLevel": "UPPER_FLOOR_1",  (optional)
                        "length": 42.5
                    }
                },
                ...
            ]
        }

        Args:
            geojson: The parsed JSON response from the routing endpoint

        Returns:
            Ordered list of RouteSegment objects

        Raises:
            RouteComputerError: If the GeoJSON structure is invalid or empty
        """
        features = geojson.get("features")
        if not features:
            raise RouteComputerError(
                "Es konnte keine Route berechnet werden",
                recoverable=False,
            )

        segments: list[RouteSegment] = []

        for i, feature in enumerate(features):
            try:
                segment = self._parse_feature(feature)
                segments.append(segment)
            except (KeyError, TypeError, ValueError) as exc:
                logger.error(
                    f"Failed to parse route segment {i}: {exc}. Feature: {feature}"
                )
                raise RouteComputerError(
                    "Routendaten konnten nicht verarbeitet werden",
                    recoverable=False,
                )

        return segments

    def _parse_feature(self, feature: dict[str, Any]) -> RouteSegment:
        """
        Parse a single GeoJSON Feature into a RouteSegment.

        Args:
            feature: A GeoJSON Feature dict

        Returns:
            A RouteSegment object

        Raises:
            KeyError: If required fields are missing
            TypeError: If field types are unexpected
            ValueError: If field values are invalid
        """
        properties = feature["properties"]
        geometry = feature["geometry"]

        segment_type = properties["type"]
        level = properties["level"]
        length_m = float(properties["length"])

        # Extract target level for level-change segments
        target_level = properties.get("toLevel")

        # Parse polyline coordinates from geometry
        # GeoJSON coordinates are [lon, lat] pairs
        coordinates = geometry["coordinates"]
        polyline = [(float(coord[0]), float(coord[1])) for coord in coordinates]

        return RouteSegment(
            segment_type=segment_type,
            level=level,
            length_m=length_m,
            polyline=polyline,
            target_level=target_level,
        )

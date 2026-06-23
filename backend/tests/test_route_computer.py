"""
Tests for the RouteComputer module.

Tests cover:
- Successful route computation and GeoJSON parsing
- Handling of level-change segments with target_level
- Multi-segment routes preserving order
- Error handling: 204 No Content, 4xx, 5xx, timeout
- Invalid/empty GeoJSON handling
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from pipeline.route_computer import (
    Position,
    RouteComputer,
    RouteComputerError,
    RouteSegment,
)
from clients.ris_maps_client import (
    RISMapsClient,
    RISMapsClientError,
    RISMapsNoContentError,
    RISMapsServerError,
    RISMapsTimeoutError,
)


# --- Fixtures ---


@pytest.fixture
def mock_client():
    """Create a mock RISMapsClient."""
    client = MagicMock(spec=RISMapsClient)
    client.get_indoor_route = AsyncMock()
    return client


@pytest.fixture
def route_computer(mock_client):
    """Create a RouteComputer with a mocked client."""
    return RouteComputer(mock_client)


@pytest.fixture
def start_position():
    return Position(lat=50.1059862, lon=8.6613112, level="GROUND_FLOOR")


@pytest.fixture
def dest_position():
    return Position(lat=50.1066346, lon=8.6642098, level="GROUND_FLOOR")


@pytest.fixture
def single_walk_geojson():
    """A simple GeoJSON FeatureCollection with one WALK segment."""
    return {
        "type": "FeatureCollection",
        "totalFeatures": 1,
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [8.6613112, 50.1059862],
                        [8.6632317, 50.1067006],
                        [8.6642098, 50.1066346],
                    ],
                },
                "properties": {
                    "type": "WALK",
                    "level": "GROUND_FLOOR",
                    "length": 228.47,
                },
            }
        ],
    }


@pytest.fixture
def multi_segment_geojson():
    """A GeoJSON FeatureCollection with multiple segments including a level change."""
    return {
        "type": "FeatureCollection",
        "totalFeatures": 3,
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [8.6613, 50.1060],
                        [8.6620, 50.1063],
                    ],
                },
                "properties": {
                    "type": "WALK",
                    "level": "GROUND_FLOOR",
                    "length": 55.2,
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [8.6620, 50.1063],
                        [8.6620, 50.1063],
                    ],
                },
                "properties": {
                    "type": "ESCALATOR",
                    "level": "GROUND_FLOOR",
                    "toLevel": "BASEMENT_FLOOR_1",
                    "length": 12.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [8.6620, 50.1063],
                        [8.6635, 50.1065],
                    ],
                },
                "properties": {
                    "type": "WALK",
                    "level": "BASEMENT_FLOOR_1",
                    "length": 120.5,
                },
            },
        ],
    }


# --- Test: Successful Route Computation ---


@pytest.mark.asyncio
async def test_compute_route_single_walk_segment(
    route_computer, mock_client, start_position, dest_position, single_walk_geojson
):
    """Test parsing a simple single-segment walk route."""
    mock_client.get_indoor_route.return_value = single_walk_geojson

    segments = await route_computer.compute_route(start_position, dest_position, "1866")

    assert len(segments) == 1
    seg = segments[0]
    assert seg.segment_type == "WALK"
    assert seg.level == "GROUND_FLOOR"
    assert seg.length_m == 228.47
    assert seg.target_level is None
    assert len(seg.polyline) == 3
    # GeoJSON is [lon, lat], so first coord should be (lon, lat)
    assert seg.polyline[0] == (8.6613112, 50.1059862)
    assert seg.polyline[2] == (8.6642098, 50.1066346)


@pytest.mark.asyncio
async def test_compute_route_multi_segment_with_level_change(
    route_computer, mock_client, start_position, dest_position, multi_segment_geojson
):
    """Test parsing a multi-segment route with level changes."""
    mock_client.get_indoor_route.return_value = multi_segment_geojson

    segments = await route_computer.compute_route(start_position, dest_position, "1866")

    assert len(segments) == 3

    # First segment: WALK on GROUND_FLOOR
    assert segments[0].segment_type == "WALK"
    assert segments[0].level == "GROUND_FLOOR"
    assert segments[0].length_m == 55.2
    assert segments[0].target_level is None

    # Second segment: ESCALATOR with level change
    assert segments[1].segment_type == "ESCALATOR"
    assert segments[1].level == "GROUND_FLOOR"
    assert segments[1].target_level == "BASEMENT_FLOOR_1"
    assert segments[1].length_m == 12.0

    # Third segment: WALK on BASEMENT_FLOOR_1
    assert segments[2].segment_type == "WALK"
    assert segments[2].level == "BASEMENT_FLOOR_1"
    assert segments[2].length_m == 120.5
    assert segments[2].target_level is None


@pytest.mark.asyncio
async def test_compute_route_calls_client_with_correct_params(
    route_computer, mock_client, single_walk_geojson
):
    """Test that the client is called with the correct parameters."""
    mock_client.get_indoor_route.return_value = single_walk_geojson

    start = Position(lat=50.1, lon=8.6, level="UPPER_FLOOR_1")
    dest = Position(lat=50.2, lon=8.7, level="BASEMENT_FLOOR_1")

    await route_computer.compute_route(start, dest, "4711")

    mock_client.get_indoor_route.assert_called_once_with(
        zone_id="4711",
        from_level="UPPER_FLOOR_1",
        from_lat=50.1,
        from_lon=8.6,
        to_level="BASEMENT_FLOOR_1",
        to_lat=50.2,
        to_lon=8.7,
    )


@pytest.mark.asyncio
async def test_compute_route_preserves_segment_order(
    route_computer, mock_client, start_position, dest_position, multi_segment_geojson
):
    """Test that segments are returned in the same order as the GeoJSON features."""
    mock_client.get_indoor_route.return_value = multi_segment_geojson

    segments = await route_computer.compute_route(start_position, dest_position, "1866")

    types = [s.segment_type for s in segments]
    assert types == ["WALK", "ESCALATOR", "WALK"]


# --- Test: Error Handling ---


@pytest.mark.asyncio
async def test_compute_route_no_content_204(
    route_computer, mock_client, start_position, dest_position
):
    """Test that 204 No Content raises RouteComputerError with appropriate message."""
    mock_client.get_indoor_route.side_effect = RISMapsNoContentError()

    with pytest.raises(RouteComputerError) as exc_info:
        await route_computer.compute_route(start_position, dest_position, "1866")

    assert "keine Route berechnet" in str(exc_info.value)
    assert not exc_info.value.recoverable


@pytest.mark.asyncio
async def test_compute_route_client_error_4xx(
    route_computer, mock_client, start_position, dest_position
):
    """Test that 4xx errors raise RouteComputerError."""
    mock_client.get_indoor_route.side_effect = RISMapsClientError(
        "Client error: HTTP 400", status_code=400
    )

    with pytest.raises(RouteComputerError) as exc_info:
        await route_computer.compute_route(start_position, dest_position, "1866")

    assert "nicht verfügbar" in str(exc_info.value)
    assert not exc_info.value.recoverable


@pytest.mark.asyncio
async def test_compute_route_server_error_5xx(
    route_computer, mock_client, start_position, dest_position
):
    """Test that 5xx errors raise RouteComputerError marked as recoverable."""
    mock_client.get_indoor_route.side_effect = RISMapsServerError(
        "Server error: HTTP 500", status_code=500
    )

    with pytest.raises(RouteComputerError) as exc_info:
        await route_computer.compute_route(start_position, dest_position, "1866")

    assert "vorübergehend nicht verfügbar" in str(exc_info.value)
    assert exc_info.value.recoverable


@pytest.mark.asyncio
async def test_compute_route_timeout(
    route_computer, mock_client, start_position, dest_position
):
    """Test that timeout errors raise RouteComputerError marked as recoverable."""
    mock_client.get_indoor_route.side_effect = RISMapsTimeoutError()

    with pytest.raises(RouteComputerError) as exc_info:
        await route_computer.compute_route(start_position, dest_position, "1866")

    assert "vorübergehend nicht verfügbar" in str(exc_info.value)
    assert exc_info.value.recoverable


@pytest.mark.asyncio
async def test_compute_route_empty_features(
    route_computer, mock_client, start_position, dest_position
):
    """Test that an empty features list raises RouteComputerError."""
    mock_client.get_indoor_route.return_value = {
        "type": "FeatureCollection",
        "features": [],
    }

    with pytest.raises(RouteComputerError) as exc_info:
        await route_computer.compute_route(start_position, dest_position, "1866")

    assert "keine Route berechnet" in str(exc_info.value)


@pytest.mark.asyncio
async def test_compute_route_missing_features_key(
    route_computer, mock_client, start_position, dest_position
):
    """Test that missing 'features' key raises RouteComputerError."""
    mock_client.get_indoor_route.return_value = {"type": "FeatureCollection"}

    with pytest.raises(RouteComputerError) as exc_info:
        await route_computer.compute_route(start_position, dest_position, "1866")

    assert "keine Route berechnet" in str(exc_info.value)


@pytest.mark.asyncio
async def test_compute_route_invalid_feature_structure(
    route_computer, mock_client, start_position, dest_position
):
    """Test that a malformed feature raises RouteComputerError."""
    mock_client.get_indoor_route.return_value = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                # Missing "geometry" and "properties"
            }
        ],
    }

    with pytest.raises(RouteComputerError) as exc_info:
        await route_computer.compute_route(start_position, dest_position, "1866")

    assert "nicht verarbeitet" in str(exc_info.value)


# --- Test: Segment Types ---


@pytest.mark.asyncio
async def test_all_segment_types(route_computer, mock_client, start_position, dest_position):
    """Test that all valid segment types are correctly parsed."""
    segment_types = ["WALK", "STAIRS", "ESCALATOR", "ELEVATOR", "RAMP"]
    features = []
    for seg_type in segment_types:
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[8.66, 50.10], [8.67, 50.11]],
            },
            "properties": {
                "type": seg_type,
                "level": "GROUND_FLOOR",
                "length": 10.0,
            },
        }
        if seg_type != "WALK":
            feature["properties"]["toLevel"] = "UPPER_FLOOR_1"
        features.append(feature)

    mock_client.get_indoor_route.return_value = {
        "type": "FeatureCollection",
        "features": features,
    }

    segments = await route_computer.compute_route(start_position, dest_position, "1866")

    assert len(segments) == 5
    for i, seg_type in enumerate(segment_types):
        assert segments[i].segment_type == seg_type

    # WALK should not have target_level set (not in properties)
    assert segments[0].target_level is None
    # Level-change segments should have target_level
    for seg in segments[1:]:
        assert seg.target_level == "UPPER_FLOOR_1"

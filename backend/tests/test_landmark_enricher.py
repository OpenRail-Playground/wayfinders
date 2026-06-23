"""
Tests for the LandmarkEnricher module.

Covers:
- Finding nearest recognizable POI within 30m on same level
- Filtering out ROUTING group POIs
- Fallback to platform number when no landmark found
- Fallback to "Korridor" when no platform nearby
- Non-walk segments get no landmark enrichment
- Multiple POIs: selects closest
- Empty POI list
"""

from pipeline.landmark_enricher import (
    LandmarkEnricher,
    haversine_distance,
    MAX_LANDMARK_DISTANCE_M,
    _is_recognizable_landmark,
)
from pipeline.models import EnrichedSegment, Platform, POI, RouteSegment


def _make_poi(
    name: str = "Test POI",
    category: str = "Shop",
    group: str = "SHOPPING",
    level: str = "GROUND_FLOOR",
    lat: float = 50.1073,
    lon: float = 8.6637,
    poi_id: str = "poi-1",
) -> POI:
    return POI(
        poi_id=poi_id,
        name=name,
        category=category,
        group=group,
        level=level,
        lat=lat,
        lon=lon,
        tags=[],
        detail=None,
    )


def _make_walk_segment(
    level: str = "GROUND_FLOOR",
    endpoint_lon: float = 8.6637,
    endpoint_lat: float = 50.1073,
) -> RouteSegment:
    """Create a WALK segment with a single-point polyline at the given endpoint."""
    return RouteSegment(
        segment_type="WALK",
        level=level,
        length_m=50.0,
        polyline=[(endpoint_lon, endpoint_lat)],
        target_level=None,
    )


def _make_platform(
    name: str = "5/6",
    level: str = "GROUND_FLOOR",
    center_lat: float = 50.1073,
    center_lon: float = 8.6637,
) -> Platform:
    return Platform(
        name=name,
        level=level,
        center_lat=center_lat,
        center_lon=center_lon,
        category="TRACK",
    )


class TestHaversineDistance:
    """Tests for the haversine distance function."""

    def test_same_point_returns_zero(self):
        assert haversine_distance(50.0, 8.0, 50.0, 8.0) == 0.0

    def test_known_distance(self):
        # Frankfurt Hbf to a point ~100m away
        lat1, lon1 = 50.1073, 8.6637
        # Approx 100m north
        lat2, lon2 = 50.1082, 8.6637
        dist = haversine_distance(lat1, lon1, lat2, lon2)
        assert 90 < dist < 110  # ~100m

    def test_short_distance_within_station(self):
        # Two points ~10m apart
        lat1, lon1 = 50.1073, 8.6637
        lat2, lon2 = 50.1073, 8.66384  # ~10m east at this latitude
        dist = haversine_distance(lat1, lon1, lat2, lon2)
        assert 5 < dist < 15


class TestIsRecognizableLandmark:
    """Tests for the landmark recognition filter."""

    def test_shopping_group_is_landmark(self):
        poi = _make_poi(group="SHOPPING")
        assert _is_recognizable_landmark(poi) is True

    def test_station_facility_is_landmark(self):
        poi = _make_poi(group="STATION_FACILITY", category="TravelService")
        assert _is_recognizable_landmark(poi) is True

    def test_routing_group_excluded(self):
        poi = _make_poi(name="Treppe", group="ROUTING", category="Stairs")
        assert _is_recognizable_landmark(poi) is False

    def test_named_non_routing_is_landmark(self):
        poi = _make_poi(name="Gepäckaufbewahrung", group="OTHER", category="Service")
        assert _is_recognizable_landmark(poi) is True


class TestLandmarkEnricher:
    """Tests for the LandmarkEnricher.enrich() method."""

    def setup_method(self):
        self.enricher = LandmarkEnricher()

    def test_finds_nearest_poi_within_30m_same_level(self):
        # POI is at the same location as the segment endpoint
        poi = _make_poi(lat=50.1073, lon=8.6637, level="GROUND_FLOOR")
        segment = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1073, endpoint_lon=8.6637
        )

        result = self.enricher.enrich([segment], [poi], [])
        assert len(result) == 1
        assert result[0].landmark_poi == poi
        assert result[0].landmark_distance_m == 0.0
        assert result[0].fallback_cue is None

    def test_ignores_poi_on_different_level(self):
        poi = _make_poi(lat=50.1073, lon=8.6637, level="UPPER_FLOOR_1")
        segment = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1073, endpoint_lon=8.6637
        )

        result = self.enricher.enrich([segment], [poi], [])
        assert result[0].landmark_poi is None
        assert result[0].fallback_cue == "Korridor"

    def test_ignores_poi_beyond_30m(self):
        # POI is ~500m away
        poi = _make_poi(lat=50.1120, lon=8.6637, level="GROUND_FLOOR")
        segment = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1073, endpoint_lon=8.6637
        )

        result = self.enricher.enrich([segment], [poi], [])
        assert result[0].landmark_poi is None

    def test_excludes_routing_pois(self):
        poi = _make_poi(
            name="Escalator",
            group="ROUTING",
            category="Escalator",
            lat=50.1073,
            lon=8.6637,
            level="GROUND_FLOOR",
        )
        segment = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1073, endpoint_lon=8.6637
        )

        result = self.enricher.enrich([segment], [poi], [])
        assert result[0].landmark_poi is None

    def test_selects_closest_of_multiple_pois(self):
        poi_far = _make_poi(
            name="Far Shop",
            lat=50.10745,
            lon=8.6637,
            level="GROUND_FLOOR",
            poi_id="far",
        )
        poi_close = _make_poi(
            name="Close Shop",
            lat=50.10731,
            lon=8.6637,
            level="GROUND_FLOOR",
            poi_id="close",
        )
        segment = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1073, endpoint_lon=8.6637
        )

        result = self.enricher.enrich([segment], [poi_far, poi_close], [])
        assert result[0].landmark_poi == poi_close

    def test_fallback_to_platform_number(self):
        platform = _make_platform(
            name="5/6", level="GROUND_FLOOR", center_lat=50.1073, center_lon=8.6637
        )
        segment = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1073, endpoint_lon=8.6637
        )

        result = self.enricher.enrich([segment], [], [platform])
        assert result[0].landmark_poi is None
        assert result[0].fallback_cue == "Gleis 5/6"

    def test_fallback_to_korridor_no_nearby_platform(self):
        # Platform is very far away
        platform = _make_platform(
            name="10", level="GROUND_FLOOR", center_lat=50.120, center_lon=8.680
        )
        segment = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1073, endpoint_lon=8.6637
        )

        result = self.enricher.enrich([segment], [], [platform])
        assert result[0].landmark_poi is None
        assert result[0].fallback_cue == "Korridor"

    def test_non_walk_segment_no_landmark(self):
        poi = _make_poi(lat=50.1073, lon=8.6637, level="GROUND_FLOOR")
        segment = RouteSegment(
            segment_type="ESCALATOR",
            level="GROUND_FLOOR",
            length_m=20.0,
            polyline=[(8.6637, 50.1073)],
            target_level="UPPER_FLOOR_1",
        )

        result = self.enricher.enrich([segment], [poi], [])
        assert result[0].landmark_poi is None
        assert result[0].landmark_distance_m == 0.0
        assert result[0].fallback_cue is None

    def test_empty_segments_returns_empty(self):
        result = self.enricher.enrich([], [], [])
        assert result == []

    def test_empty_poi_list_with_walk_segment(self):
        segment = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1073, endpoint_lon=8.6637
        )
        result = self.enricher.enrich([segment], [], [])
        assert result[0].landmark_poi is None
        assert result[0].fallback_cue == "Korridor"

    def test_multiple_segments_enriched_independently(self):
        poi1 = _make_poi(
            name="Shop A",
            lat=50.1073,
            lon=8.6637,
            level="GROUND_FLOOR",
            poi_id="a",
        )
        poi2 = _make_poi(
            name="Shop B",
            lat=50.1080,
            lon=8.6640,
            level="GROUND_FLOOR",
            poi_id="b",
        )
        seg1 = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1073, endpoint_lon=8.6637
        )
        seg2 = _make_walk_segment(
            level="GROUND_FLOOR", endpoint_lat=50.1080, endpoint_lon=8.6640
        )

        result = self.enricher.enrich([seg1, seg2], [poi1, poi2], [])
        assert result[0].landmark_poi == poi1
        assert result[1].landmark_poi == poi2

    def test_walk_segment_uses_last_polyline_point(self):
        """The endpoint should be the LAST coordinate in the polyline."""
        poi = _make_poi(lat=50.1080, lon=8.6640, level="GROUND_FLOOR")
        segment = RouteSegment(
            segment_type="WALK",
            level="GROUND_FLOOR",
            length_m=100.0,
            polyline=[
                (8.6637, 50.1073),  # start
                (8.6638, 50.1075),  # mid
                (8.6640, 50.1080),  # end — POI is here
            ],
            target_level=None,
        )

        result = self.enricher.enrich([segment], [poi], [])
        assert result[0].landmark_poi == poi

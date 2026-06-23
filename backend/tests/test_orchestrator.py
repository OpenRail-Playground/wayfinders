"""Unit tests for NavigationOrchestrator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pipeline.orchestrator import NavigationOrchestrator, OrchestratorError
from pipeline.intent_parser import IntentParserError, ParsedIntent
from pipeline.poi_resolver import POIResolverError
from pipeline.route_computer import RouteComputerError
from pipeline.description_generator import DescriptionGeneratorError
from pipeline.models import Position, RouteSegment, EnrichedSegment, POI, Platform
from clients.genai_client import GenAIClient
from clients.ris_maps_client import RISMapsClient, RISMapsNoContentError, RISMapsServerError


@pytest.fixture
def mock_ris_maps_client():
    """Create a mock RISMapsClient."""
    client = MagicMock(spec=RISMapsClient)
    client.get_pois = AsyncMock(return_value={"pois": []})
    client.get_platforms = AsyncMock(return_value={"platforms": []})
    return client


@pytest.fixture
def mock_genai_client():
    """Create a mock GenAIClient."""
    client = MagicMock(spec=GenAIClient)
    client.complete = AsyncMock()
    return client


@pytest.fixture
def orchestrator(mock_ris_maps_client, mock_genai_client):
    """Create a NavigationOrchestrator with mocked clients."""
    return NavigationOrchestrator(mock_ris_maps_client, mock_genai_client)


@pytest.mark.asyncio
async def test_navigate_full_pipeline_success(orchestrator):
    """Test successful execution of the full pipeline."""
    # Mock IntentParser
    with patch.object(
        orchestrator._intent_parser,
        "parse",
        new_callable=AsyncMock,
        return_value=ParsedIntent(
            start_description="Gleis 5",
            destination_description="Starbucks",
        ),
    ), patch.object(
        orchestrator._poi_resolver,
        "resolve",
        new_callable=AsyncMock,
        return_value=(
            Position(lat=50.1, lon=8.6, level="GROUND_FLOOR"),
            Position(lat=50.2, lon=8.7, level="GROUND_FLOOR"),
        ),
    ), patch.object(
        orchestrator._route_computer,
        "compute_route",
        new_callable=AsyncMock,
        return_value=[
            RouteSegment(
                segment_type="WALK",
                level="GROUND_FLOOR",
                length_m=100.0,
                polyline=[(8.6, 50.1), (8.7, 50.2)],
            )
        ],
    ), patch.object(
        orchestrator._landmark_enricher,
        "enrich",
        return_value=[
            EnrichedSegment(
                segment=RouteSegment(
                    segment_type="WALK",
                    level="GROUND_FLOOR",
                    length_m=100.0,
                    polyline=[(8.6, 50.1), (8.7, 50.2)],
                ),
                landmark_poi=None,
                landmark_distance_m=0.0,
                fallback_cue="Korridor",
            )
        ],
    ), patch.object(
        orchestrator._description_generator,
        "generate",
        new_callable=AsyncMock,
        return_value=["Gehen Sie 100m den Korridor entlang."],
    ):
        result = await orchestrator.navigate("Vom Gleis 5 zum Starbucks", "1866")

    assert result == ["Gehen Sie 100m den Korridor entlang."]


@pytest.mark.asyncio
async def test_navigate_passes_through_intent_parser_error(orchestrator):
    """Test that IntentParserError user_message is passed through."""
    with patch.object(
        orchestrator._intent_parser,
        "parse",
        new_callable=AsyncMock,
        side_effect=IntentParserError(
            "Failed", user_message="Start- oder Zielposition konnte nicht erkannt werden"
        ),
    ):
        with pytest.raises(OrchestratorError) as exc_info:
            await orchestrator.navigate("invalid query", "1866")

    assert exc_info.value.user_message == "Start- oder Zielposition konnte nicht erkannt werden"


@pytest.mark.asyncio
async def test_navigate_passes_through_poi_resolver_error(orchestrator):
    """Test that POIResolverError user_message is passed through."""
    with patch.object(
        orchestrator._intent_parser,
        "parse",
        new_callable=AsyncMock,
        return_value=ParsedIntent(start_description="A", destination_description="B"),
    ), patch.object(
        orchestrator._poi_resolver,
        "resolve",
        new_callable=AsyncMock,
        side_effect=POIResolverError(
            "Failed", user_message="Position konnte nicht im Bahnhof gefunden werden"
        ),
    ):
        with pytest.raises(OrchestratorError) as exc_info:
            await orchestrator.navigate("Von A nach B", "1866")

    assert exc_info.value.user_message == "Position konnte nicht im Bahnhof gefunden werden"


@pytest.mark.asyncio
async def test_navigate_passes_through_route_computer_error(orchestrator):
    """Test that RouteComputerError message is passed through."""
    with patch.object(
        orchestrator._intent_parser,
        "parse",
        new_callable=AsyncMock,
        return_value=ParsedIntent(start_description="A", destination_description="B"),
    ), patch.object(
        orchestrator._poi_resolver,
        "resolve",
        new_callable=AsyncMock,
        return_value=(
            Position(lat=50.1, lon=8.6, level="GROUND_FLOOR"),
            Position(lat=50.2, lon=8.7, level="GROUND_FLOOR"),
        ),
    ), patch.object(
        orchestrator._route_computer,
        "compute_route",
        new_callable=AsyncMock,
        side_effect=RouteComputerError("Es konnte keine Route berechnet werden"),
    ):
        with pytest.raises(OrchestratorError) as exc_info:
            await orchestrator.navigate("Von A nach B", "1866")

    assert exc_info.value.user_message == "Es konnte keine Route berechnet werden"


@pytest.mark.asyncio
async def test_navigate_passes_through_description_generator_error(orchestrator):
    """Test that DescriptionGeneratorError user_message is passed through."""
    with patch.object(
        orchestrator._intent_parser,
        "parse",
        new_callable=AsyncMock,
        return_value=ParsedIntent(start_description="A", destination_description="B"),
    ), patch.object(
        orchestrator._poi_resolver,
        "resolve",
        new_callable=AsyncMock,
        return_value=(
            Position(lat=50.1, lon=8.6, level="GROUND_FLOOR"),
            Position(lat=50.2, lon=8.7, level="GROUND_FLOOR"),
        ),
    ), patch.object(
        orchestrator._route_computer,
        "compute_route",
        new_callable=AsyncMock,
        return_value=[
            RouteSegment(
                segment_type="WALK",
                level="GROUND_FLOOR",
                length_m=50.0,
                polyline=[(8.6, 50.1), (8.7, 50.2)],
            )
        ],
    ), patch.object(
        orchestrator._landmark_enricher,
        "enrich",
        return_value=[
            EnrichedSegment(
                segment=RouteSegment(
                    segment_type="WALK",
                    level="GROUND_FLOOR",
                    length_m=50.0,
                    polyline=[(8.6, 50.1), (8.7, 50.2)],
                ),
                landmark_poi=None,
                landmark_distance_m=0.0,
                fallback_cue="Korridor",
            )
        ],
    ), patch.object(
        orchestrator._description_generator,
        "generate",
        new_callable=AsyncMock,
        side_effect=DescriptionGeneratorError(
            "LLM failed",
            user_message="KI-Service ist vorübergehend nicht verfügbar",
        ),
    ):
        with pytest.raises(OrchestratorError) as exc_info:
            await orchestrator.navigate("Von A nach B", "1866")

    assert exc_info.value.user_message == "KI-Service ist vorübergehend nicht verfügbar"


@pytest.mark.asyncio
async def test_navigate_unexpected_error_gives_generic_message(orchestrator):
    """Test that unexpected errors produce a generic user-facing message."""
    with patch.object(
        orchestrator._intent_parser,
        "parse",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Something unexpected happened"),
    ):
        with pytest.raises(OrchestratorError) as exc_info:
            await orchestrator.navigate("Von A nach B", "1866")

    assert exc_info.value.user_message == "Anfrage konnte nicht verarbeitet werden"


@pytest.mark.asyncio
async def test_navigate_logs_warning_when_exceeds_soft_target(orchestrator, caplog):
    """Test that a warning is logged when pipeline exceeds 15s soft target."""
    import time

    async def slow_parse(query):
        # We can't actually wait 15s in a test, so we patch time.monotonic
        return ParsedIntent(start_description="A", destination_description="B")

    # Patch time.monotonic only within _run_pipeline by providing enough values
    # for both the event loop (which calls monotonic internally) and our code.
    # Instead, we patch at the module level with a function that simulates elapsed time.
    call_count = {"n": 0}
    real_monotonic = time.monotonic

    def fake_monotonic():
        call_count["n"] += 1
        # First call in _run_pipeline is start_time, second call is in finally block
        # But asyncio event loop also calls monotonic, so we only fake within our module
        # by using a wrapper that returns predictable values for our code.
        return real_monotonic()

    # Use a simpler approach: patch SOFT_TARGET_SECONDS to 0 so any elapsed time triggers warning
    with patch.object(
        orchestrator._intent_parser,
        "parse",
        new_callable=AsyncMock,
        return_value=ParsedIntent(start_description="A", destination_description="B"),
    ), patch.object(
        orchestrator._poi_resolver,
        "resolve",
        new_callable=AsyncMock,
        return_value=(
            Position(lat=50.1, lon=8.6, level="GROUND_FLOOR"),
            Position(lat=50.2, lon=8.7, level="GROUND_FLOOR"),
        ),
    ), patch.object(
        orchestrator._route_computer,
        "compute_route",
        new_callable=AsyncMock,
        return_value=[
            RouteSegment(
                segment_type="WALK",
                level="GROUND_FLOOR",
                length_m=50.0,
                polyline=[(8.6, 50.1), (8.7, 50.2)],
            )
        ],
    ), patch.object(
        orchestrator._landmark_enricher,
        "enrich",
        return_value=[
            EnrichedSegment(
                segment=RouteSegment(
                    segment_type="WALK",
                    level="GROUND_FLOOR",
                    length_m=50.0,
                    polyline=[(8.6, 50.1), (8.7, 50.2)],
                ),
                landmark_poi=None,
                landmark_distance_m=0.0,
                fallback_cue="Korridor",
            )
        ],
    ), patch.object(
        orchestrator._description_generator,
        "generate",
        new_callable=AsyncMock,
        return_value=["Weiter geradeaus."],
    ), patch(
        "pipeline.orchestrator.SOFT_TARGET_SECONDS", 0.0,
    ):
        import logging

        with caplog.at_level(logging.WARNING, logger="pipeline.orchestrator"):
            result = await orchestrator.navigate("Von A nach B", "1866")

    assert result == ["Weiter geradeaus."]
    assert "exceeded soft target" in caplog.text


@pytest.mark.asyncio
async def test_fetch_pois_and_platforms_graceful_degradation(
    orchestrator, mock_ris_maps_client
):
    """Test that POI/platform fetch failures degrade gracefully."""
    mock_ris_maps_client.get_pois.side_effect = RISMapsServerError(
        "Server error", status_code=500
    )
    mock_ris_maps_client.get_platforms.side_effect = RISMapsNoContentError()

    pois, platforms = await orchestrator._fetch_pois_and_platforms("1866")

    assert pois == []
    assert platforms == []


@pytest.mark.asyncio
async def test_fetch_pois_and_platforms_parses_data(orchestrator, mock_ris_maps_client):
    """Test that POI and platform data is correctly parsed into model objects."""
    mock_ris_maps_client.get_pois.return_value = {
        "pois": [
            {
                "id": "poi-1",
                "name": "Starbucks",
                "category": "CoffeeShop",
                "group": "SHOPPING",
                "level": "GROUND_FLOOR",
                "displayPosition": {"lat": 50.1, "lon": 8.6},
                "tags": ["Kaffee"],
                "detail": None,
            }
        ]
    }
    mock_ris_maps_client.get_platforms.return_value = {
        "platforms": [
            {
                "name": "5/6",
                "level": "GROUND_FLOOR",
                "center": {"lat": 50.2, "lon": 8.7},
                "category": "TRACK",
            }
        ]
    }

    pois, platforms = await orchestrator._fetch_pois_and_platforms("1866")

    assert len(pois) == 1
    assert pois[0].name == "Starbucks"
    assert pois[0].lat == 50.1
    assert pois[0].lon == 8.6

    assert len(platforms) == 1
    assert platforms[0].name == "5/6"
    assert platforms[0].center_lat == 50.2
    assert platforms[0].center_lon == 8.7


@pytest.mark.asyncio
async def test_navigate_hard_timeout_raises_orchestrator_error(orchestrator):
    """Test that exceeding the hard timeout raises OrchestratorError with timeout message."""
    import asyncio

    async def slow_parse(query):
        await asyncio.sleep(100)  # Simulate a very slow operation
        return ParsedIntent(start_description="A", destination_description="B")

    with patch.object(
        orchestrator._intent_parser,
        "parse",
        side_effect=slow_parse,
    ), patch(
        "pipeline.orchestrator.HARD_TIMEOUT_SECONDS", 0.1,  # 100ms for test speed
    ):
        with pytest.raises(OrchestratorError) as exc_info:
            await orchestrator.navigate("Von A nach B", "1866")

    assert exc_info.value.user_message == "Anfrage hat zu lange gedauert"

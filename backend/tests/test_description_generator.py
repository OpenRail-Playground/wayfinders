"""Unit tests for DescriptionGenerator."""

from __future__ import annotations

import json
from typing import Optional

import pytest
from unittest.mock import AsyncMock, MagicMock

from pipeline.description_generator import (
    DescriptionGenerator,
    DescriptionGeneratorError,
    SYSTEM_PROMPT,
    _display_level,
)
from pipeline.models import EnrichedSegment, POI, RouteSegment
from clients.genai_client import GenAIClient, GenAITimeoutError, GenAIServiceError


@pytest.fixture
def mock_genai_client():
    """Create a mock GenAIClient."""
    client = MagicMock(spec=GenAIClient)
    client.complete = AsyncMock()
    return client


@pytest.fixture
def generator(mock_genai_client):
    """Create a DescriptionGenerator with a mocked GenAI client."""
    return DescriptionGenerator(mock_genai_client)


def _make_walk_segment(
    level: str = "GROUND_FLOOR",
    length_m: float = 50.0,
) -> RouteSegment:
    return RouteSegment(
        segment_type="WALK",
        level=level,
        length_m=length_m,
        polyline=[(8.6637, 50.1073), (8.6640, 50.1075)],
        target_level=None,
    )


def _make_level_change_segment(
    segment_type: str = "ESCALATOR",
    level: str = "GROUND_FLOOR",
    target_level: str = "BASEMENT_FLOOR_1",
    length_m: float = 12.0,
) -> RouteSegment:
    return RouteSegment(
        segment_type=segment_type,
        level=level,
        length_m=length_m,
        polyline=[(8.6637, 50.1073)],
        target_level=target_level,
    )


def _make_poi(
    name: str = "Starbucks",
    category: str = "Shop",
    group: str = "SHOPPING",
    level: str = "GROUND_FLOOR",
) -> POI:
    return POI(
        poi_id="poi-1",
        name=name,
        category=category,
        group=group,
        level=level,
        lat=50.1073,
        lon=8.6637,
    )


def _make_enriched_segment_with_landmark(
    segment: Optional[RouteSegment] = None,
    poi: Optional[POI] = None,
    distance: float = 5.0,
) -> EnrichedSegment:
    return EnrichedSegment(
        segment=segment or _make_walk_segment(),
        landmark_poi=poi or _make_poi(),
        landmark_distance_m=distance,
        fallback_cue=None,
    )


def _make_enriched_segment_with_fallback(
    segment: Optional[RouteSegment] = None,
    fallback_cue: str = "Korridor",
) -> EnrichedSegment:
    return EnrichedSegment(
        segment=segment or _make_walk_segment(),
        landmark_poi=None,
        landmark_distance_m=0.0,
        fallback_cue=fallback_cue,
    )


def _make_enriched_level_change(
    segment_type: str = "ESCALATOR",
    target_level: str = "BASEMENT_FLOOR_1",
) -> EnrichedSegment:
    return EnrichedSegment(
        segment=_make_level_change_segment(
            segment_type=segment_type, target_level=target_level
        ),
        landmark_poi=None,
        landmark_distance_m=0.0,
        fallback_cue=None,
    )


@pytest.mark.asyncio
async def test_generate_single_walk_segment_with_landmark(generator, mock_genai_client):
    """Test generating instruction for a single walk segment with POI landmark."""
    mock_genai_client.complete.return_value = json.dumps(
        ["Gehen Sie Richtung Starbucks (ca. 50m)."]
    )

    segments = [_make_enriched_segment_with_landmark()]
    result = await generator.generate(segments)

    assert len(result) == 1
    assert "Starbucks" in result[0]


@pytest.mark.asyncio
async def test_generate_single_walk_segment_with_fallback(generator, mock_genai_client):
    """Test generating instruction for a walk segment with fallback cue."""
    mock_genai_client.complete.return_value = json.dumps(
        ["Gehen Sie den Korridor entlang (ca. 50m)."]
    )

    segments = [_make_enriched_segment_with_fallback(fallback_cue="Korridor")]
    result = await generator.generate(segments)

    assert len(result) == 1
    assert "Korridor" in result[0]


@pytest.mark.asyncio
async def test_generate_level_change_segment(generator, mock_genai_client):
    """Test generating instruction for a level-change segment."""
    mock_genai_client.complete.return_value = json.dumps(
        ["Nehmen Sie die Rolltreppe hinunter zum Untergeschoss 1."]
    )

    segments = [_make_enriched_level_change(segment_type="ESCALATOR", target_level="BASEMENT_FLOOR_1")]
    result = await generator.generate(segments)

    assert len(result) == 1
    assert "Rolltreppe" in result[0] or "Untergeschoss" in result[0]


@pytest.mark.asyncio
async def test_generate_multiple_segments(generator, mock_genai_client):
    """Test generating instructions for multiple segments."""
    mock_genai_client.complete.return_value = json.dumps([
        "Gehen Sie Richtung Starbucks (ca. 50m).",
        "Nehmen Sie die Rolltreppe hinunter zum Untergeschoss 1.",
        "Gehen Sie den Korridor entlang (ca. 30m).",
    ])

    segments = [
        _make_enriched_segment_with_landmark(),
        _make_enriched_level_change(),
        _make_enriched_segment_with_fallback(
            segment=_make_walk_segment(level="BASEMENT_FLOOR_1", length_m=30.0),
            fallback_cue="Korridor",
        ),
    ]
    result = await generator.generate(segments)

    assert len(result) == 3


@pytest.mark.asyncio
async def test_generate_empty_segments_returns_empty_list(generator, mock_genai_client):
    """Test that empty segment list returns empty instructions without LLM call."""
    result = await generator.generate([])

    assert result == []
    mock_genai_client.complete.assert_not_called()


@pytest.mark.asyncio
async def test_generate_passes_system_prompt(generator, mock_genai_client):
    """Test that the system prompt is passed to the LLM."""
    mock_genai_client.complete.return_value = json.dumps(["Instruction."])

    await generator.generate([_make_enriched_segment_with_landmark()])

    call_kwargs = mock_genai_client.complete.call_args[1]
    assert call_kwargs["system_message"] == SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_generate_user_prompt_includes_landmark_name(generator, mock_genai_client):
    """Test that the user prompt includes the landmark POI name."""
    mock_genai_client.complete.return_value = json.dumps(["Instruction."])

    poi = _make_poi(name="DB Lounge")
    segments = [_make_enriched_segment_with_landmark(poi=poi)]
    await generator.generate(segments)

    call_kwargs = mock_genai_client.complete.call_args[1]
    user_msg = call_kwargs["messages"][0]["content"][0]["text"]
    assert "DB Lounge" in user_msg


@pytest.mark.asyncio
async def test_generate_user_prompt_includes_facility_and_target_level(generator, mock_genai_client):
    """Test that level-change segments include facility type and target level."""
    mock_genai_client.complete.return_value = json.dumps(["Instruction."])

    segments = [_make_enriched_level_change(segment_type="ELEVATOR", target_level="UPPER_FLOOR_1")]
    await generator.generate(segments)

    call_kwargs = mock_genai_client.complete.call_args[1]
    user_msg = call_kwargs["messages"][0]["content"][0]["text"]
    assert "Aufzug" in user_msg
    assert "Obergeschoss 1" in user_msg


@pytest.mark.asyncio
async def test_generate_raises_error_on_genai_timeout(generator, mock_genai_client):
    """Test that GenAI timeout raises DescriptionGeneratorError."""
    mock_genai_client.complete.side_effect = GenAITimeoutError("Request timed out")

    with pytest.raises(DescriptionGeneratorError) as exc_info:
        await generator.generate([_make_enriched_segment_with_landmark()])

    assert exc_info.value.user_message == "KI-Service ist vorübergehend nicht verfügbar"


@pytest.mark.asyncio
async def test_generate_raises_error_on_genai_service_error(generator, mock_genai_client):
    """Test that GenAI service error raises DescriptionGeneratorError."""
    mock_genai_client.complete.side_effect = GenAIServiceError("503 error", status_code=503)

    with pytest.raises(DescriptionGeneratorError) as exc_info:
        await generator.generate([_make_enriched_segment_with_landmark()])

    assert exc_info.value.user_message == "KI-Service ist vorübergehend nicht verfügbar"


@pytest.mark.asyncio
async def test_generate_raises_error_on_invalid_json(generator, mock_genai_client):
    """Test that invalid JSON response raises DescriptionGeneratorError."""
    mock_genai_client.complete.return_value = "This is not JSON"

    with pytest.raises(DescriptionGeneratorError) as exc_info:
        await generator.generate([_make_enriched_segment_with_landmark()])

    assert "konnte nicht erstellt werden" in exc_info.value.user_message


@pytest.mark.asyncio
async def test_generate_raises_error_on_non_array_json(generator, mock_genai_client):
    """Test that a non-array JSON response raises DescriptionGeneratorError."""
    mock_genai_client.complete.return_value = '{"instruction": "Walk ahead"}'

    with pytest.raises(DescriptionGeneratorError) as exc_info:
        await generator.generate([_make_enriched_segment_with_landmark()])

    assert "konnte nicht erstellt werden" in exc_info.value.user_message


@pytest.mark.asyncio
async def test_generate_handles_markdown_code_block(generator, mock_genai_client):
    """Test that markdown code block wrapping is handled."""
    mock_genai_client.complete.return_value = (
        '```json\n["Gehen Sie Richtung Starbucks."]\n```'
    )

    segments = [_make_enriched_segment_with_landmark()]
    result = await generator.generate(segments)

    assert len(result) == 1
    assert "Starbucks" in result[0]


@pytest.mark.asyncio
async def test_generate_pads_if_too_few_instructions(generator, mock_genai_client):
    """Test that fewer instructions than segments are padded."""
    mock_genai_client.complete.return_value = json.dumps(["Only one instruction."])

    segments = [
        _make_enriched_segment_with_landmark(),
        _make_enriched_segment_with_fallback(),
    ]
    result = await generator.generate(segments)

    assert len(result) == 2
    assert result[0] == "Only one instruction."
    assert result[1] == "Weiter geradeaus gehen."


@pytest.mark.asyncio
async def test_generate_truncates_if_too_many_instructions(generator, mock_genai_client):
    """Test that more instructions than segments are truncated."""
    mock_genai_client.complete.return_value = json.dumps([
        "Instruction 1.",
        "Instruction 2.",
        "Instruction 3.",
    ])

    segments = [_make_enriched_segment_with_landmark()]
    result = await generator.generate(segments)

    assert len(result) == 1
    assert result[0] == "Instruction 1."


@pytest.mark.asyncio
async def test_generate_handles_whitespace_in_response(generator, mock_genai_client):
    """Test that leading/trailing whitespace in response is handled."""
    mock_genai_client.complete.return_value = '  \n["Gehen Sie geradeaus."]\n  '

    segments = [_make_enriched_segment_with_landmark()]
    result = await generator.generate(segments)

    assert len(result) == 1
    assert result[0] == "Gehen Sie geradeaus."


@pytest.mark.asyncio
async def test_generate_stairs_segment(generator, mock_genai_client):
    """Test instruction generation for stairs."""
    mock_genai_client.complete.return_value = json.dumps(
        ["Nehmen Sie die Treppe hoch zum Obergeschoss 1."]
    )

    segments = [_make_enriched_level_change(segment_type="STAIRS", target_level="UPPER_FLOOR_1")]
    result = await generator.generate(segments)

    assert len(result) == 1


@pytest.mark.asyncio
async def test_generate_user_prompt_includes_fallback_cue(generator, mock_genai_client):
    """Test that the user prompt includes fallback cue when no landmark."""
    mock_genai_client.complete.return_value = json.dumps(["Instruction."])

    segments = [_make_enriched_segment_with_fallback(fallback_cue="Gleis 5/6")]
    await generator.generate(segments)

    call_kwargs = mock_genai_client.complete.call_args[1]
    user_msg = call_kwargs["messages"][0]["content"][0]["text"]
    assert "Gleis 5/6" in user_msg


def test_display_level_known_values():
    """Test that known level values are converted to German names."""
    assert _display_level("GROUND_FLOOR") == "Erdgeschoss"
    assert _display_level("BASEMENT_FLOOR_1") == "Untergeschoss 1"
    assert _display_level("UPPER_FLOOR_1") == "Obergeschoss 1"
    assert _display_level("UPPER_FLOOR_2") == "Obergeschoss 2"


def test_display_level_unknown_value():
    """Test that unknown level values are returned as-is."""
    assert _display_level("UNKNOWN_LEVEL") == "UNKNOWN_LEVEL"

"""Unit tests for IntentParser."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from pipeline.intent_parser import IntentParser, IntentParserError, ParsedIntent
from clients.genai_client import GenAIClient, GenAITimeoutError, GenAIServiceError


@pytest.fixture
def mock_genai_client():
    """Create a mock GenAIClient."""
    client = MagicMock(spec=GenAIClient)
    client.complete = AsyncMock()
    return client


@pytest.fixture
def parser(mock_genai_client):
    """Create an IntentParser with a mocked GenAI client."""
    return IntentParser(mock_genai_client)


@pytest.mark.asyncio
async def test_parse_german_query_with_start_and_destination(parser, mock_genai_client):
    """Test parsing a German query that contains both start and destination."""
    mock_genai_client.complete.return_value = (
        '{"start_description": "Gleis 5", "destination_description": "Starbucks"}'
    )

    result = await parser.parse("Ich bin am Gleis 5 und möchte zum Starbucks")

    assert isinstance(result, ParsedIntent)
    assert result.start_description == "Gleis 5"
    assert result.destination_description == "Starbucks"


@pytest.mark.asyncio
async def test_parse_english_query(parser, mock_genai_client):
    """Test parsing an English query."""
    mock_genai_client.complete.return_value = (
        '{"start_description": "platform 3", "destination_description": "DB Lounge"}'
    )

    result = await parser.parse("I'm at platform 3 and need to get to the DB Lounge")

    assert result.start_description == "platform 3"
    assert result.destination_description == "DB Lounge"


@pytest.mark.asyncio
async def test_parse_passes_query_as_user_message(parser, mock_genai_client):
    """Test that the user query is passed in AWS Converse message format."""
    mock_genai_client.complete.return_value = (
        '{"start_description": "Eingang", "destination_description": "Gleis 1"}'
    )

    await parser.parse("Vom Eingang zum Gleis 1")

    mock_genai_client.complete.assert_called_once()
    call_kwargs = mock_genai_client.complete.call_args[1]
    assert call_kwargs["messages"] == [
        {"role": "user", "content": [{"text": "Vom Eingang zum Gleis 1"}]}
    ]
    assert call_kwargs["system_message"] is not None
    assert len(call_kwargs["system_message"]) > 0


@pytest.mark.asyncio
async def test_parse_raises_error_when_start_is_null(parser, mock_genai_client):
    """Test that missing start description raises IntentParserError."""
    mock_genai_client.complete.return_value = (
        '{"start_description": null, "destination_description": "Starbucks"}'
    )

    with pytest.raises(IntentParserError) as exc_info:
        await parser.parse("Bring mich zum Starbucks")

    assert "start" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_parse_raises_error_when_start_is_empty_string(parser, mock_genai_client):
    """Test that empty start description raises IntentParserError."""
    mock_genai_client.complete.return_value = (
        '{"start_description": "", "destination_description": "Ausgang"}'
    )

    with pytest.raises(IntentParserError) as exc_info:
        await parser.parse("Wo ist der Ausgang?")

    assert "start" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_parse_raises_error_when_destination_is_null(parser, mock_genai_client):
    """Test that missing destination raises IntentParserError."""
    mock_genai_client.complete.return_value = (
        '{"start_description": "Gleis 5", "destination_description": null}'
    )

    with pytest.raises(IntentParserError):
        await parser.parse("Ich bin am Gleis 5")


@pytest.mark.asyncio
async def test_parse_raises_error_on_invalid_json(parser, mock_genai_client):
    """Test that invalid JSON from LLM raises IntentParserError."""
    mock_genai_client.complete.return_value = "This is not JSON at all"

    with pytest.raises(IntentParserError) as exc_info:
        await parser.parse("Vom Gleis 3 zum Ausgang")

    assert exc_info.value.user_message == "Start- oder Zielposition konnte nicht erkannt werden"


@pytest.mark.asyncio
async def test_parse_raises_error_on_genai_timeout(parser, mock_genai_client):
    """Test that GenAI timeout propagates as IntentParserError."""
    mock_genai_client.complete.side_effect = GenAITimeoutError("Request timed out")

    with pytest.raises(IntentParserError) as exc_info:
        await parser.parse("Vom Gleis 5 zum Starbucks")

    assert exc_info.value.user_message == "KI-Service ist vorübergehend nicht verfügbar"


@pytest.mark.asyncio
async def test_parse_raises_error_on_genai_service_error(parser, mock_genai_client):
    """Test that GenAI service error propagates as IntentParserError."""
    mock_genai_client.complete.side_effect = GenAIServiceError("503 error", status_code=503)

    with pytest.raises(IntentParserError) as exc_info:
        await parser.parse("Vom Gleis 5 zum Starbucks")

    assert exc_info.value.user_message == "KI-Service ist vorübergehend nicht verfügbar"


@pytest.mark.asyncio
async def test_parse_handles_json_with_extra_whitespace(parser, mock_genai_client):
    """Test that JSON with leading/trailing whitespace is parsed correctly."""
    mock_genai_client.complete.return_value = (
        '  \n{"start_description": "Haupteingang", "destination_description": "Gleis 12"}\n  '
    )

    result = await parser.parse("Vom Haupteingang zum Gleis 12")

    assert result.start_description == "Haupteingang"
    assert result.destination_description == "Gleis 12"


@pytest.mark.asyncio
async def test_parse_system_prompt_requests_json_format(parser, mock_genai_client):
    """Test that the system prompt instructs JSON output."""
    mock_genai_client.complete.return_value = (
        '{"start_description": "A", "destination_description": "B"}'
    )

    await parser.parse("Von A nach B")

    call_kwargs = mock_genai_client.complete.call_args[1]
    system_msg = call_kwargs["system_message"]
    assert "JSON" in system_msg
    assert "start_description" in system_msg
    assert "destination_description" in system_msg

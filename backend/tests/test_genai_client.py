"""Unit tests for GenAIClient."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from clients.genai_client import (
    GenAIClient,
    GenAIError,
    GenAITimeoutError,
    GenAIServiceError,
    REQUEST_TIMEOUT,
)


@pytest.fixture
def client():
    """Create a GenAIClient instance with test credentials."""
    return GenAIClient(api_key="test-key", endpoint="https://example.com/converse")


@pytest.mark.asyncio
async def test_complete_success(client):
    """Test successful completion returns parsed text."""
    mock_response = httpx.Response(
        status_code=200,
        json={
            "output": {
                "message": {
                    "content": [{"text": "Hello from Claude"}]
                }
            }
        },
    )

    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await client.complete(
            messages=[{"role": "user", "content": [{"text": "Hi"}]}],
            system_message="You are a helpful assistant.",
        )

    assert result == "Hello from Claude"
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["json"]["messages"] == [
        {"role": "user", "content": [{"text": "Hi"}]}
    ]
    assert call_kwargs["json"]["system"] == [{"text": "You are a helpful assistant."}]
    assert call_kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "test-key"


@pytest.mark.asyncio
async def test_complete_without_system_message(client):
    """Test completion without a system message omits the system field."""
    mock_response = httpx.Response(
        status_code=200,
        json={
            "output": {
                "message": {
                    "content": [{"text": "Response"}]
                }
            }
        },
    )

    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        await client.complete(
            messages=[{"role": "user", "content": [{"text": "Hi"}]}],
        )

    call_kwargs = mock_post.call_args[1]
    assert "system" not in call_kwargs["json"]


@pytest.mark.asyncio
async def test_complete_timeout_raises_genai_timeout_error(client):
    """Test that a timeout raises GenAITimeoutError."""
    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Connection timed out")

        with pytest.raises(GenAITimeoutError) as exc_info:
            await client.complete(
                messages=[{"role": "user", "content": [{"text": "Hi"}]}]
            )

    assert "timed out" in str(exc_info.value)


@pytest.mark.asyncio
async def test_complete_http_error_raises_genai_service_error(client):
    """Test that an httpx transport error raises GenAIServiceError."""
    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(GenAIServiceError):
            await client.complete(
                messages=[{"role": "user", "content": [{"text": "Hi"}]}]
            )


@pytest.mark.asyncio
async def test_complete_5xx_raises_genai_service_error(client):
    """Test that a 5xx response raises GenAIServiceError with status code."""
    mock_response = httpx.Response(status_code=503, text="Service Unavailable")

    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        with pytest.raises(GenAIServiceError) as exc_info:
            await client.complete(
                messages=[{"role": "user", "content": [{"text": "Hi"}]}]
            )

    assert exc_info.value.status_code == 503
    assert "unavailable" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_complete_4xx_raises_genai_service_error(client):
    """Test that a 4xx response raises GenAIServiceError with status code."""
    mock_response = httpx.Response(status_code=401, text="Unauthorized")

    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        with pytest.raises(GenAIServiceError) as exc_info:
            await client.complete(
                messages=[{"role": "user", "content": [{"text": "Hi"}]}]
            )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_complete_invalid_response_format_raises_genai_error(client):
    """Test that an unexpected response structure raises GenAIError."""
    mock_response = httpx.Response(
        status_code=200,
        json={"unexpected": "format"},
    )

    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        with pytest.raises(GenAIError) as exc_info:
            await client.complete(
                messages=[{"role": "user", "content": [{"text": "Hi"}]}]
            )

    assert "parse" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_complete_empty_content_raises_genai_error(client):
    """Test that empty content blocks raise GenAIError."""
    mock_response = httpx.Response(
        status_code=200,
        json={
            "output": {
                "message": {
                    "content": []
                }
            }
        },
    )

    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        with pytest.raises(GenAIError):
            await client.complete(
                messages=[{"role": "user", "content": [{"text": "Hi"}]}]
            )


@pytest.mark.asyncio
async def test_client_uses_env_defaults(monkeypatch):
    """Test that the client reads from env vars when no args provided."""
    monkeypatch.setenv("GENAI_API_KEY", "env-key-123")
    monkeypatch.setenv("GENAI_ENDPOINT", "https://env-endpoint.example.com/converse")

    client = GenAIClient()
    assert client._api_key == "env-key-123"
    assert client._endpoint == "https://env-endpoint.example.com/converse"
    await client.close()


def test_request_timeout_is_30_seconds():
    """Verify the configured timeout matches the 30-second requirement."""
    assert REQUEST_TIMEOUT == 30.0

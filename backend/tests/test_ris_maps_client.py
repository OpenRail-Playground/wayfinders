"""Unit tests for RISMapsClient."""

import pytest
import httpx
from unittest.mock import patch, MagicMock

from clients.ris_maps_client import (
    RISMapsClient,
    RISMapsNoContentError,
    RISMapsClientError,
    RISMapsServerError,
    RISMapsTimeoutError,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
)


@pytest.fixture
def mock_settings():
    """Mock settings for the RIS-Maps client."""
    settings = MagicMock()
    settings.rimaps_base_url = "https://rimaps-tst.example.com/rimapsapi/0.7"
    settings.rimaps_user = "test-user"
    settings.rimaps_password = "test-password"
    return settings


@pytest.fixture
def client(mock_settings):
    """Create a RISMapsClient with mocked settings."""
    with patch("clients.ris_maps_client.get_settings", return_value=mock_settings):
        return RISMapsClient()


@pytest.mark.asyncio
async def test_get_stations_success(client):
    """Test successful station list retrieval."""
    mock_data = {
        "stations": [
            {"zoneID": "1866", "name": "Frankfurt (Main) Hbf", "hasRouting": True}
        ]
    }
    mock_response = httpx.Response(status_code=200, json=mock_data)

    with patch("httpx.AsyncClient.request", return_value=mock_response):
        result = await client.get_stations()

    assert result == mock_data
    assert result["stations"][0]["zoneID"] == "1866"


@pytest.mark.asyncio
async def test_get_pois_success(client):
    """Test successful POI list retrieval."""
    mock_data = {
        "pois": [
            {"poiID": "123", "name": "Starbucks", "category": "SHOPPING"}
        ]
    }
    mock_response = httpx.Response(status_code=200, json=mock_data)

    with patch("httpx.AsyncClient.request", return_value=mock_response):
        result = await client.get_pois("1866")

    assert result == mock_data


@pytest.mark.asyncio
async def test_get_platforms_success(client):
    """Test successful platform list retrieval."""
    mock_data = {
        "platforms": [
            {"name": "101/102", "level": "GROUND_FLOOR"}
        ]
    }
    mock_response = httpx.Response(status_code=200, json=mock_data)

    with patch("httpx.AsyncClient.request", return_value=mock_response):
        result = await client.get_platforms("1866")

    assert result == mock_data


@pytest.mark.asyncio
async def test_get_indoor_route_success(client):
    """Test successful indoor route computation."""
    mock_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[8.66, 50.11], [8.67, 50.12]]},
                "properties": {"segmentType": "WALK", "level": "GROUND_FLOOR", "length": 42.5},
            }
        ],
    }
    mock_response = httpx.Response(status_code=200, json=mock_data)

    with patch("httpx.AsyncClient.request", return_value=mock_response) as mock_request:
        result = await client.get_indoor_route(
            zone_id="1866",
            from_level="GROUND_FLOOR",
            from_lat=50.107,
            from_lon=8.663,
            to_level="BASEMENT_FLOOR_1",
            to_lat=50.108,
            to_lon=8.664,
        )

    assert result == mock_data
    # Verify query parameters were passed correctly
    call_args = mock_request.call_args
    params = call_args[1]["params"]
    assert params["zoneID"] == "1866"
    assert params["fromLevel"] == "GROUND_FLOOR"
    assert params["toLevel"] == "BASEMENT_FLOOR_1"
    assert params["handicapped"] == "false"


@pytest.mark.asyncio
async def test_204_no_content_raises_no_content_error(client):
    """Test that 204 responses raise RISMapsNoContentError."""
    mock_response = httpx.Response(status_code=204)

    with patch("httpx.AsyncClient.request", return_value=mock_response):
        with pytest.raises(RISMapsNoContentError):
            await client.get_indoor_route(
                zone_id="1866",
                from_level="GROUND_FLOOR",
                from_lat=50.107,
                from_lon=8.663,
                to_level="GROUND_FLOOR",
                to_lat=50.108,
                to_lon=8.664,
            )


@pytest.mark.asyncio
async def test_4xx_raises_client_error(client):
    """Test that 4xx responses raise RISMapsClientError without retry."""
    mock_response = httpx.Response(status_code=401, text="Unauthorized")

    with patch("httpx.AsyncClient.request", return_value=mock_response) as mock_request:
        with pytest.raises(RISMapsClientError) as exc_info:
            await client.get_stations()

    assert exc_info.value.status_code == 401
    # 4xx should NOT be retried
    assert mock_request.call_count == 1


@pytest.mark.asyncio
async def test_403_raises_client_error(client):
    """Test that 403 responses raise RISMapsClientError."""
    mock_response = httpx.Response(status_code=403, text="Forbidden")

    with patch("httpx.AsyncClient.request", return_value=mock_response):
        with pytest.raises(RISMapsClientError) as exc_info:
            await client.get_pois("1866")

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_5xx_retries_and_raises_server_error(client):
    """Test that 5xx responses are retried once then raise RISMapsServerError."""
    mock_response = httpx.Response(status_code=503, text="Service Unavailable")

    with patch("httpx.AsyncClient.request", return_value=mock_response) as mock_request:
        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RISMapsServerError) as exc_info:
                await client.get_stations()

    assert exc_info.value.status_code == 503
    # Should be called 1 + MAX_RETRIES = 2 times
    assert mock_request.call_count == 1 + MAX_RETRIES


@pytest.mark.asyncio
async def test_5xx_retry_success_on_second_attempt(client):
    """Test that a 5xx followed by success works correctly."""
    mock_error_response = httpx.Response(status_code=500, text="Internal Server Error")
    mock_success_response = httpx.Response(
        status_code=200, json={"stations": []}
    )

    with patch(
        "httpx.AsyncClient.request",
        side_effect=[mock_error_response, mock_success_response],
    ) as mock_request:
        with patch("asyncio.sleep", return_value=None):
            result = await client.get_stations()

    assert result == {"stations": []}
    assert mock_request.call_count == 2


@pytest.mark.asyncio
async def test_timeout_raises_timeout_error(client):
    """Test that a timeout raises RISMapsTimeoutError."""
    with patch(
        "httpx.AsyncClient.request",
        side_effect=httpx.TimeoutException("Connection timed out"),
    ):
        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RISMapsTimeoutError):
                await client.get_stations()


@pytest.mark.asyncio
async def test_timeout_retries_once(client):
    """Test that timeout errors are retried."""
    with patch(
        "httpx.AsyncClient.request",
        side_effect=httpx.TimeoutException("Connection timed out"),
    ) as mock_request:
        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RISMapsTimeoutError):
                await client.get_stations()

    # Should attempt 1 + MAX_RETRIES = 2 times
    assert mock_request.call_count == 1 + MAX_RETRIES


@pytest.mark.asyncio
async def test_base_url_trailing_slash_stripped(mock_settings):
    """Test that trailing slashes in base URL are properly stripped."""
    mock_settings.rimaps_base_url = "https://example.com/api/0.7/"
    with patch("clients.ris_maps_client.get_settings", return_value=mock_settings):
        client = RISMapsClient()

    assert client._base_url == "https://example.com/api/0.7"


def test_request_timeout_is_30_seconds():
    """Verify the configured timeout matches the 30-second requirement."""
    assert REQUEST_TIMEOUT == 30.0


def test_max_retries_is_1():
    """Verify the configured retry count is 1."""
    assert MAX_RETRIES == 1

"""Unit tests for the GET /api/stations endpoint."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from httpx import AsyncClient, ASGITransport

from main import app
from clients.ris_maps_client import (
    RISMapsClientError,
    RISMapsServerError,
    RISMapsTimeoutError,
)


@pytest.fixture
def mock_settings():
    """Mock settings so the app doesn't require real env vars."""
    settings = MagicMock()
    settings.rimaps_base_url = "https://rimaps.example.com/api/0.7"
    settings.rimaps_user = "test-user"
    settings.rimaps_password = "test-password"
    settings.genai_api_key = "test-key"
    settings.genai_endpoint = "https://genai.example.com"
    return settings


@pytest.fixture
def sample_stations_response():
    """Sample RIS-Maps station list response."""
    return {
        "stations": [
            {"zoneID": "1866", "name": "Frankfurt (Main) Hbf", "hasRouting": True},
            {"zoneID": "5555", "name": "Aachen Hbf", "hasRouting": False},
            {"zoneID": "1071", "name": "Berlin Hbf", "hasRouting": True},
            {"zoneID": "2222", "name": "Zürich HB", "hasRouting": True},
            {"zoneID": "3333", "name": "München Hbf", "hasRouting": False},
        ]
    }


@pytest.mark.asyncio
async def test_get_stations_returns_filtered_and_sorted(mock_settings, sample_stations_response):
    """Test that only stations with hasRouting=true are returned, sorted by name."""
    with patch("routes.stations.RISMapsClient") as MockClient:
        instance = MockClient.return_value
        instance.get_stations = AsyncMock(return_value=sample_stations_response)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/stations")

    assert response.status_code == 200
    data = response.json()
    assert "stations" in data
    stations = data["stations"]

    # Only hasRouting=true stations
    assert len(stations) == 3

    # Sorted alphabetically by name
    assert stations[0]["name"] == "Berlin Hbf"
    assert stations[1]["name"] == "Frankfurt (Main) Hbf"
    assert stations[2]["name"] == "Zürich HB"

    # Each station has only zoneID and name
    for s in stations:
        assert set(s.keys()) == {"zoneID", "name"}


@pytest.mark.asyncio
async def test_get_stations_empty_list(mock_settings):
    """Test response when no stations have routing."""
    with patch("routes.stations.RISMapsClient") as MockClient:
        instance = MockClient.return_value
        instance.get_stations = AsyncMock(
            return_value={"stations": [{"zoneID": "1", "name": "Test", "hasRouting": False}]}
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/stations")

    assert response.status_code == 200
    assert response.json() == {"stations": []}


@pytest.mark.asyncio
async def test_get_stations_server_error_returns_503(mock_settings):
    """Test that RIS-Maps 5xx errors return HTTP 503."""
    with patch("routes.stations.RISMapsClient") as MockClient:
        instance = MockClient.return_value
        instance.get_stations = AsyncMock(
            side_effect=RISMapsServerError("Server error", status_code=500)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/stations")

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["error"] == "Bahnhofsdaten sind vorübergehend nicht verfügbar"


@pytest.mark.asyncio
async def test_get_stations_timeout_returns_503(mock_settings):
    """Test that RIS-Maps timeout returns HTTP 503."""
    with patch("routes.stations.RISMapsClient") as MockClient:
        instance = MockClient.return_value
        instance.get_stations = AsyncMock(
            side_effect=RISMapsTimeoutError()
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/stations")

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["error"] == "Bahnhofsdaten sind vorübergehend nicht verfügbar"


@pytest.mark.asyncio
async def test_get_stations_auth_error_returns_503(mock_settings):
    """Test that RIS-Maps 401 auth error returns HTTP 503 with auth message."""
    with patch("routes.stations.RISMapsClient") as MockClient:
        instance = MockClient.return_value
        instance.get_stations = AsyncMock(
            side_effect=RISMapsClientError("Unauthorized", status_code=401)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/stations")

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["error"] == "Authentifizierungsfehler bei Bahnhofsdaten"


@pytest.mark.asyncio
async def test_get_stations_forbidden_returns_503_auth_message(mock_settings):
    """Test that RIS-Maps 403 error returns HTTP 503 with auth message."""
    with patch("routes.stations.RISMapsClient") as MockClient:
        instance = MockClient.return_value
        instance.get_stations = AsyncMock(
            side_effect=RISMapsClientError("Forbidden", status_code=403)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/stations")

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["error"] == "Authentifizierungsfehler bei Bahnhofsdaten"

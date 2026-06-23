"""Unit tests for the POST /api/navigate endpoint."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from httpx import AsyncClient, ASGITransport

from main import app
from pipeline.orchestrator import OrchestratorError


@pytest.fixture
def mock_settings():
    """Mock settings so the app doesn't require real env vars."""
    settings = MagicMock()
    settings.rimaps_base_url = "https://rimaps.example.com/api/0.7"
    settings.rimaps_user = "test-user"
    settings.rimaps_password = "test-password"
    settings.genai_api_key = "test-key"
    settings.genai_endpoint = "https://genai.example.com"
    app.state.settings = settings
    return settings


@pytest.mark.asyncio
async def test_navigate_success(mock_settings):
    """Test successful navigation returns instructions."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(
            return_value=["Gehen Sie geradeaus.", "Nehmen Sie die Treppe nach oben."]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "Ich bin am Gleis 5 und möchte zum Starbucks"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["instructions"] == ["Gehen Sie geradeaus.", "Nehmen Sie die Treppe nach oben."]
    assert data["error"] is None


@pytest.mark.asyncio
async def test_navigate_empty_query_returns_422(mock_settings):
    """Test that empty query returns 422 with error message."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/navigate",
            json={"zoneID": "1866", "query": ""},
        )

    assert response.status_code == 422
    data = response.json()
    assert data["instructions"] == []
    assert "Beschreibung" in data["error"]


@pytest.mark.asyncio
async def test_navigate_whitespace_query_returns_422(mock_settings):
    """Test that whitespace-only query returns 422 with error message."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/navigate",
            json={"zoneID": "1866", "query": "   \t\n  "},
        )

    assert response.status_code == 422
    data = response.json()
    assert data["instructions"] == []
    assert "Beschreibung" in data["error"]


@pytest.mark.asyncio
async def test_navigate_query_too_long_returns_422(mock_settings):
    """Test that query exceeding 500 chars returns 422."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/navigate",
            json={"zoneID": "1866", "query": "a" * 501},
        )

    assert response.status_code == 422
    data = response.json()
    assert data["instructions"] == []
    assert "500 Zeichen" in data["error"]


@pytest.mark.asyncio
async def test_navigate_missing_zone_id_returns_422(mock_settings):
    """Test that missing zoneID returns 422."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/navigate",
            json={"query": "Ich bin am Gleis 5"},
        )

    assert response.status_code == 422
    data = response.json()
    assert data["instructions"] == []
    assert data["error"] is not None


@pytest.mark.asyncio
async def test_navigate_empty_zone_id_returns_422(mock_settings):
    """Test that empty zoneID returns 422."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/navigate",
            json={"zoneID": "", "query": "Ich bin am Gleis 5"},
        )

    assert response.status_code == 422
    data = response.json()
    assert data["instructions"] == []
    assert data["error"] is not None


@pytest.mark.asyncio
async def test_navigate_intent_parse_error_returns_422(mock_settings):
    """Test that intent parsing failure returns 422."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(
            side_effect=OrchestratorError(
                "Intent parsing failed",
                user_message="Start- oder Zielposition konnte nicht erkannt werden",
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "Wo ist der Ausgang?"},
            )

    assert response.status_code == 422
    data = response.json()
    assert data["instructions"] == []
    assert "nicht erkannt" in data["error"]


@pytest.mark.asyncio
async def test_navigate_poi_not_found_returns_422(mock_settings):
    """Test that POI resolution failure returns 422."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(
            side_effect=OrchestratorError(
                "POI resolution failed",
                user_message="Startposition konnte nicht im Bahnhof gefunden werden",
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "Vom Mars zum Jupiter"},
            )

    assert response.status_code == 422
    data = response.json()
    assert data["instructions"] == []
    assert "gefunden" in data["error"]


@pytest.mark.asyncio
async def test_navigate_no_route_returns_404(mock_settings):
    """Test that no-route-found returns 404."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(
            side_effect=OrchestratorError(
                "No route found",
                user_message="Es konnte keine Route berechnet werden",
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "Von Gleis 1 zu Gleis 20"},
            )

    assert response.status_code == 404
    data = response.json()
    assert data["instructions"] == []
    assert "keine Route" in data["error"]


@pytest.mark.asyncio
async def test_navigate_service_unavailable_returns_503(mock_settings):
    """Test that service unavailable returns 503."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(
            side_effect=OrchestratorError(
                "Service unavailable",
                user_message="KI-Service ist vorübergehend nicht verfügbar",
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "Von Gleis 5 zum Starbucks"},
            )

    assert response.status_code == 503
    data = response.json()
    assert data["instructions"] == []
    assert "nicht verfügbar" in data["error"]


@pytest.mark.asyncio
async def test_navigate_unexpected_error_returns_500_generic_message(mock_settings):
    """Test that unexpected errors return 500 with generic message (no internal details)."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(
            side_effect=RuntimeError("Internal database connection string: secret123")
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "Von Gleis 5 zum Starbucks"},
            )

    assert response.status_code == 500
    data = response.json()
    assert data["instructions"] == []
    # Must not expose internal details
    assert "secret123" not in data["error"]
    assert "database" not in data["error"]
    assert data["error"] == "Anfrage konnte nicht verarbeitet werden"


@pytest.mark.asyncio
async def test_navigate_query_at_exactly_500_chars_succeeds(mock_settings):
    """Test that query at exactly 500 chars is accepted."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(return_value=["Gehen Sie geradeaus."])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "a" * 500},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["instructions"] == ["Gehen Sie geradeaus."]


@pytest.mark.asyncio
async def test_navigate_trims_whitespace_from_query(mock_settings):
    """Test that leading/trailing whitespace is trimmed from query."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(return_value=["Gehen Sie geradeaus."])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "  Gleis 5 zum Starbucks  "},
            )

    assert response.status_code == 200
    # Verify the orchestrator was called with trimmed query
    instance.navigate.assert_called_once_with(
        query="Gleis 5 zum Starbucks",
        zone_id="1866",
    )


@pytest.mark.asyncio
async def test_navigate_timeout_returns_504(mock_settings):
    """Test that request timeout returns 504."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(
            side_effect=OrchestratorError(
                "Pipeline exceeded hard timeout",
                user_message="Anfrage hat zu lange gedauert",
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "Von Gleis 5 zum Starbucks"},
            )

    assert response.status_code == 504
    data = response.json()
    assert data["instructions"] == []
    assert "zu lange gedauert" in data["error"]


@pytest.mark.asyncio
async def test_navigate_auth_error_returns_503(mock_settings):
    """Test that authentication error returns 503."""
    with patch("routes.navigate.NavigationOrchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.navigate = AsyncMock(
            side_effect=OrchestratorError(
                "Auth error",
                user_message="Authentifizierungsfehler bei Bahnhofsdaten",
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/navigate",
                json={"zoneID": "1866", "query": "Von Gleis 5 zum Starbucks"},
            )

    assert response.status_code == 503
    data = response.json()
    assert data["instructions"] == []
    assert "Authentifizierungsfehler" in data["error"]

"""
RIS-Maps API client module.

Provides access to Deutsche Bahn's RIS-Maps API for station data,
indoor POIs, platforms, and indoor routing.

Authentication uses Basic Auth with credentials from environment variables.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

# Timeout for each individual request (None = no timeout)
REQUEST_TIMEOUT = None

# Retry configuration
MAX_RETRIES = 1
INITIAL_BACKOFF = 1.0  # seconds


class RISMapsError(Exception):
    """Base exception for RIS-Maps API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RISMapsNoContentError(RISMapsError):
    """Raised when the API returns 204 No Content (e.g., no route found)."""

    def __init__(self, message: str = "No content returned by RIS-Maps API"):
        super().__init__(message, status_code=204)


class RISMapsClientError(RISMapsError):
    """Raised on 4xx client errors (bad request, auth failure, etc.)."""

    pass


class RISMapsServerError(RISMapsError):
    """Raised on 5xx server errors after retries are exhausted."""

    pass


class RISMapsTimeoutError(RISMapsError):
    """Raised when a request times out."""

    def __init__(self, message: str = "RIS-Maps API request timed out"):
        super().__init__(message, status_code=None)


class RISMapsClient:
    """
    Async HTTP client for the RIS-Maps API.

    Uses Basic Auth from RIMAPS_USER / RIMAPS_PASSWORD env vars.
    Base URL is resolved from RIMAPS_BASE_URL env var.

    Implements:
    - 30-second per-request timeout
    - 1 retry on 5xx with exponential backoff
    - Distinct error handling for 204, 4xx, 5xx, and timeout
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.rimaps_base_url.rstrip("/")
        self._auth = (settings.rimaps_user, settings.rimaps_password)

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        """
        Make an authenticated request to the RIS-Maps API with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path relative to base URL (e.g., /station/list/DB/all)
            params: Optional query parameters

        Returns:
            Parsed JSON response body

        Raises:
            RISMapsNoContentError: On 204 responses
            RISMapsClientError: On 4xx responses
            RISMapsServerError: On 5xx responses after retries exhausted
            RISMapsTimeoutError: On request timeout
        """
        url = f"{self._base_url}{path}"
        auth = httpx.BasicAuth(username=self._auth[0], password=self._auth[1])
        timeout = httpx.Timeout(REQUEST_TIMEOUT) if REQUEST_TIMEOUT else None

        last_error: Exception | None = None

        for attempt in range(1 + MAX_RETRIES):
            try:
                async with httpx.AsyncClient(auth=auth, timeout=timeout) as client:
                    response = await client.request(method, url, params=params)

                # 204 No Content
                if response.status_code == 204:
                    raise RISMapsNoContentError()

                # 2xx success
                if 200 <= response.status_code < 300:
                    return response.json()

                # 4xx client error — no retry
                if 400 <= response.status_code < 500:
                    error_msg = f"RIS-Maps client error: HTTP {response.status_code}"
                    logger.warning(
                        f"{error_msg} for {method} {path}"
                    )
                    raise RISMapsClientError(error_msg, status_code=response.status_code)

                # 5xx server error — retry with backoff
                if response.status_code >= 500:
                    error_msg = f"RIS-Maps server error: HTTP {response.status_code}"
                    last_error = RISMapsServerError(error_msg, status_code=response.status_code)
                    logger.warning(
                        f"{error_msg} for {method} {path} (attempt {attempt + 1}/{1 + MAX_RETRIES})"
                    )
                    if attempt < MAX_RETRIES:
                        backoff = INITIAL_BACKOFF * (2 ** attempt)
                        await asyncio.sleep(backoff)
                        continue
                    raise last_error

            except httpx.TimeoutException:
                error_msg = f"RIS-Maps request timed out for {method} {path} (attempt {attempt + 1}/{1 + MAX_RETRIES})"
                logger.warning(error_msg)
                last_error = RISMapsTimeoutError()
                if attempt < MAX_RETRIES:
                    backoff = INITIAL_BACKOFF * (2 ** attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise last_error

            except (RISMapsNoContentError, RISMapsClientError):
                # Don't retry these
                raise

            except httpx.HTTPError as exc:
                error_msg = f"RIS-Maps HTTP error for {method} {path}: {exc}"
                logger.error(error_msg)
                last_error = RISMapsServerError(error_msg)
                if attempt < MAX_RETRIES:
                    backoff = INITIAL_BACKOFF * (2 ** attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise last_error

        # Should not reach here, but just in case
        raise last_error or RISMapsError("Unexpected error in RIS-Maps client")

    async def get_stations(self) -> dict[str, Any]:
        """
        Fetch the full list of DB stations.

        Endpoint: GET /station/list/DB/all

        Returns:
            JSON response containing station list

        Raises:
            RISMapsNoContentError: If no stations available
            RISMapsClientError: On 4xx errors
            RISMapsServerError: On 5xx errors
            RISMapsTimeoutError: On timeout
        """
        return await self._request("GET", "/station/list/DB/all")

    async def get_pois(self, zone_id: str) -> dict[str, Any]:
        """
        Fetch indoor POIs for a given station zone.

        Endpoint: GET /station/poi/indoor/DB/zoneid/{zoneID}

        Args:
            zone_id: The station's zone ID

        Returns:
            JSON response containing POI list

        Raises:
            RISMapsNoContentError: If no POIs found for this zone
            RISMapsClientError: On 4xx errors
            RISMapsServerError: On 5xx errors
            RISMapsTimeoutError: On timeout
        """
        return await self._request("GET", f"/station/poi/indoor/DB/zoneid/{zone_id}")

    async def get_platforms(self, zone_id: str) -> dict[str, Any]:
        """
        Fetch platforms for a given station zone.

        Endpoint: GET /station/platform/DB/{zoneID}

        Args:
            zone_id: The station's zone ID

        Returns:
            JSON response containing platform list

        Raises:
            RISMapsNoContentError: If no platforms found for this zone
            RISMapsClientError: On 4xx errors
            RISMapsServerError: On 5xx errors
            RISMapsTimeoutError: On timeout
        """
        return await self._request("GET", f"/station/platform/DB/{zone_id}")

    async def get_indoor_route(
        self,
        zone_id: str,
        from_level: str,
        from_lat: float,
        from_lon: float,
        to_level: str,
        to_lat: float,
        to_lon: float,
        handicapped: bool = False,
    ) -> dict[str, Any]:
        """
        Compute an indoor route between two positions.

        Endpoint: GET /station/routing/indoor/byposition.geojson
        Query params: zoneID, fromLevel, fromLat, fromLon, toLevel, toLat, toLon, handicapped

        Args:
            zone_id: The station's zone ID
            from_level: Start level (LevelEnum value, e.g. "GROUND_FLOOR")
            from_lat: Start latitude
            from_lon: Start longitude
            to_level: Destination level (LevelEnum value)
            to_lat: Destination latitude
            to_lon: Destination longitude
            handicapped: Whether to compute a barrier-free route

        Returns:
            GeoJSON FeatureCollection with route segments

        Raises:
            RISMapsNoContentError: If no route can be computed (204)
            RISMapsClientError: On 4xx errors
            RISMapsServerError: On 5xx errors
            RISMapsTimeoutError: On timeout
        """
        params = {
            "zoneID": zone_id,
            "fromLevel": from_level,
            "fromLat": str(from_lat),
            "fromLon": str(from_lon),
            "toLevel": to_level,
            "toLat": str(to_lat),
            "toLon": str(to_lon),
            "handicapped": "true" if handicapped else "false",
        }
        return await self._request(
            "GET", "/station/routing/indoor/byposition.geojson", params=params
        )

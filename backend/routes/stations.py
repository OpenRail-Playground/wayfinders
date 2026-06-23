"""
Station list endpoint.

Returns all stations with indoor routing data, sorted alphabetically by name.
"""

import logging

from fastapi import APIRouter, HTTPException

from clients.ris_maps_client import (
    RISMapsClient,
    RISMapsClientError,
    RISMapsServerError,
    RISMapsTimeoutError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/stations")
async def get_stations():
    """
    Fetch available stations with indoor routing support.

    Calls the RIS-Maps API for the full station list, filters to stations
    that have indoor routing (hasRouting: true), and returns them sorted
    alphabetically by name.

    Returns:
        dict with "stations" key containing list of {zoneID, name} objects

    Raises:
        HTTPException 503: If RIS-Maps is unavailable or returns auth error
    """
    client = RISMapsClient()

    try:
        data = await client.get_stations()
    except RISMapsClientError as exc:
        # 401/403 auth errors
        if exc.status_code in (401, 403):
            logger.error(f"RIS-Maps authentication error: {exc}")
            raise HTTPException(
                status_code=503,
                detail={"error": "Authentifizierungsfehler bei Bahnhofsdaten"},
            )
        # Other 4xx errors
        logger.error(f"RIS-Maps client error: {exc}")
        raise HTTPException(
            status_code=503,
            detail={"error": "Bahnhofsdaten sind vorübergehend nicht verfügbar"},
        )
    except (RISMapsServerError, RISMapsTimeoutError) as exc:
        logger.error(f"RIS-Maps unavailable: {exc}")
        raise HTTPException(
            status_code=503,
            detail={"error": "Bahnhofsdaten sind vorübergehend nicht verfügbar"},
        )

    # Filter to stations with indoor routing, sort alphabetically by name
    all_stations = data.get("stations", [])
    routable = [s for s in all_stations if s.get("hasRouting") is True]
    routable.sort(key=lambda s: s.get("name", ""))

    # Return only zoneID and name
    result = [{"zoneID": s["zoneID"], "name": s["name"]} for s in routable]

    return {"stations": result}

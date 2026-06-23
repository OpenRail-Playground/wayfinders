"""
POIResolver — LLM Step 2 of the navigation pipeline.

Fetches POIs and platforms for a station zone from the RIS-Maps API,
builds a combined location list, and uses the LLM to match user-provided
start and destination descriptions to the best-fit location coordinates.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from clients.genai_client import GenAIClient, GenAIError
from clients.ris_maps_client import (
    RISMapsClient,
    RISMapsError,
    RISMapsNoContentError,
)
from pipeline.models import Position

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a location matching assistant for a train station indoor navigation system.

Your task: Given a list of available locations (POIs and platforms) in a train station, \
match the user's start and destination descriptions to the best-fit location from the list.

Rules:
- Select the SINGLE best match for each description from the provided location list.
- Match based on name similarity, category, and contextual clues.
- For platform/track references (e.g. "Gleis 5", "Bahnsteig 3/4"), match to the platform entry with the corresponding name.
- For named facilities (e.g. "Starbucks", "DB Lounge"), match to the POI with that name.
- For generic references (e.g. "Treppe", "Ausgang"), pick the most likely match considering the context.
- If you cannot find a reasonable match for start, set start to null.
- If you cannot find a reasonable match for destination, set destination to null.
- Always select the highest-confidence match. Do not return multiple options.
- Respond ONLY with a JSON object, no extra text.

Output format (strict JSON):
{"start": {"lat": <number>, "lon": <number>, "level": "<string>"}, "destination": {"lat": <number>, "lon": <number>, "level": "<string>"}}

If a match cannot be found, use null for that field:
{"start": null, "destination": {"lat": <number>, "lon": <number>, "level": "<string>"}}
"""


class POIResolverError(Exception):
    """Raised when POI resolution fails."""

    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(message)
        self.user_message = user_message or message


class POIResolver:
    """
    Resolves start and destination descriptions to geographic positions.

    Fetches available POIs and platforms from RIS-Maps, then uses the LLM
    to match free-text descriptions to the best-fit location coordinates.
    """

    def __init__(self, ris_maps_client: RISMapsClient, genai_client: GenAIClient):
        self._ris_maps = ris_maps_client
        self._genai = genai_client

    async def resolve(
        self,
        start_description: str,
        destination_description: str,
        zone_id: str,
    ) -> tuple[Position, Position]:
        """
        Resolve start and destination descriptions to geographic positions.

        Args:
            start_description: Free-text description of the start location.
            destination_description: Free-text description of the destination.
            zone_id: The station's zone ID for fetching POIs/platforms.

        Returns:
            A tuple of (start_position, destination_position).

        Raises:
            POIResolverError: If positions cannot be resolved or services fail.
        """
        # Fetch POIs and platforms from RIS-Maps
        location_list = await self._fetch_locations(zone_id)

        if not location_list:
            raise POIResolverError(
                f"No POIs or platforms found for zone {zone_id}",
                user_message="Bahnhofsdaten konnten nicht abgerufen werden",
            )

        # Build the user message with location list and descriptions
        user_message = self._build_user_message(
            start_description, destination_description, location_list
        )

        # Call LLM to match descriptions to locations
        messages = [{"role": "user", "content": [{"text": user_message}]}]

        try:
            response_text = await self._genai.complete(
                messages=messages,
                system_message=SYSTEM_PROMPT,
            )
        except GenAIError as exc:
            logger.error("LLM call failed during POI resolution: %s", exc)
            raise POIResolverError(
                f"LLM call failed: {exc}",
                user_message="KI-Service ist vorübergehend nicht verfügbar",
            ) from exc

        # Parse the LLM response
        return self._parse_response(response_text)

    async def resolve_destination_only(
        self,
        destination_description: str,
        zone_id: str,
    ) -> Position:
        """
        Resolve only a destination description to a geographic position.

        Used when the start position is already known (e.g. from image).

        Args:
            destination_description: Free-text description of the destination.
            zone_id: The station's zone ID for fetching POIs/platforms.

        Returns:
            The destination Position.

        Raises:
            POIResolverError: If the destination cannot be resolved.
        """
        location_list = await self._fetch_locations(zone_id)

        if not location_list:
            raise POIResolverError(
                f"No POIs or platforms found for zone {zone_id}",
                user_message="Bahnhofsdaten konnten nicht abgerufen werden",
            )

        # Build a destination-only user message
        location_lines = []
        for loc in location_list:
            location_lines.append(
                f"- {loc['name']} (category: {loc['category']}, "
                f"level: {loc['level']}, lat: {loc['lat']}, lon: {loc['lon']})"
            )
        locations_text = "\n".join(location_lines)

        user_message = (
            f"Available locations in this station:\n"
            f"{locations_text}\n\n"
            f"Match the following destination description to the best-fit location from the list above:\n"
            f"- Destination: \"{destination_description}\"\n\n"
            f"Return the coordinates and level as JSON.\n"
            f"Output format: {{\"destination\": {{\"lat\": <number>, \"lon\": <number>, \"level\": \"<string>\"}}}}"
        )

        messages = [{"role": "user", "content": [{"text": user_message}]}]

        try:
            response_text = await self._genai.complete(
                messages=messages,
                system_message=SYSTEM_PROMPT,
            )
        except GenAIError as exc:
            logger.error("LLM call failed during destination-only POI resolution: %s", exc)
            raise POIResolverError(
                f"LLM call failed: {exc}",
                user_message="KI-Service ist vorübergehend nicht verfügbar",
            ) from exc

        # Parse response
        try:
            parsed = json.loads(response_text.strip())
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse LLM response as JSON: %s | Response: %s",
                exc,
                response_text[:200],
            )
            raise POIResolverError(
                f"LLM returned invalid JSON: {response_text[:100]}",
                user_message="Zielposition konnte nicht im Bahnhof gefunden werden",
            ) from exc

        dest_data = parsed.get("destination")
        if dest_data is None:
            raise POIResolverError(
                "Destination could not be resolved",
                user_message="Zielposition konnte nicht im Bahnhof gefunden werden",
            )

        try:
            return Position(
                lat=float(dest_data["lat"]),
                lon=float(dest_data["lon"]),
                level=str(dest_data["level"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise POIResolverError(
                f"Invalid destination position data: {dest_data}",
                user_message="Zielposition konnte nicht im Bahnhof gefunden werden",
            ) from exc

    async def _fetch_locations(self, zone_id: str) -> list[dict]:
        """
        Fetch POIs and platforms, returning a combined location list.

        Each entry has: name, category, lat, lon, level.
        """
        locations: list[dict] = []

        # Fetch POIs
        try:
            pois_data = await self._ris_maps.get_pois(zone_id)
            pois = pois_data.get("pois", [])
            for poi in pois:
                # Extract coordinates from geometry or displayPosition
                lat, lon = self._extract_poi_coordinates(poi)
                if lat is not None and lon is not None:
                    locations.append({
                        "name": poi.get("name", "Unknown"),
                        "category": poi.get("category", "Unknown"),
                        "lat": lat,
                        "lon": lon,
                        "level": poi.get("level", "GROUND_FLOOR"),
                    })
        except RISMapsNoContentError:
            logger.warning("No POIs found for zone %s", zone_id)
        except RISMapsError as exc:
            logger.error("Failed to fetch POIs for zone %s: %s", zone_id, exc)

        # Fetch platforms
        try:
            platforms_data = await self._ris_maps.get_platforms(zone_id)
            platforms = platforms_data.get("platforms", [])
            for platform in platforms:
                center = platform.get("center", {})
                lat = center.get("lat")
                lon = center.get("lon")
                if lat is not None and lon is not None:
                    locations.append({
                        "name": f"Gleis {platform.get('name', 'Unknown')}",
                        "category": platform.get("category", "PLATFORM"),
                        "lat": lat,
                        "lon": lon,
                        "level": platform.get("level", "GROUND_FLOOR"),
                    })
        except RISMapsNoContentError:
            logger.warning("No platforms found for zone %s", zone_id)
        except RISMapsError as exc:
            logger.error("Failed to fetch platforms for zone %s: %s", zone_id, exc)

        return locations

    def _extract_poi_coordinates(self, poi: dict) -> tuple[Optional[float], Optional[float]]:
        """Extract lat/lon from a POI entry, trying displayPosition first, then geometry."""
        # Try displayPosition
        display_pos = poi.get("displayPosition")
        if display_pos:
            lat = display_pos.get("lat")
            lon = display_pos.get("lon")
            if lat is not None and lon is not None:
                return lat, lon

        # Fall back to geometry coordinates (Point type: [lon, lat])
        geometry = poi.get("geometry", {})
        if geometry.get("type") == "Point":
            coords = geometry.get("coordinates", [])
            if len(coords) >= 2:
                return coords[1], coords[0]  # GeoJSON is [lon, lat]

        return None, None

    def _build_user_message(
        self,
        start_description: str,
        destination_description: str,
        locations: list[dict],
    ) -> str:
        """Build the user prompt with location list and descriptions to match."""
        # Build a compact location list for the LLM
        location_lines = []
        for loc in locations:
            location_lines.append(
                f"- {loc['name']} (category: {loc['category']}, "
                f"level: {loc['level']}, lat: {loc['lat']}, lon: {loc['lon']})"
            )

        locations_text = "\n".join(location_lines)

        return (
            f"Available locations in this station:\n"
            f"{locations_text}\n\n"
            f"Match the following descriptions to the best-fit location from the list above:\n"
            f"- Start: \"{start_description}\"\n"
            f"- Destination: \"{destination_description}\"\n\n"
            f"Return the coordinates and level for each match as JSON."
        )

    def _parse_response(self, response_text: str) -> tuple[Position, Position]:
        """
        Parse the LLM JSON response into Position objects.

        Raises POIResolverError if parsing fails or positions cannot be resolved.
        """
        try:
            parsed = json.loads(response_text.strip())
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse LLM response as JSON: %s | Response: %s",
                exc,
                response_text[:200],
            )
            raise POIResolverError(
                f"LLM returned invalid JSON: {response_text[:100]}",
                user_message="Position konnte nicht im Bahnhof gefunden werden",
            ) from exc

        start_data = parsed.get("start")
        dest_data = parsed.get("destination")

        # Determine which could not be resolved
        start_failed = start_data is None
        dest_failed = dest_data is None

        if start_failed and dest_failed:
            raise POIResolverError(
                "Both start and destination could not be resolved",
                user_message="Start- und Zielposition konnten nicht im Bahnhof gefunden werden",
            )

        if start_failed:
            raise POIResolverError(
                "Start position could not be resolved",
                user_message="Startposition konnte nicht im Bahnhof gefunden werden",
            )

        if dest_failed:
            raise POIResolverError(
                "Destination could not be resolved",
                user_message="Zielposition konnte nicht im Bahnhof gefunden werden",
            )

        # Validate and build Position objects
        try:
            start_position = Position(
                lat=float(start_data["lat"]),
                lon=float(start_data["lon"]),
                level=str(start_data["level"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise POIResolverError(
                f"Invalid start position data: {start_data}",
                user_message="Startposition konnte nicht im Bahnhof gefunden werden",
            ) from exc

        try:
            dest_position = Position(
                lat=float(dest_data["lat"]),
                lon=float(dest_data["lon"]),
                level=str(dest_data["level"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise POIResolverError(
                f"Invalid destination position data: {dest_data}",
                user_message="Zielposition konnte nicht im Bahnhof gefunden werden",
            ) from exc

        return start_position, dest_position

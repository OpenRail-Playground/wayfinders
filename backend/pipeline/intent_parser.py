"""
IntentParser — LLM Step 1 of the navigation pipeline.

Extracts a start location description and a destination description
from a free-text user query using Claude via DB GenAI Hub.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from clients.genai_client import GenAIClient, GenAIError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a location extraction assistant for a train station indoor navigation system.

Your task: Given a user's natural language query (German or English), extract two pieces of information:
1. start_description — where the user currently is
2. destination_description — where the user wants to go

Rules:
- Extract the descriptions as short, clear location references (e.g. "Gleis 5", "Starbucks", "DB Lounge", "Haupteingang").
- If the user does not mention a start location, set start_description to null.
- If the user does not mention a destination, set destination_description to null.
- Do NOT invent locations. Only extract what the user explicitly states.
- Respond ONLY with a JSON object, no extra text.

Output format (strict JSON):
{"start_description": "<string or null>", "destination_description": "<string or null>"}
"""


@dataclass
class ParsedIntent:
    """Result of intent parsing — extracted location descriptions."""

    start_description: str
    destination_description: str


class IntentParserError(Exception):
    """Raised when intent parsing fails."""

    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(message)
        self.user_message = user_message or message


class IntentParser:
    """
    Extracts start and destination descriptions from a user query via LLM.

    Uses a structured JSON output format prompted through the system message.
    """

    def __init__(self, genai_client: GenAIClient):
        self._client = genai_client

    async def parse(self, query: str) -> ParsedIntent:
        """
        Parse a user query to extract start and destination descriptions.

        Args:
            query: The raw user query in natural language (German or English).

        Returns:
            ParsedIntent with start_description and destination_description.

        Raises:
            IntentParserError: If the start position cannot be determined,
                or if the LLM call fails.
        """
        messages = [
            {"role": "user", "content": [{"text": query}]}
        ]

        try:
            response_text = await self._client.complete(
                messages=messages,
                system_message=SYSTEM_PROMPT,
            )
        except GenAIError as exc:
            logger.error("LLM call failed during intent parsing: %s", exc)
            raise IntentParserError(
                f"LLM call failed: {exc}",
                user_message="KI-Service ist vorübergehend nicht verfügbar",
            ) from exc

        # Parse the JSON response from the LLM
        try:
            parsed = json.loads(response_text.strip())
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse LLM response as JSON: %s | Response: %s",
                exc,
                response_text[:200],
            )
            raise IntentParserError(
                f"LLM returned invalid JSON: {response_text[:100]}",
                user_message="Start- oder Zielposition konnte nicht erkannt werden",
            ) from exc

        start_desc = parsed.get("start_description")
        dest_desc = parsed.get("destination_description")

        # Validate: start is required
        if not start_desc:
            raise IntentParserError(
                "Start position could not be determined from query",
                user_message="Start- oder Zielposition konnte nicht erkannt werden",
            )

        # Validate: destination is required
        if not dest_desc:
            raise IntentParserError(
                "Destination could not be determined from query",
                user_message="Start- oder Zielposition konnte nicht erkannt werden",
            )

        return ParsedIntent(
            start_description=start_desc,
            destination_description=dest_desc,
        )

    async def parse_destination_only(self, query: str) -> ParsedIntent:
        """
        Parse a user query to extract the destination description only.

        Used when the start position will be determined from an image.
        The start_description in the result will be empty.

        Args:
            query: The raw user query in natural language (German or English).

        Returns:
            ParsedIntent with an empty start_description and the destination.

        Raises:
            IntentParserError: If the destination cannot be determined.
        """
        messages = [
            {"role": "user", "content": [{"text": query}]}
        ]

        try:
            response_text = await self._client.complete(
                messages=messages,
                system_message=SYSTEM_PROMPT,
            )
        except GenAIError as exc:
            logger.error("LLM call failed during intent parsing: %s", exc)
            raise IntentParserError(
                f"LLM call failed: {exc}",
                user_message="KI-Service ist vorübergehend nicht verfügbar",
            ) from exc

        try:
            parsed = json.loads(response_text.strip())
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse LLM response as JSON: %s | Response: %s",
                exc,
                response_text[:200],
            )
            raise IntentParserError(
                f"LLM returned invalid JSON: {response_text[:100]}",
                user_message="Zielposition konnte nicht erkannt werden",
            ) from exc

        dest_desc = parsed.get("destination_description")

        if not dest_desc:
            raise IntentParserError(
                "Destination could not be determined from query",
                user_message="Zielposition konnte nicht erkannt werden",
            )

        return ParsedIntent(
            start_description="",
            destination_description=dest_desc,
        )

"""
DescriptionGenerator — LLM Step 3 of the navigation pipeline.

Takes enriched route segments (with landmark POI references) and calls
Claude via DB GenAI Hub to generate one human-readable navigation
instruction per segment. Level-change segments include facility type
and target level name. Supports German output.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from clients.genai_client import GenAIClient, GenAIError
from pipeline.models import EnrichedSegment, NavigationLeg

logger = logging.getLogger(__name__)

# Human-friendly level names for German output
LEVEL_DISPLAY_NAMES: dict[str, str] = {
    "BASEMENT_FLOOR_4": "Untergeschoss 4",
    "BASEMENT_FLOOR_3": "Untergeschoss 3",
    "BASEMENT_FLOOR_2": "Untergeschoss 2",
    "BASEMENT_FLOOR_1": "Untergeschoss 1",
    "GROUND_FLOOR": "Erdgeschoss",
    "UPPER_FLOOR_1": "Obergeschoss 1",
    "UPPER_FLOOR_2": "Obergeschoss 2",
    "UPPER_FLOOR_3": "Obergeschoss 3",
}

# Mapping of segment types to German facility names
FACILITY_TYPE_NAMES: dict[str, str] = {
    "STAIRS": "Treppe",
    "ESCALATOR": "Rolltreppe",
    "ELEVATOR": "Aufzug",
    "RAMP": "Rampe",
}

SYSTEM_PROMPT = """\
You are a navigation instruction generator for a German train station indoor navigation system.

Your task: Given a list of navigation legs, generate exactly ONE concise navigation instruction per leg.

Rules:
- Generate exactly one instruction per leg, in the same order as the input.
- Each WALK leg has a destination POI or landmark — tell the user to walk towards it.
- If a leg has a turn_direction (links/rechts), start the instruction with the turn (e.g., "Biegen Sie rechts ab und gehen Sie Richtung Pret A Manger").
- If there is no turn_direction, it's the first leg or a straight continuation — just say "Gehen Sie Richtung [destination]".
- For level-change legs (STAIRS, ESCALATOR, ELEVATOR, RAMP), mention the facility type and target level.
- Include approximate distances when available.
- Write all instructions in German.
- Keep instructions concise and easy to follow.

Output format (strict JSON array of strings):
["instruction 1", "instruction 2", ...]

Do NOT include any extra text outside the JSON array.
"""


class DescriptionGeneratorError(Exception):
    """Raised when description generation fails."""

    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(message)
        self.user_message = user_message or message


class DescriptionGenerator:
    """
    Generates human-readable navigation instructions from enriched route segments.

    Uses Claude via GenAI Hub to produce one instruction per segment,
    referencing POI landmarks by name when available.
    """

    def __init__(self, genai_client: GenAIClient):
        self._client = genai_client

    async def generate(self, legs: list[NavigationLeg]) -> list[str]:
        """
        Generate navigation instructions for the given navigation legs.

        Args:
            legs: Ordered list of NavigationLeg objects.

        Returns:
            List of instruction strings, one per leg.

        Raises:
            DescriptionGeneratorError: If the LLM call fails or the response
                cannot be parsed.
        """
        if not legs:
            return []

        # Build the user prompt describing each leg
        user_prompt = self._build_user_prompt(legs)

        messages = [{"role": "user", "content": [{"text": user_prompt}]}]

        try:
            response_text = await self._client.complete(
                messages=messages,
                system_message=SYSTEM_PROMPT,
            )
        except GenAIError as exc:
            logger.error("LLM call failed during description generation: %s", exc)
            raise DescriptionGeneratorError(
                f"LLM call failed: {exc}",
                user_message="KI-Service ist vorübergehend nicht verfügbar",
            ) from exc

        # Parse the JSON array response
        instructions = self._parse_response(response_text, len(legs))
        return instructions

    def _build_user_prompt(self, legs: list[NavigationLeg]) -> str:
        """
        Build the user message describing all navigation legs for the LLM.
        """
        lines: list[str] = []
        lines.append(
            f"Generate navigation instructions for the following {len(legs)} legs:\n"
        )

        for i, leg in enumerate(legs, start=1):
            desc = f"Leg {i}: Type={leg.leg_type}, Level={_display_level(leg.level)}, Length={leg.length_m:.0f}m"

            # Turn direction
            if leg.turn_direction:
                desc += f", TurnDirection={leg.turn_direction} ({leg.angle_change:.0f}°)"

            # Level-change info
            if leg.target_level:
                facility = FACILITY_TYPE_NAMES.get(leg.leg_type, leg.leg_type)
                target = _display_level(leg.target_level)
                desc += f", Facility={facility}, TargetLevel={target}"

            # Destination POI
            if leg.destination_poi:
                desc += f", Destination=\"{leg.destination_poi.name}\" ({leg.destination_poi.category})"
            elif leg.destination_fallback:
                desc += f", Destination=\"{leg.destination_fallback}\""

            lines.append(desc)

        return "\n".join(lines)

    def _parse_response(self, response_text: str, expected_count: int) -> list[str]:
        """
        Parse the LLM response as a JSON array of instruction strings.

        Args:
            response_text: Raw text response from the LLM.
            expected_count: Expected number of instructions (one per segment).

        Returns:
            List of instruction strings.

        Raises:
            DescriptionGeneratorError: If the response is not valid JSON or
                does not contain the expected number of instructions.
        """
        # Strip whitespace and try to find JSON array in response
        cleaned = response_text.strip()

        # Handle case where LLM wraps response in markdown code block
        if cleaned.startswith("```"):
            # Remove markdown code fences
            lines = cleaned.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            instructions = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse LLM description response as JSON: %s | Response: %s",
                exc,
                response_text[:200],
            )
            raise DescriptionGeneratorError(
                f"LLM returned invalid JSON: {response_text[:100]}",
                user_message="Navigationsbeschreibung konnte nicht erstellt werden",
            ) from exc

        if not isinstance(instructions, list):
            raise DescriptionGeneratorError(
                f"LLM returned non-array response: {type(instructions).__name__}",
                user_message="Navigationsbeschreibung konnte nicht erstellt werden",
            )

        # Validate all items are strings
        instructions = [str(item) for item in instructions]

        if len(instructions) != expected_count:
            logger.warning(
                "LLM returned %d instructions, expected %d. Adjusting.",
                len(instructions),
                expected_count,
            )
            # If too few, pad with generic instructions
            while len(instructions) < expected_count:
                instructions.append("Weiter geradeaus gehen.")
            # If too many, truncate
            instructions = instructions[:expected_count]

        return instructions


def _display_level(level: str) -> str:
    """Convert a LevelEnum value to a human-friendly German name."""
    return LEVEL_DISPLAY_NAMES.get(level, level)

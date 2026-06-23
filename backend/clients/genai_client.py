"""
GenAI Hub client for LLM inference via DB GenAI Hub gateway.

Calls Anthropic Claude Opus 4.7 through the DB GenAI Hub gateway using the
AWS Converse API request format. Handles authentication, timeouts,
and response parsing.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Default endpoint for GenAI Hub gateway
DEFAULT_GENAI_ENDPOINT = (
    "https://genaihub-gateway.genai-prod.comp.db.de"
    "/claude/model/eu.anthropic.claude-opus-4-7/converse"
)

# Per-request timeout in seconds (None = no timeout)
REQUEST_TIMEOUT = None


class GenAIError(Exception):
    """Base exception for GenAI client errors."""

    pass


class GenAITimeoutError(GenAIError):
    """Raised when the GenAI Hub request times out."""

    pass


class GenAIServiceError(GenAIError):
    """Raised when the GenAI Hub returns an HTTP error."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GenAIClient:
    """
    Client for the DB GenAI Hub gateway.

    Sends requests to Anthropic Claude Opus 4.7 via the AWS Converse API format.
    Authenticates using an API key passed as the Ocp-Apim-Subscription-Key header.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
    ):
        """
        Initialize the GenAI Hub client.

        Args:
            api_key: GenAI Hub API key. Defaults to GENAI_API_KEY env var.
            endpoint: GenAI Hub endpoint URL. Defaults to GENAI_ENDPOINT env var
                      or the hardcoded default endpoint.
        """
        self._api_key = api_key or os.environ.get("GENAI_API_KEY", "")
        self._endpoint = (
            endpoint
            or os.environ.get("GENAI_ENDPOINT", "")
            or DEFAULT_GENAI_ENDPOINT
        )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(REQUEST_TIMEOUT) if REQUEST_TIMEOUT else None,
        )

    async def complete(
        self,
        messages: list,
        system_message: Optional[str] = None,
    ) -> str:
        """
        Send a completion request to the GenAI Hub.

        Uses the AWS Converse API request format.

        Args:
            messages: List of message dicts in AWS Converse format, e.g.
                [{"role": "user", "content": [{"text": "Hello"}]}]
            system_message: Optional system prompt text.

        Returns:
            The text content from the model's response.

        Raises:
            GenAITimeoutError: If the request exceeds the 30-second timeout.
            GenAIServiceError: If the GenAI Hub returns an HTTP error.
            GenAIError: If the response cannot be parsed.
        """
        payload: dict = {"messages": messages}

        if system_message:
            payload["system"] = [{"text": system_message}]

        headers = {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": self._api_key,
        }

        try:
            response = await self._client.post(
                self._endpoint,
                json=payload,
                headers=headers,
            )
        except httpx.TimeoutException:
            logger.error("GenAI Hub request timed out after %ss", REQUEST_TIMEOUT)
            raise GenAITimeoutError(
                f"GenAI Hub request timed out after {REQUEST_TIMEOUT}s"
            )
        except httpx.HTTPError as exc:
            logger.error("GenAI Hub request failed: %s", exc)
            raise GenAIServiceError(f"GenAI Hub request failed: {exc}")

        if response.status_code >= 500:
            logger.error(
                "GenAI Hub returned server error: %s", response.status_code
            )
            raise GenAIServiceError(
                "GenAI Hub service is unavailable",
                status_code=response.status_code,
            )

        if response.status_code >= 400:
            logger.error(
                "GenAI Hub returned client error: %s %s",
                response.status_code,
                response.text[:200],
            )
            raise GenAIServiceError(
                f"GenAI Hub returned error status {response.status_code}",
                status_code=response.status_code,
            )

        # Parse AWS Converse response format
        try:
            data = response.json()
            text = data["output"]["message"]["content"][0]["text"]
            return text
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("Failed to parse GenAI Hub response: %s", exc)
            raise GenAIError(
                f"Failed to parse GenAI Hub response: {exc}"
            )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

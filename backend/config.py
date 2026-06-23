"""
Configuration module for the indoor navigation backend.

Loads required environment variables and validates them at startup.
The application fails to start with a descriptive error if any required variable is missing.
"""

import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env from project root (one level up from backend/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# Required environment variables
REQUIRED_ENV_VARS = [
    "RIMAPS_BASE_URL",
    "RIMAPS_USER",
    "RIMAPS_PASSWORD",
    "GENAI_API_KEY",
    "GENAI_ENDPOINT",
]


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        self.rimaps_base_url: str = os.environ.get("RIMAPS_BASE_URL", "")
        self.rimaps_user: str = os.environ.get("RIMAPS_USER", "")
        self.rimaps_password: str = os.environ.get("RIMAPS_PASSWORD", "")
        self.genai_api_key: str = os.environ.get("GENAI_API_KEY", "")
        self.genai_endpoint: str = os.environ.get("GENAI_ENDPOINT", "")


def validate_env_vars() -> None:
    """
    Validate that all required environment variables are set.

    Raises SystemExit if any required variable is missing.
    Logs a descriptive error indicating which variables are missing.
    """
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]

    if missing:
        for var in missing:
            logger.error(f"Required environment variable '{var}' is not set.")
        logger.error(
            f"Application cannot start. Missing environment variables: {', '.join(missing)}"
        )
        sys.exit(1)


def get_settings() -> Settings:
    """Return application settings. Call only after validate_env_vars()."""
    return Settings()

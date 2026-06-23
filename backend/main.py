"""
FastAPI application for the LLM Indoor Navigation backend.

Orchestrates LLM calls (via DB GenAI Hub) and RIS-Maps API calls
to provide indoor navigation directions for Deutsche Bahn train stations.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from config import validate_env_vars, get_settings
from routes.stations import router as stations_router
from routes.navigate import router as navigate_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Suppress noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: validate configuration at startup."""
    logger.info("Starting indoor navigation backend...")
    validate_env_vars()
    settings = get_settings()
    app.state.settings = settings
    logger.info("Configuration validated. Application ready.")
    yield
    logger.info("Shutting down indoor navigation backend.")


app = FastAPI(
    title="LLM Indoor Navigation API",
    description="Indoor navigation assistant for Deutsche Bahn train stations",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Register routers
app.include_router(stations_router)
app.include_router(navigate_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """
    Custom validation error handler.

    Returns a user-facing error message in the standard NavigateResponse format
    for the /api/navigate endpoint. Falls back to generic 422 for other endpoints.
    """
    if request.url.path == "/api/navigate":
        # Extract a user-friendly message from the validation errors
        errors = exc.errors()
        if errors:
            first = errors[0]
            # Use the custom message from our field_validator if available
            msg = first.get("msg", "")
            if "Value error," in msg:
                msg = msg.replace("Value error, ", "")
            elif first.get("loc") and "zoneID" in str(first.get("loc")):
                msg = "Bitte wählen Sie einen Bahnhof"
            elif first.get("loc") and "query" in str(first.get("loc")):
                msg = "Bitte geben Sie eine Beschreibung ein"
            else:
                msg = "Ungültige Anfrage"
        else:
            msg = "Ungültige Anfrage"

        return JSONResponse(
            status_code=422,
            content={"instructions": [], "error": msg},
        )

    # Default validation error for non-navigate endpoints
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

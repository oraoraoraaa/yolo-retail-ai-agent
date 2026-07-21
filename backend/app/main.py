"""FastAPI application entrypoint.

Run from the ``backend`` package directory:

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.db.session import init_db
from app.routers import (
    audit_router,
    auth_router,
    chat_router,
    database_router,
    media_router,
    planogram_router,
    tickets_router,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create tables / seed defaults on startup."""
    init_db()
    yield


app = FastAPI(
    title="YOLO Retail AI Agent — Backend",
    description=(
        "Backend API for the shelf-audit workspace: local YOLO vision (via "
        "model-local), an LLM-backed retail agent, planogram matching, "
        "persistent SQLite/Postgres storage, and JWT staff auth."
    ),
    version=__version__,
    lifespan=lifespan,
)

_settings = get_settings()
# allow_credentials=True forbids allow_origins=["*"], so we keep an explicit
# origin list and OR a private-network regex for LAN / phone testing.
# Without the regex, Starlette answers OPTIONS with 400 "Disallowed CORS origin"
# and the browser never reaches POST /api/v1/auth/login.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_origin_regex=_settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(audit_router)
app.include_router(chat_router)
app.include_router(database_router)
app.include_router(planogram_router)
app.include_router(media_router)
app.include_router(tickets_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    """Service banner."""
    return {"service": "yolo-retail-ai-agent", "version": __version__}


@app.get("/health", tags=["meta"])
async def health() -> dict[str, object]:
    """Health probe reporting optional-feature availability."""
    settings = get_settings()
    weights = settings.local_vision_model_path
    return {
        "status": "ok",
        "llmEnabled": settings.llm_enabled,
        "authEnabled": settings.auth_enabled,
        "databaseUrlScheme": settings.database_url.split(":", 1)[0],
        "localVisionBaseUrl": settings.local_vision_base_url,
        "weightsPath": str(weights),
        "weightsPresent": weights.exists(),
        "visionBackend": "model-local",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

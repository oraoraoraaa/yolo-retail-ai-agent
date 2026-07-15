"""FastAPI application entrypoint.

Run from the ``backend`` directory:

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.routers import audit_router, chat_router, database_router

settings = get_settings()

app = FastAPI(
    title="YOLO Retail AI Agent — Backend",
    description=(
        "Backend API for the shelf-audit workspace: YOLOv8 gap detection, "
        "an LLM-backed retail agent, and a lightweight record store."
    ),
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audit_router)
app.include_router(chat_router)
app.include_router(database_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    """Service banner."""
    return {"service": "yolo-retail-ai-agent", "version": __version__}


@app.get("/health", tags=["meta"])
async def health() -> dict[str, object]:
    """Health probe reporting optional-feature availability."""
    return {
        "status": "ok",
        "llmEnabled": settings.llm_enabled,
        "weightsPath": str(settings.yolo_weights_path),
        "weightsPresent": settings.yolo_weights_path.exists(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

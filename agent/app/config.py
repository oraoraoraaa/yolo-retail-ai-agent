"""Environment-driven application settings.

Uses a small, dependency-free loader so the backend starts even when nothing
is configured. A local ``.env`` file (if present) is parsed manually.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# backend/app/config.py -> backend/app -> backend -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Populate ``os.environ`` from a simple ``.env`` file (no overrides)."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BACKEND_DIR / ".env")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve(path_value: str) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve()


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration resolved from the environment."""

    cors_origins: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv(
                "APP_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
        )
    )

    # YOLO gap-detection
    yolo_weights_path: Path = field(
        default_factory=lambda: _resolve(
            os.getenv(
                "YOLO_WEIGHTS_PATH",
                "artifacts/gap-detection/train/weights/best.pt",
            )
        )
    )
    yolo_conf: float = field(default_factory=lambda: float(os.getenv("YOLO_CONF", "0.25")))
    yolo_iou: float = field(default_factory=lambda: float(os.getenv("YOLO_IOU", "0.7")))
    yolo_imgsz: int = field(default_factory=lambda: int(os.getenv("YOLO_IMGSZ", "640")))

    # LLM agent (OpenAI-compatible)
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    )
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()

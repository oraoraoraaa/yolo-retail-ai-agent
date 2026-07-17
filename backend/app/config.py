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
DEFAULT_LOCAL_WEIGHTS = (
    REPO_ROOT / "train" / "export" / "gap-product-chinese-yolo11n.onnx"
)
DEFAULT_DATA_DIR = BACKEND_DIR / "data"
DEFAULT_SQLITE_URL = f"sqlite:///{(DEFAULT_DATA_DIR / 'retail.db').as_posix()}"


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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_database_url(raw: str) -> str:
    """Accept common Postgres URL schemes and default to local SQLite."""
    value = (raw or "").strip()
    if not value:
        DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DEFAULT_SQLITE_URL
    # SQLAlchemy 2 prefers postgresql+psycopg:// for psycopg3
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value[len("postgres://") :]
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://") :]
    if value.startswith("sqlite:///"):
        # Ensure parent directory exists for file-backed sqlite
        db_path = Path(value.replace("sqlite:///", "", 1))
        if not db_path.is_absolute():
            db_path = (REPO_ROOT / db_path).resolve()
            value = f"sqlite:///{db_path.as_posix()}"
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return value


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

    # Local vision service (model-local/stream_server.py) — sole inference path
    local_vision_base_url: str = field(
        default_factory=lambda: os.getenv(
            "LOCAL_VISION_BASE_URL", "http://127.0.0.1:8001"
        ).rstrip("/")
    )
    local_vision_model: str = field(
        default_factory=lambda: os.getenv(
            "LOCAL_VISION_MODEL",
            str(DEFAULT_LOCAL_WEIGHTS),
        )
    )
    local_vision_timeout: float = field(
        default_factory=lambda: float(os.getenv("LOCAL_VISION_TIMEOUT", "60"))
    )

    # LLM agent (OpenAI-compatible)
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    )
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    # Upload / payload size limits (protect event loop + LLM token budgets)
    max_upload_bytes: int = field(
        default_factory=lambda: int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    )
    max_chat_images: int = field(
        default_factory=lambda: int(os.getenv("MAX_CHAT_IMAGES", "4"))
    )
    max_base64_chars: int = field(
        default_factory=lambda: int(os.getenv("MAX_BASE64_CHARS", str(14 * 1024 * 1024)))
    )

    # Persistence (SQLite by default; set DATABASE_URL for Postgres)
    database_url: str = field(
        default_factory=lambda: _normalize_database_url(os.getenv("DATABASE_URL", ""))
    )
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("DATA_DIR", str(DEFAULT_DATA_DIR))
        ).expanduser()
    )
    media_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("MEDIA_DIR", str(DEFAULT_DATA_DIR / "media"))
        ).expanduser()
    )

    # Auth (JWT). Disabled by default for local demos; enable for store deploy.
    auth_enabled: bool = field(default_factory=lambda: _env_bool("AUTH_ENABLED", False))
    auth_secret: str = field(
        default_factory=lambda: os.getenv(
            "AUTH_SECRET",
            "dev-only-change-me-in-production",
        )
    )
    auth_token_ttl_hours: int = field(
        default_factory=lambda: int(os.getenv("AUTH_TOKEN_TTL_HOURS", "12"))
    )
    auth_admin_username: str = field(
        default_factory=lambda: os.getenv("AUTH_ADMIN_USERNAME", "admin")
    )
    auth_admin_password: str = field(
        default_factory=lambda: os.getenv("AUTH_ADMIN_PASSWORD", "admin")
    )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def local_vision_model_path(self) -> Path:
        return _resolve(self.local_vision_model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    settings = Settings()
    # Ensure default data/media dirs exist for SQLite + image refs.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    return settings


def reset_settings() -> None:
    """Clear the settings cache (used by tests)."""
    get_settings.cache_clear()

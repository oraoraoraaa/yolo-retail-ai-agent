"""Database record schemas (mirrors ``frontend/src/types/database.ts``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.common import CamelModel

DatabaseRecordType = Literal["audit", "sku", "inventory", "chat"]


class DatabaseRecord(CamelModel):
    """A saved retail record surfaced on the database page."""

    id: str
    type: DatabaseRecordType
    title: str
    summary: str
    updated_at: str
    image_ref: str | None = None
    image_url: str | None = None
    detection_json: dict[str, Any] | None = None
    planogram_json: dict[str, Any] | None = None
    extra_json: dict[str, Any] | None = None


class DatabaseQueryResult(CamelModel):
    """Envelope returned by ``GET /api/v1/database/records``."""

    records: list[DatabaseRecord] = Field(default_factory=list)


class DatabaseClearResult(CamelModel):
    """Result of wiping database-page records only."""

    deleted: int
    media_deleted: int = 0
    message: str = "Database records cleared."


class BackupMeta(CamelModel):
    """Manifest metadata for a system backup archive."""

    version: int = 1
    created_at: str
    app: str = "yolo-retail-ai-agent"
    database_scheme: str = "sqlite"


class BackupRestoreResult(CamelModel):
    """Result of restoring a system backup zip."""

    ok: bool
    message: str
    restored: dict[str, int] = Field(default_factory=dict)

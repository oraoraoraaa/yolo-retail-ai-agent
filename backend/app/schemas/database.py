"""Database record schemas (mirrors ``frontend/src/types/database.ts``)."""

from __future__ import annotations

from typing import Literal

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


class DatabaseQueryResult(CamelModel):
    """Envelope returned by ``GET /api/v1/database/records``."""

    records: list[DatabaseRecord] = Field(default_factory=list)

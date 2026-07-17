"""Planogram schemas (mirrors ``frontend/src/types/planogram.ts``)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import CamelModel


class PlanogramSlot(CamelModel):
    """One facing region drawn on a shelf planogram (normalized box in [0, 1])."""

    id: str
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    item_name: str = ""
    item_price: float | None = None
    item_stock: int = 0
    sku: str = ""
    notes: str = ""


class PlanogramCreate(CamelModel):
    """Payload for creating a planogram."""

    name: str
    description: str = ""
    image_base64: str = ""
    image_width: int = Field(default=0, ge=0)
    image_height: int = Field(default=0, ge=0)
    slots: list[PlanogramSlot] = Field(default_factory=list)


class PlanogramUpdate(CamelModel):
    """Partial update for an existing planogram."""

    name: str | None = None
    description: str | None = None
    image_base64: str | None = None
    image_width: int | None = Field(default=None, ge=0)
    image_height: int | None = Field(default=None, ge=0)
    slots: list[PlanogramSlot] | None = None


class Planogram(CamelModel):
    """Full planogram record stored in the database."""

    id: str
    name: str
    description: str = ""
    image_base64: str = ""
    image_width: int = 0
    image_height: int = 0
    image_ref: str | None = None
    image_url: str | None = None
    slots: list[PlanogramSlot] = Field(default_factory=list)
    created_at: str
    updated_at: str


class PlanogramListResult(CamelModel):
    """List wrapper for planogram records."""

    planograms: list[Planogram]
    active_planogram_id: str | None = None


class PlanogramMatchRequest(CamelModel):
    """Vision detections to match against drawn planogram slots."""

    vision_model_response: dict[str, Any]


class PlanogramMatchResult(CamelModel):
    """Coordinate match between detections and planogram slots."""

    planogram_id: str
    planogram_name: str
    slot_count: int = 0
    matches: list[dict[str, Any]] = Field(default_factory=list)
    gap_matches: list[dict[str, Any]] = Field(default_factory=list)
    missing_items: list[dict[str, Any]] = Field(default_factory=list)
    summary: str = ""

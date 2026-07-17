"""Shelf-image audit schemas (mirrors ``frontend/src/types/audit.ts``)."""

from __future__ import annotations

from typing import Any

from app.schemas.common import CamelModel


class DetectionAgentRequest(CamelModel):
    """Vision-model JSON payload sent from the local detector to the agent."""

    vision_model_response: dict[str, Any]
    planogram_response: dict[str, Any] | None = None
    language: str = "en"
    # Optional client-side image for audit persistence (raw base64 or data URL).
    image_base64: str | None = None
    source_label: str | None = None


class AuditAnalysisResult(CamelModel):
    """Result returned by the shelf-image audit endpoint."""

    # Short recommended next step for store staff.
    suggested_action: str
    # Longer reasoning that explains why the action was suggested.
    explanation: str
    # Persisted record id when the audit was saved.
    record_id: str | None = None
    # Optional closed-loop ticket ids created/updated from this audit.
    ticket_ids: list[str] = []
    closed_loop_narrative: str | None = None

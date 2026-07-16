"""Shelf-image audit schemas (mirrors ``frontend/src/types/audit.ts``)."""

from __future__ import annotations

from typing import Any

from app.schemas.common import CamelModel


class DetectionAgentRequest(CamelModel):
    """Vision-model JSON payload sent from the local detector to the agent."""

    vision_model_response: dict[str, Any]
    planogram_response: dict[str, Any] | None = None
    language: str = "en"


class AuditAnalysisResult(CamelModel):
    """Result returned by the shelf-image audit endpoint."""

    # Short recommended next step for store staff.
    suggested_action: str
    # Longer reasoning that explains why the action was suggested.
    explanation: str

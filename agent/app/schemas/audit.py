"""Shelf-image audit schemas (mirrors ``frontend/src/types/audit.ts``)."""

from __future__ import annotations

from app.schemas.common import CamelModel


class AuditAnalysisResult(CamelModel):
    """Result returned by the shelf-image audit endpoint."""

    # Short recommended next step for store staff.
    suggested_action: str
    # Longer reasoning that explains why the action was suggested.
    explanation: str

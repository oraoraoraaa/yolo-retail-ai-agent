"""Shelf-image audit endpoint.

``POST /api/v1/audit/analyze`` accepts a multipart ``image`` field and returns
``{ suggestedAction, explanation }``.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.schemas.audit import AuditAnalysisResult, DetectionAgentRequest
from app.services import get_agent, get_detector, get_store

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

_ALLOWED_PREFIX = "image/"


@router.post("/analyze", response_model=AuditAnalysisResult)
async def analyze_shelf_image(image: UploadFile = File(...)) -> AuditAnalysisResult:
    """Run gap detection on an uploaded shelf image."""
    if image.content_type and not image.content_type.startswith(_ALLOWED_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Expected an image upload, received '{image.content_type}'.",
        )

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image is empty.",
        )

    detector = get_detector()
    detection = detector.analyze(image_bytes)

    agent = get_agent()
    suggested_action, explanation = agent.summarize_audit(detection)

    if detection.available:
        get_store().add(
            "audit",
            title=image.filename or "Shelf audit",
            summary=f"{suggested_action} · {detection.gap_count} gap(s) detected.",
        )

    return AuditAnalysisResult(suggested_action=suggested_action, explanation=explanation)


@router.post("/analyze-detections", response_model=AuditAnalysisResult)
async def analyze_detection_json(payload: DetectionAgentRequest) -> AuditAnalysisResult:
    """Analyze local vision-model JSON with the retail agent."""
    agent = get_agent()
    suggested_action, explanation = agent.summarize_detection_json(
        payload.vision_model_response,
        payload.planogram_response,
        language=payload.language,
    )
    return AuditAnalysisResult(suggested_action=suggested_action, explanation=explanation)

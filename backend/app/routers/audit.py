"""Shelf-image audit endpoint.

``POST /api/v1/audit/analyze`` accepts a multipart ``image`` field, forwards it
to the local model-local vision service (local weight files), then returns an
agent narrative: ``{ suggestedAction, explanation }``.

``POST /api/v1/audit/analyze-detections`` accepts precomputed local vision JSON
(also produced by model-local) and returns the same narrative shape. Audits are
persisted with optional image refs + detection JSON.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.schemas.audit import AuditAnalysisResult, DetectionAgentRequest
from app.services import get_agent, get_detector, get_store
from app.services.auth import AuthUser, get_current_user
from app.services.media import decode_image_payload

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

_ALLOWED_PREFIX = "image/"


def _gap_count(vision: dict[str, Any] | None) -> int:
    if not vision:
        return 0
    summary = vision.get("summary") or {}
    if isinstance(summary, dict) and summary.get("gapCount") is not None:
        try:
            return int(summary["gapCount"])
        except (TypeError, ValueError):
            pass
    detections = vision.get("detections") or []
    if isinstance(detections, list):
        return sum(
            1
            for item in detections
            if isinstance(item, dict) and str(item.get("label", "")).lower() == "gap"
        )
    return 0


@router.post("/analyze", response_model=AuditAnalysisResult)
async def analyze_shelf_image(
    _user: Annotated[AuthUser, Depends(get_current_user)],
    image: UploadFile = File(...),
) -> AuditAnalysisResult:
    """Run gap detection on an uploaded shelf image via model-local."""
    settings = get_settings()
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
    if len(image_bytes) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Uploaded image exceeds the {settings.max_upload_bytes} byte limit "
                f"({len(image_bytes)} bytes)."
            ),
        )

    detector = get_detector()
    detection = await detector.analyze(image_bytes)

    agent = get_agent()
    if detection.available and detection.vision_model_response is not None:
        suggested_action, explanation = await agent.summarize_detection_json(
            detection.vision_model_response,
            planogram_response=None,
        )
    else:
        suggested_action, explanation = await agent.summarize_audit(detection)

    record_id: str | None = None
    if detection.available:
        record = get_store().add(
            "audit",
            title=image.filename or "Shelf audit",
            summary=f"{suggested_action} · {detection.gap_count} gap(s) detected.",
            image_bytes=image_bytes,
            image_mime=image.content_type,
            detection_json=detection.vision_model_response,
            extra_json={
                "suggestedAction": suggested_action,
                "explanation": explanation,
            },
        )
        record_id = record.id

    return AuditAnalysisResult(
        suggested_action=suggested_action,
        explanation=explanation,
        record_id=record_id,
    )


@router.post("/analyze-detections", response_model=AuditAnalysisResult)
async def analyze_detection_json(
    payload: DetectionAgentRequest,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> AuditAnalysisResult:
    """Analyze local vision-model JSON with the retail agent.

    The vision JSON is expected to come from model-local
    (``POST /api/v1/detect/image`` or ``/capture``).
    """
    settings = get_settings()
    if payload.image_base64 and len(payload.image_base64) > settings.max_base64_chars:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"imageBase64 exceeds the {settings.max_base64_chars} character limit "
                f"({len(payload.image_base64)} chars)."
            ),
        )

    agent = get_agent()
    suggested_action, explanation = await agent.summarize_detection_json(
        payload.vision_model_response,
        payload.planogram_response,
        language=payload.language,
    )

    image_bytes: bytes | None = None
    image_mime: str | None = None
    if payload.image_base64:
        image_bytes, image_mime = decode_image_payload(payload.image_base64)
        if image_bytes and len(image_bytes) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"Decoded image exceeds the {settings.max_upload_bytes} byte limit "
                    f"({len(image_bytes)} bytes)."
                ),
            )

    gaps = _gap_count(payload.vision_model_response)
    title = (payload.source_label or "").strip() or "Shelf audit"
    record = get_store().add(
        "audit",
        title=title,
        summary=f"{suggested_action} · {gaps} gap(s) detected.",
        image_bytes=image_bytes,
        image_mime=image_mime,
        detection_json=payload.vision_model_response,
        planogram_json=payload.planogram_response,
        extra_json={
            "suggestedAction": suggested_action,
            "explanation": explanation,
            "language": payload.language,
        },
    )

    return AuditAnalysisResult(
        suggested_action=suggested_action,
        explanation=explanation,
        record_id=record.id,
    )

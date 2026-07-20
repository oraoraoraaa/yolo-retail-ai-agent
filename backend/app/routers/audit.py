"""Shelf-image audit endpoint.

``POST /api/v1/audit/analyze`` accepts a multipart ``image`` field, forwards it
to the local model-local vision service (local weight files), then returns an
agent narrative: ``{ suggestedAction, explanation }``.

``POST /api/v1/audit/analyze-detections`` accepts precomputed local vision JSON
(also produced by model-local) and returns the same narrative shape. Audits are
persisted with optional image refs + detection JSON, and optionally run the
closed-loop Detect → Decide → Dispatch pipeline to open action tickets.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.config import get_settings
from app.schemas.audit import AuditAnalysisResult, DetectionAgentRequest
from app.services import get_agent, get_detector, get_store
from app.services.auth import AuthUser, require_write
from app.services.closed_loop import get_closed_loop_agent
from app.services.media import decode_image_payload

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

_ALLOWED_PREFIX = "image/"


def _normalize_language(language: str | None) -> str:
    """Coerce an arbitrary language hint to a supported code ('zh' or 'en')."""
    return "zh" if str(language or "").strip().lower().startswith("zh") else "en"


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


async def _run_closed_loop_safe(
    *,
    vision: dict[str, Any],
    planogram: dict[str, Any] | None,
    language: str,
    source_label: str | None,
    audit_record_id: str | None,
    dispatch: bool = True,
) -> tuple[list[str], str | None]:
    """Best-effort closed loop; never fails the audit response."""
    try:
        result = await get_closed_loop_agent().run(
            vision,
            planogram,
            language=language,
            source_label=source_label,
            audit_record_id=audit_record_id,
            dispatch=dispatch,
            dedupe=True,
        )
        ids = [t.id for t in result.tickets_created] + [t.id for t in result.tickets_updated]
        seen: set[str] = set()
        ordered: list[str] = []
        for ticket_id in ids:
            if ticket_id not in seen:
                seen.add(ticket_id)
                ordered.append(ticket_id)
        return ordered, result.narrative
    except Exception:  # pragma: no cover - defensive
        return [], None


@router.post("/analyze", response_model=AuditAnalysisResult)
async def analyze_shelf_image(
    _user: Annotated[AuthUser, Depends(require_write)],
    image: UploadFile = File(...),
    language: str = Query(default="en"),
) -> AuditAnalysisResult:
    """Run gap detection on an uploaded shelf image via model-local."""
    settings = get_settings()
    language = _normalize_language(language)
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
            language=language,
        )
    else:
        suggested_action, explanation = await agent.summarize_audit(
            detection, language=language
        )

    record_id: str | None = None
    ticket_ids: list[str] = []
    closed_loop_narrative: str | None = None
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
        if detection.vision_model_response is not None:
            ticket_ids, closed_loop_narrative = await _run_closed_loop_safe(
                vision=detection.vision_model_response,
                planogram=None,
                language=language,
                source_label=image.filename,
                audit_record_id=record_id,
            )

    return AuditAnalysisResult(
        suggested_action=suggested_action,
        explanation=explanation,
        record_id=record_id,
        ticket_ids=ticket_ids,
        closed_loop_narrative=closed_loop_narrative,
    )


@router.post("/analyze-detections", response_model=AuditAnalysisResult)
async def analyze_detection_json(
    payload: DetectionAgentRequest,
    _user: Annotated[AuthUser, Depends(require_write)],
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

    ticket_ids, closed_loop_narrative = await _run_closed_loop_safe(
        vision=payload.vision_model_response,
        planogram=payload.planogram_response,
        language=payload.language,
        source_label=payload.source_label,
        audit_record_id=record.id,
    )

    return AuditAnalysisResult(
        suggested_action=suggested_action,
        explanation=explanation,
        record_id=record.id,
        ticket_ids=ticket_ids,
        closed_loop_narrative=closed_loop_narrative,
    )

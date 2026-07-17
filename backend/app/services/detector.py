"""Client for the local vision service (`model-local/stream_server.py`).

All shelf vision inference is performed by the model-local process using local
weight files (ONNX / YOLO). This module never loads Ultralytics itself — it only
forwards images to the local HTTP API and normalizes the response.
"""

from __future__ import annotations

import base64
import threading
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings, get_settings


@dataclass
class Detection:
    """A single detected box with its class label and confidence."""

    label: str
    confidence: float


@dataclass
class GapDetectionResult:
    """Aggregated outcome of running the detector on one image."""

    available: bool
    detections: list[Detection] = field(default_factory=list)
    unavailable_reason: str | None = None
    vision_model_response: dict[str, Any] | None = None

    @property
    def gap_count(self) -> int:
        return sum(1 for det in self.detections if "gap" in det.label.lower())

    @property
    def product_count(self) -> int:
        return sum(1 for det in self.detections if "gap" not in det.label.lower())

    @property
    def total(self) -> int:
        return len(self.detections)


class GapDetector:
    """HTTP client for the local model-local vision service."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()

    def _detect_url(self) -> str:
        return f"{self._settings.local_vision_base_url}/api/v1/detect/image"

    def _health_url(self) -> str:
        return f"{self._settings.local_vision_base_url}/health"

    async def analyze(
        self, image_bytes: bytes, model: str | None = None
    ) -> GapDetectionResult:
        """Run detection on raw image bytes via the local vision service."""
        if not image_bytes:
            return GapDetectionResult(
                available=False,
                unavailable_reason="Uploaded image is empty.",
            )

        max_bytes = self._settings.max_upload_bytes
        if len(image_bytes) > max_bytes:
            return GapDetectionResult(
                available=False,
                unavailable_reason=(
                    f"Uploaded image exceeds the {max_bytes} byte limit "
                    f"({len(image_bytes)} bytes)."
                ),
            )

        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload: dict[str, Any] = {
            "imageBase64": f"data:image/jpeg;base64,{encoded}",
        }
        weights = model or self._settings.local_vision_model
        if weights:
            payload["model"] = weights

        try:
            async with httpx.AsyncClient(
                timeout=self._settings.local_vision_timeout
            ) as client:
                response = await client.post(self._detect_url(), json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                detail = exc.response.text
            except Exception:  # pragma: no cover - defensive
                detail = str(exc)
            return GapDetectionResult(
                available=False,
                unavailable_reason=(
                    "Local vision service rejected the request "
                    f"({exc.response.status_code}): {detail or exc}"
                ),
            )
        except Exception as exc:
            return GapDetectionResult(
                available=False,
                unavailable_reason=(
                    "Local vision service is unavailable at "
                    f"'{self._settings.local_vision_base_url}'. "
                    "Start model-local with `uv run stream_server.py`. "
                    f"Details: {exc}"
                ),
            )

        detections_raw = data.get("detections") or []
        detections: list[Detection] = []
        for item in detections_raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "object")
            try:
                confidence = float(item.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            detections.append(Detection(label=label, confidence=confidence))

        return GapDetectionResult(
            available=True,
            detections=detections,
            vision_model_response=data if isinstance(data, dict) else None,
        )


_detector: GapDetector | None = None


def get_detector() -> GapDetector:
    """Return the process-wide detector singleton."""
    global _detector
    if _detector is None:
        _detector = GapDetector(get_settings())
    return _detector


def reset_detector() -> None:
    """Clear the singleton (used by tests)."""
    global _detector
    _detector = None

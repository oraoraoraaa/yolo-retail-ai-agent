"""YOLOv8 gap-detection wrapper.

Loads the trained weights lazily and runs inference on an uploaded shelf image.
When ultralytics is not installed or the weights file is missing, the detector
reports itself as unavailable so callers can fall back to a placeholder response
instead of crashing.
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass, field

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
    """Thin, thread-safe wrapper around an ultralytics ``YOLO`` model."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._model = None
        self._load_error: str | None = None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._loaded = True

            weights = self._settings.yolo_weights_path
            if not weights.exists():
                self._load_error = (
                    f"Weights not found at '{weights}'. Train the model or set "
                    "YOLO_WEIGHTS_PATH to enable real detection."
                )
                return

            try:
                from ultralytics import YOLO
            except ImportError:
                self._load_error = (
                    "ultralytics is not installed. Run "
                    "`pip install -r ../model/gap-detection/requirements.txt` "
                    "to enable real detection."
                )
                return

            try:
                self._model = YOLO(str(weights))
            except Exception as exc:  # pragma: no cover - defensive
                self._load_error = f"Failed to load YOLO weights: {exc}"

    def analyze(self, image_bytes: bytes) -> GapDetectionResult:
        """Run detection on raw image bytes."""
        self._ensure_loaded()
        if self._model is None:
            return GapDetectionResult(available=False, unavailable_reason=self._load_error)

        try:
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:  # pragma: no cover - defensive
            return GapDetectionResult(
                available=False,
                unavailable_reason=f"Could not decode uploaded image: {exc}",
            )

        results = self._model.predict(
            source=image,
            imgsz=self._settings.yolo_imgsz,
            conf=self._settings.yolo_conf,
            iou=self._settings.yolo_iou,
            verbose=False,
        )

        detections: list[Detection] = []
        for result in results:
            names = result.names
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for cls_id, conf in zip(boxes.cls.tolist(), boxes.conf.tolist()):
                label = names.get(int(cls_id), str(int(cls_id))) if isinstance(names, dict) else str(int(cls_id))
                detections.append(Detection(label=label, confidence=float(conf)))

        return GapDetectionResult(available=True, detections=detections)


_detector: GapDetector | None = None


def get_detector() -> GapDetector:
    """Return the process-wide detector singleton."""
    global _detector
    if _detector is None:
        _detector = GapDetector(get_settings())
    return _detector

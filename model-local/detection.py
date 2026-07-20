"""Shared helpers for local YOLO / ONNX inference scripts."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import supervision as sv

box_annotator = sv.BoxAnnotator()
label_annotator = sv.LabelAnnotator()

# --- Anti-occlusion (temporal) tuning -------------------------------------
# A camera facing a shelf in a busy store constantly has customers walking
# through frame. A single snapshot of a person standing in front of a facing
# reads as a gap (or, when they fill the frame, as "no detections" → a false
# camera_issue). Buffering a short burst of frames and reasoning over their
# per-pixel median (a "clean plate") removes anyone who moves at all, while a
# motion mask flags the regions that are still busy so the decision layer can
# treat them as *obscured* rather than empty.

# Absolute per-pixel luminance delta (vs. the clean plate) that counts a pixel
# as "moved" in a given frame.
MOTION_DIFF_THRESHOLD = 25
# A detection box is flagged ``obscured`` when at least this fraction of its
# pixels fall inside the motion mask.
OBSCURED_OVERLAP_THRESHOLD = 0.5
# Motion blobs smaller than this fraction of the frame are ignored as speckle
# when reporting normalized occlusion regions.
OCCLUSION_MIN_AREA_FRAC = 0.01
# Fraction of the frame in motion above which the whole view is considered
# obstructed (a customer is standing right in front of the camera).
VIEW_OBSTRUCTED_COVERAGE = 0.35


def downscale_frame(frame: Any, max_width: int) -> Any:
    """Downscale ``frame`` so its width does not exceed ``max_width``.

    Used to keep the long-baseline clean-plate buffer memory-bounded: a naive
    buffer of full 1080p frames spanning minutes would be hundreds of MB, so we
    store a downscaled copy (one per audit). Aspect ratio is preserved and the
    frame is returned unchanged when it is already narrow enough or when
    ``max_width`` is non-positive.
    """
    if frame is None or max_width <= 0:
        return frame
    height, width = frame.shape[:2]
    if width <= max_width:
        return frame
    scale = max_width / float(width)
    new_size = (max_width, max(1, int(round(height * scale))))
    return cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)


def _match_shape(frame: Any, height: int, width: int) -> Any:
    """Resize ``frame`` to (height, width) when it differs, else return as-is."""
    if frame is None:
        return frame
    if frame.shape[0] == height and frame.shape[1] == width:
        return frame
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def unify_frames(frames: list[Any], *, max_width: int = 0) -> list[Any]:
    """Bring a set of frames to a single common resolution.

    The long-baseline clean plate medians frames captured across minutes with
    the current audit's burst; a streaming camera may have changed resolution
    or the baseline may be downscaled, so ``median_clean_plate`` (which requires
    identical shapes) would otherwise drop the mismatched frames. This resizes
    everything to the smallest common frame (optionally capped at ``max_width``)
    so they can be medianed together.
    """
    usable = [f for f in frames if f is not None]
    if not usable:
        return []
    target_w = min(f.shape[1] for f in usable)
    if max_width > 0:
        target_w = min(target_w, max_width)
    # Preserve aspect using the frame that defines the target width.
    ref = min(usable, key=lambda f: f.shape[1])
    ref_h, ref_w = ref.shape[:2]
    target_h = max(1, int(round(ref_h * (target_w / float(ref_w)))))
    return [_match_shape(f, target_h, target_w) for f in usable]


def median_clean_plate(frames: list[Any]) -> Any:
    """Return the per-pixel median of a burst of frames (a "clean plate").

    A shopper who occupies a pixel only briefly is the minority across the
    window, so the median resolves to the shelf behind them. Frames must share
    the same shape; the first frame is returned unchanged for a single-frame
    burst.
    """
    usable = [frame for frame in frames if frame is not None]
    if not usable:
        raise ValueError("median_clean_plate requires at least one frame")
    if len(usable) == 1:
        return usable[0]
    shape = usable[0].shape
    usable = [frame for frame in usable if frame.shape == shape]
    if len(usable) == 1:
        return usable[0]
    stack = np.stack(usable, axis=0)
    return np.median(stack, axis=0).astype(np.uint8)


def motion_occlusion_mask(
    frames: list[Any],
    *,
    diff_threshold: int = MOTION_DIFF_THRESHOLD,
) -> tuple[Any, float]:
    """Compute a binary motion mask and its frame-coverage fraction.

    No new model is required: since the camera is fixed, transient occlusion is
    just the set of pixels that differ from the burst's clean-plate luminance in
    at least one frame. Returns ``(mask, coverage)`` where ``mask`` is a uint8
    0/255 image and ``coverage`` is the fraction of pixels flagged as moving.
    """
    usable = [frame for frame in frames if frame is not None]
    if len(usable) < 2:
        height, width = (usable[0].shape[:2] if usable else (0, 0))
        return np.zeros((height, width), dtype=np.uint8), 0.0

    grays = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in usable]
    reference = np.median(np.stack(grays, axis=0), axis=0).astype(np.uint8)
    counts = np.zeros(reference.shape, dtype=np.uint16)
    for gray in grays:
        diff = cv2.absdiff(gray, reference)
        _, thresh = cv2.threshold(diff, diff_threshold, 1, cv2.THRESH_BINARY)
        counts += thresh.astype(np.uint16)

    mask = np.where(counts >= 1, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)
    coverage = float(np.count_nonzero(mask)) / float(mask.size) if mask.size else 0.0
    return mask, coverage


def occlusion_regions(
    mask: Any,
    *,
    min_area_frac: float = OCCLUSION_MIN_AREA_FRAC,
) -> list[dict[str, float]]:
    """Return normalized bounding boxes of significant motion blobs in ``mask``.

    These let the backend project occlusion onto planogram slots that produced
    no detection of their own (e.g. a customer fully covering a facing).
    """
    if mask is None or getattr(mask, "size", 0) == 0:
        return []
    height, width = mask.shape[:2]
    if height == 0 or width == 0:
        return []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total = float(height * width)
    regions: list[dict[str, float]] = []
    for contour in contours:
        x, y, box_w, box_h = cv2.boundingRect(contour)
        if total <= 0 or (box_w * box_h) / total < min_area_frac:
            continue
        regions.append(
            {
                "x1": x / width,
                "y1": y / height,
                "x2": (x + box_w) / width,
                "y2": (y + box_h) / height,
            }
        )
    return regions


def detection_obscured(
    mask: Any,
    box: dict[str, float],
    *,
    overlap_threshold: float = OBSCURED_OVERLAP_THRESHOLD,
) -> bool:
    """True when a detection box overlaps the motion mask beyond a threshold."""
    if mask is None or getattr(mask, "size", 0) == 0:
        return False
    height, width = mask.shape[:2]
    if height == 0 or width == 0:
        return False
    try:
        x1 = int(max(0, min(width, round(float(box.get("x1", 0.0))))))
        y1 = int(max(0, min(height, round(float(box.get("y1", 0.0))))))
        x2 = int(max(0, min(width, round(float(box.get("x2", 0.0))))))
        y2 = int(max(0, min(height, round(float(box.get("y2", 0.0))))))
    except (TypeError, ValueError):
        return False
    if x2 <= x1 or y2 <= y1:
        return False
    region = mask[y1:y2, x1:x2]
    if region.size == 0:
        return False
    return float(np.count_nonzero(region)) / float(region.size) >= overlap_threshold


def parse_video_reference(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def camera_backends() -> list[int]:
    """Return preferred OpenCV capture backends for the current platform.

    Linux prefers V4L2; macOS prefers AVFoundation; Windows prefers DSHOW/MSMF.
    CAP_ANY is always appended as a fallback so probing works cross-platform.
    """
    backends: list[int] = []
    platform = sys.platform

    if platform.startswith("linux") and hasattr(cv2, "CAP_V4L2"):
        backends.append(cv2.CAP_V4L2)
    if platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
        backends.append(cv2.CAP_AVFOUNDATION)
    if platform.startswith("win"):
        if hasattr(cv2, "CAP_DSHOW"):
            backends.append(cv2.CAP_DSHOW)
        if hasattr(cv2, "CAP_MSMF"):
            backends.append(cv2.CAP_MSMF)

    backends.append(cv2.CAP_ANY)

    # Preserve order while removing duplicates.
    unique: list[int] = []
    for backend in backends:
        if backend not in unique:
            unique.append(backend)
    return unique


def open_video_capture(video_reference: int | str) -> cv2.VideoCapture:
    """Open a camera index, device path, file, or stream URL.

    Integer camera indices try platform-appropriate backends first (so macOS
    does not fail on Linux-only ``CAP_V4L2``), then fall back to ``CAP_ANY``.
    """
    if isinstance(video_reference, int):
        last_capture: cv2.VideoCapture | None = None
        for backend in camera_backends():
            capture = cv2.VideoCapture(video_reference, backend)
            if capture.isOpened():
                return capture
            capture.release()
            last_capture = capture
        if last_capture is not None:
            # Return the last closed capture so callers can still call isOpened()
            # if they somehow ignore the exception path; we raise instead.
            pass
        raise RuntimeError(
            f"Could not open camera/video source {video_reference!r}. "
            "Try camera 0, camera 1, or a device path / stream URL. "
            f"Tried backends: {camera_backends()}"
        )

    capture = cv2.VideoCapture(video_reference)
    if not capture.isOpened():
        raise RuntimeError(
            f"Could not open camera/video source {video_reference!r}. "
            "Try camera 0, camera 1, or a /dev/videoX path / stream URL."
        )
    return capture


def probe_camera_index(index: int) -> bool:
    """Return True when the given camera index can be opened."""
    for backend in camera_backends():
        capture = cv2.VideoCapture(index, backend)
        try:
            if capture.isOpened():
                return True
        finally:
            capture.release()
    return False


def camera_display_name(index: int) -> str | None:
    """Return a human-readable device name for a camera index when available.

    On Linux, V4L2 exposes the device product name under
    ``/sys/class/video4linux/videoN/name`` (e.g. "Integrated Camera",
    "Logitech BRIO"). Returns None when no friendly name can be resolved, so
    callers can fall back to a generic label.
    """
    if sys.platform.startswith("linux"):
        name_path = Path(f"/sys/class/video4linux/video{index}/name")
        try:
            if name_path.exists():
                name = name_path.read_text(encoding="utf-8", errors="replace").strip()
                if name:
                    return name
        except OSError:
            pass
    return None


def get_detection_names(model: object, result: object | None) -> dict[int, str]:
    names = getattr(result, "names", None)
    if isinstance(names, dict):
        return {int(key): str(value) for key, value in names.items()}

    names = getattr(model, "names", None)
    if isinstance(names, dict):
        return {int(key): str(value) for key, value in names.items()}
    if isinstance(names, list):
        return {index: str(name) for index, name in enumerate(names)}
    return {}


def draw_predictions(result: object, frame: Any, model: object) -> Any:
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return frame

    xyxy = boxes.xyxy.cpu().numpy()
    confidence = boxes.conf.cpu().numpy() if boxes.conf is not None else None
    class_id = boxes.cls.cpu().numpy().astype(int) if boxes.cls is not None else None

    detections = sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)
    names = get_detection_names(model, result)

    labels = []
    for index in range(len(detections)):
        det_class_id = (
            None if detections.class_id is None else int(detections.class_id[index])
        )
        label = (
            names.get(det_class_id, "object") if det_class_id is not None else "object"
        )
        conf = (
            0.0
            if detections.confidence is None
            else float(detections.confidence[index])
        )
        labels.append(f"{label} {conf:.2f}")

    frame = box_annotator.annotate(scene=frame, detections=detections)
    return label_annotator.annotate(scene=frame, detections=detections, labels=labels)

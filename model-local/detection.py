"""Shared helpers for local YOLO / ONNX inference scripts."""

from __future__ import annotations

import sys
from typing import Any

import cv2
import supervision as sv

box_annotator = sv.BoxAnnotator()
label_annotator = sv.LabelAnnotator()


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

from __future__ import annotations

import argparse
import base64
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

from detection import (
    VIEW_OBSTRUCTED_COVERAGE,
    camera_display_name,
    detection_obscured,
    downscale_frame,
    draw_predictions,
    get_detection_names,
    median_clean_plate,
    motion_occlusion_mask,
    occlusion_regions,
    open_video_capture,
    parse_video_reference,
    probe_camera_index,
    unify_frames,
)

DEFAULT_WEIGHTS = (
    Path(__file__).resolve().parent.parent
    / "train"
    / "export"
    / "gap-product-chinese-yolo11n.onnx"
)

# Shared model cache keyed by resolved weights path. Multiple concurrent camera
# streams that use the same weights reuse one loaded model instead of loading a
# separate copy per camera.
_MODEL_CACHE: dict[Path, object] = {}
_MODEL_CACHE_LOCK = threading.Lock()

# One inference lock per loaded model. ``ThreadingHTTPServer`` dispatches each
# request on its own thread, and multi-camera background auditing means several
# ``/detect/capture`` calls can land concurrently. They all share the SAME cached
# model object (see ``_MODEL_CACHE``), and a single Ultralytics model is not safe
# to call ``predict`` on from multiple threads at once. Serializing predict per
# model keeps concurrent captures correct at the cost of running them one at a
# time (inference is the bottleneck anyway; the GPU/CPU can only do one at once).
_MODEL_PREDICT_LOCKS: dict[Path, threading.Lock] = {}


def _predict_lock(weights: Path) -> threading.Lock:
    """Return (and lazily create) the inference lock for a resolved weights path."""
    weights = weights.expanduser().resolve()
    with _MODEL_CACHE_LOCK:
        lock = _MODEL_PREDICT_LOCKS.get(weights)
        if lock is None:
            lock = threading.Lock()
            _MODEL_PREDICT_LOCKS[weights] = lock
        return lock


def predict_with_model(model: object, weights: Path, /, **predict_kwargs: Any) -> Any:
    """Run ``model.predict`` under the per-model inference lock.

    Concurrent captures against the same weights are serialized so two threads
    never call ``predict`` on the same Ultralytics object simultaneously.
    """
    with _predict_lock(weights):
        return model.predict(**predict_kwargs)  # type: ignore[attr-defined]


def load_model(weights: Path) -> object:
    weights = weights.expanduser().resolve()
    if not weights.exists():
        raise RuntimeError(f"Weights file does not exist: {weights}")

    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(weights)
        if cached is not None:
            return cached

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "ultralytics is not installed. Run `uv sync` in model-local first."
        ) from exc

    model = YOLO(str(weights))
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE[weights] = model
    return model


# How many raw frames a live stream keeps in its ring buffer so on-demand
# audits can build a temporal median "clean plate" from recent history instead
# of a single (possibly occluded) snapshot.
STREAM_RING_BUFFER_SIZE = 12
# Defaults for a self-contained burst capture (used when the camera is NOT
# already streaming): grab this many frames spaced this far apart.
DEFAULT_BURST_FRAMES = 7
DEFAULT_BURST_INTERVAL = 0.12

# --- Adaptive occlusion-aware burst (Plan 1) ------------------------------
# A quick burst clears customers who walk briskly past, but someone choosing /
# picking items lingers over a facing for several seconds and survives a <1s
# window. When the initial burst is still busy we escalate: keep grabbing
# frames over a progressively longer window (a slow walker is a minority at any
# given pixel over ~5s, so the median resolves to the shelf) up to a total time
# budget, stopping early once the scene reads clean. Empty-shelf audits never
# escalate, so they stay fast — latency cost is paid only when the view is busy.
# Occlusion coverage at/above which we keep extending the burst.
BURST_ESCALATE_COVERAGE = 0.15
# Spacing between the extra escalation frames (wider than the initial burst so
# the same total frame count spans more wall-clock time).
BURST_ESCALATE_INTERVAL = 0.35
# Hard ceiling on total burst wall-clock time (seconds) so a permanently busy
# aisle cannot block an audit forever — it just ends up "obscured".
BURST_MAX_SECONDS = 8.0
# Absolute ceiling on frames captured in one adaptive burst (memory guard:
# full-res frames are ~6MB at 1080p, so ~40 frames ≈ 240MB worst case).
BURST_MAX_FRAMES = 40

# --- Long-baseline clean plate from audit history (Plan 6) ----------------
# Background cameras re-audit every N seconds. Retaining one DOWNSCALED frame
# per audit gives a clean-plate baseline spanning minutes at trivial memory
# cost (a customer is a guaranteed tiny minority at every pixel over minutes,
# so the median is bulletproof) without holding the capture device open for a
# long in-capture burst or buffering hundreds of full-res frames.
#
# Tradeoff to respect: the baseline median only flips to a NEW state once that
# state is the majority of the window. Too long a window would delay a GENUINE
# gap (product sells out and stays empty) because stale "product" frames keep
# out-voting it. We therefore bound the window to ~the debounce window (180s):
# long enough that a customer lingering/choosing at a facing (tens of seconds)
# is a clear minority and is medianed away, but short enough that a real gap
# becomes the majority — and thus visible to YOLO — within ~90s, which the
# wall-clock span gate is going to wait out anyway. The two layers are tuned to
# the same timescale on purpose.
AUDIT_HISTORY_MAX_FRAMES = 18
AUDIT_HISTORY_MAX_AGE_SECONDS = 180.0
# Frames retained for the baseline are downscaled to this width to bound memory.
AUDIT_HISTORY_FRAME_WIDTH = 640

# Hard ceiling on a single POST body (bytes). Detect endpoints base64-decode the
# request body into memory, so an unbounded Content-Length is an easy
# out-of-memory / DoS vector if this port is ever reachable beyond localhost.
# A base64 image is ~4/3 its raw size, so this comfortably fits a ~14 MiB raw
# image while refusing absurd payloads outright. Override with MAX_REQUEST_BYTES.
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(20 * 1024 * 1024)))


@dataclass
class StreamOptions:
    camera: str = os.getenv("VIDEO_REFERENCE", "0")
    weights: Path = DEFAULT_WEIGHTS
    imgsz: int = 640
    conf: float = 0.25
    iou: float = 0.7
    device: str | None = None
    max_det: int = 300
    max_fps: float = 30
    # Temporal anti-occlusion: number of frames to buffer/burst for the median
    # clean plate. 1 disables it (single-snapshot behavior). Interval is the
    # spacing (seconds) between burst frames when the camera is not streaming.
    burst_frames: int = DEFAULT_BURST_FRAMES
    burst_interval: float = DEFAULT_BURST_INTERVAL
    # Adaptive escalation (Plan 1): when the initial burst is still occluded,
    # keep grabbing frames over a longer window up to this time budget, stopping
    # early once coverage drops below the escalation threshold. 0 disables
    # escalation (fixed burst only). Only used for non-streaming captures.
    burst_max_seconds: float = BURST_MAX_SECONDS
    # Long-baseline clean plate (Plan 6): fold up to this many downscaled recent
    # audit frames into the median so a slow/lingering customer is a minority
    # over minutes, not just the sub-second burst. 0 disables the baseline.
    use_audit_history: bool = True


class DetectionStream:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._latest_jpeg: bytes | None = None
        self._latest_raw_frame: Any | None = None
        # Rolling window of recent raw frames for temporal median clean-plate.
        self._raw_frames: deque[Any] = deque(maxlen=STREAM_RING_BUFFER_SIZE)
        # Long-baseline clean-plate history: one DOWNSCALED frame per audit with
        # its capture time, spanning minutes at trivial memory cost (Plan 6).
        self._audit_history: deque[tuple[float, Any]] = deque(
            maxlen=AUDIT_HISTORY_MAX_FRAMES
        )
        self._frame_id = 0
        self._model: object | None = None
        self._model_weights: Path | None = None
        self._status = "idle"
        self._error: str | None = None
        self._options: StreamOptions | None = None

    def start(self, options: StreamOptions) -> None:
        self.stop()
        with self._lock:
            self._status = "starting"
            self._error = None
            self._latest_jpeg = None
            self._latest_raw_frame = None
            self._raw_frames.clear()
            self._audit_history.clear()
            self._frame_id = 0
            self._options = options
            self._stop_event = threading.Event()
            self._worker = threading.Thread(
                target=self._run,
                args=(options, self._stop_event),
                name="detection-stream",
                daemon=True,
            )
            self._worker.start()

    def stop(self) -> None:
        worker: threading.Thread | None
        with self._lock:
            worker = self._worker
            self._stop_event.set()
            self._frame_ready.notify_all()

        if worker and worker.is_alive():
            worker.join(timeout=3)

        with self._lock:
            if self._worker is worker:
                self._worker = None
                self._latest_jpeg = None
                self._latest_raw_frame = None
                self._raw_frames.clear()
                self._audit_history.clear()
                self._frame_id = 0
                self._status = "idle"
                self._options = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self._status,
                "error": self._error,
                "camera": None if self._options is None else self._options.camera,
                "hasFrame": self._latest_jpeg is not None,
            }

    def wait_for_frame(
        self, last_frame_id: int, timeout: float = 5
    ) -> tuple[int, bytes] | None:
        deadline = time.monotonic() + timeout
        with self._frame_ready:
            while (
                (self._latest_jpeg is None or self._frame_id == last_frame_id)
                and self._status in {"starting", "live"}
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._frame_ready.wait(remaining)
            if self._latest_jpeg is None or self._frame_id == last_frame_id:
                return None
            return self._frame_id, self._latest_jpeg

    def latest_raw_frame(self) -> Any | None:
        """Return a copy of the most recent raw frame captured by the worker,
        or None when no frame is available yet."""
        with self._lock:
            if self._latest_raw_frame is None:
                return None
            return self._latest_raw_frame.copy()

    def recent_raw_frames(self, count: int) -> list[Any]:
        """Return copies of up to ``count`` most recent raw frames (newest last).

        Used to build a temporal median clean plate for on-demand audits without
        reopening the capture device the streaming worker already holds.
        """
        if count <= 0:
            return []
        with self._lock:
            if not self._raw_frames:
                return []
            frames = list(self._raw_frames)[-count:]
            return [frame.copy() for frame in frames]

    def record_audit_frame(self, frame: Any) -> None:
        """Store a downscaled copy of an audited frame for the long baseline.

        Called after each audit so the median clean plate can draw on frames
        spanning minutes (Plan 6). Frames are downscaled to bound memory.
        """
        if frame is None:
            return
        small = downscale_frame(frame, AUDIT_HISTORY_FRAME_WIDTH)
        with self._lock:
            self._audit_history.append((time.monotonic(), small.copy()))

    def audit_history_frames(
        self, *, max_age_seconds: float = AUDIT_HISTORY_MAX_AGE_SECONDS
    ) -> list[Any]:
        """Return copies of retained audit-history frames within the age window
        (newest last). Powers the long-baseline clean plate."""
        cutoff = time.monotonic() - max(0.0, max_age_seconds)
        with self._lock:
            return [
                frame.copy()
                for ts, frame in self._audit_history
                if ts >= cutoff
            ]

    def _load_model(self, weights: Path) -> object:
        weights = weights.expanduser().resolve()
        with self._lock:
            if self._model is not None and self._model_weights == weights:
                return self._model

        model = load_model(weights)
        with self._lock:
            self._model = model
            self._model_weights = weights
        return model

    def _run(self, options: StreamOptions, stop_event: threading.Event) -> None:
        capture = None
        try:
            video_reference = parse_video_reference(options.camera)
            capture = open_video_capture(video_reference)
            model = self._load_model(options.weights)
            min_frame_interval = 1 / options.max_fps if options.max_fps > 0 else 0
            last_inference_at = 0.0

            with self._frame_ready:
                self._status = "live"
                self._frame_ready.notify_all()

            while not stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError(f"Failed to read a frame from {video_reference!r}.")

                now = time.monotonic()
                if min_frame_interval:
                    elapsed = now - last_inference_at
                    if elapsed < min_frame_interval:
                        time.sleep(min_frame_interval - elapsed)
                last_inference_at = time.monotonic()

                results = predict_with_model(
                    model,
                    options.weights,
                    source=frame,
                    imgsz=options.imgsz,
                    conf=options.conf,
                    iou=options.iou,
                    device=options.device,
                    max_det=options.max_det,
                    verbose=False,
                )
                result = results[0] if results else None
                annotated_frame = draw_predictions(result, frame, model) if result else frame
                encoded, jpeg = cv2.imencode(".jpg", annotated_frame)
                if not encoded:
                    continue

                with self._frame_ready:
                    self._latest_jpeg = jpeg.tobytes()
                    # Retain the raw (un-annotated) frame so on-demand audits on a
                    # streaming camera can reuse it instead of fighting the running
                    # worker for exclusive access to the capture device. The ring
                    # buffer keeps a short history so audits can median several
                    # frames into an occlusion-free clean plate.
                    raw_copy = frame.copy()
                    self._latest_raw_frame = raw_copy
                    self._raw_frames.append(raw_copy)
                    self._frame_id += 1
                    self._status = "live"
                    self._frame_ready.notify_all()
        except Exception as exc:  # pragma: no cover - runtime hardware path
            with self._frame_ready:
                self._status = "error"
                self._error = str(exc)
                self._frame_ready.notify_all()
        finally:
            if capture is not None:
                capture.release()


class StreamRegistry:
    """Manage one ``DetectionStream`` per camera so several cameras can run
    concurrently. Streams are keyed by their camera id string."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._streams: dict[str, DetectionStream] = {}

    def _key(self, camera: str) -> str:
        return str(camera)

    def start(self, options: StreamOptions) -> dict[str, Any]:
        key = self._key(options.camera)
        with self._lock:
            existing = self._streams.get(key)
            if existing is None:
                existing = DetectionStream()
                self._streams[key] = existing
        existing.start(options)
        return existing.status()

    def stop(self, camera: str) -> dict[str, Any]:
        key = self._key(camera)
        with self._lock:
            existing = self._streams.pop(key, None)
        if existing is None:
            return {"status": "idle", "error": None, "camera": key, "hasFrame": False}
        existing.stop()
        status = existing.status()
        status["camera"] = key
        return status

    def stop_all(self) -> None:
        with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for item in streams:
            item.stop()

    def get(self, camera: str) -> DetectionStream | None:
        with self._lock:
            return self._streams.get(self._key(camera))

    def status(self, camera: str) -> dict[str, Any]:
        existing = self.get(camera)
        if existing is None:
            return {
                "status": "idle",
                "error": None,
                "camera": self._key(camera),
                "hasFrame": False,
            }
        status = existing.status()
        status["camera"] = self._key(camera)
        return status

    def statuses(self) -> dict[str, Any]:
        with self._lock:
            items = list(self._streams.items())
        cameras = []
        for key, item in items:
            status = item.status()
            status["camera"] = key
            cameras.append(status)
        return {"cameras": cameras}


registry = StreamRegistry()


class AuditHistoryStore:
    """Per-camera long-baseline clean-plate history for NON-streaming cameras.

    A streaming camera keeps its own baseline on its ``DetectionStream``, but a
    background-audited camera that is not streaming has no persistent worker, so
    this process-wide store retains one downscaled frame per audit per camera
    (Plan 6). A slow / lingering customer is a tiny minority across the retained
    minutes, so folding these into the median resolves the shelf behind them.
    Thread-safe: several cameras audit concurrently.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frames: dict[str, deque[tuple[float, Any]]] = {}

    def record(self, camera: str, frame: Any) -> None:
        if frame is None:
            return
        small = downscale_frame(frame, AUDIT_HISTORY_FRAME_WIDTH)
        key = str(camera)
        with self._lock:
            buf = self._frames.get(key)
            if buf is None:
                buf = deque(maxlen=AUDIT_HISTORY_MAX_FRAMES)
                self._frames[key] = buf
            buf.append((time.monotonic(), small.copy()))

    def get(
        self, camera: str, *, max_age_seconds: float = AUDIT_HISTORY_MAX_AGE_SECONDS
    ) -> list[Any]:
        cutoff = time.monotonic() - max(0.0, max_age_seconds)
        with self._lock:
            buf = self._frames.get(str(camera))
            if not buf:
                return []
            return [frame.copy() for ts, frame in buf if ts >= cutoff]

    def clear(self, camera: str | None = None) -> None:
        with self._lock:
            if camera is None:
                self._frames.clear()
            else:
                self._frames.pop(str(camera), None)


_audit_history_store = AuditHistoryStore()


def image_data_url(jpeg: bytes) -> str:
    encoded = base64.b64encode(jpeg).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def detection_payload(result: object | None, model: object, width: int, height: int) -> list[dict[str, Any]]:
    if result is None:
        return []

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []

    names = get_detection_names(model, result)
    xyxy = boxes.xyxy.cpu().numpy()
    confidence = boxes.conf.cpu().numpy() if boxes.conf is not None else None
    class_id = boxes.cls.cpu().numpy().astype(int) if boxes.cls is not None else None

    detections: list[dict[str, Any]] = []
    for index, box in enumerate(xyxy):
        det_class_id = None if class_id is None else int(class_id[index])
        conf = 0.0 if confidence is None else float(confidence[index])
        label = names.get(det_class_id, "object") if det_class_id is not None else "object"
        x1, y1, x2, y2 = [float(value) for value in box]
        detections.append(
            {
                "label": label,
                "confidence": conf,
                "classId": det_class_id,
                "box": {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "width": max(0.0, x2 - x1),
                    "height": max(0.0, y2 - y1),
                },
                "normalizedBox": {
                    "x1": x1 / width if width else 0,
                    "y1": y1 / height if height else 0,
                    "x2": x2 / width if width else 0,
                    "y2": y2 / height if height else 0,
                },
            }
        )
    return detections


def capture_burst(camera: str, count: int, interval: float) -> list[Any]:
    """Open a camera, grab ``count`` frames spaced ``interval`` seconds apart.

    Used when a camera is not already streaming (the common background-audit
    case) so we can still build a temporal median clean plate instead of relying
    on a single snapshot that a passing customer may have occluded.
    """
    frames: list[Any] = []
    capture = None
    try:
        capture = open_video_capture(parse_video_reference(camera))
        target = max(1, count)
        for index in range(target):
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame.copy())
            if index < target - 1 and interval > 0:
                time.sleep(interval)
    finally:
        if capture is not None:
            capture.release()
    if not frames:
        raise RuntimeError(f"Failed to read a frame from {camera!r}.")
    return frames


def capture_burst_adaptive(
    camera: str,
    count: int,
    interval: float,
    *,
    max_seconds: float = BURST_MAX_SECONDS,
    escalate_coverage: float = BURST_ESCALATE_COVERAGE,
    escalate_interval: float = BURST_ESCALATE_INTERVAL,
    max_frames: int = BURST_MAX_FRAMES,
) -> tuple[list[Any], bool]:
    """Grab an initial burst; if it is still busy, keep extending the window.

    A quick burst (``count`` frames × ``interval``) clears customers who walk
    briskly past, but someone choosing / picking items lingers for several
    seconds and survives a sub-second window. When the motion coverage of the
    frames captured so far is at/above ``escalate_coverage`` we keep grabbing
    additional frames spaced ``escalate_interval`` apart until either coverage
    drops below the threshold ("clean enough"), the wall-clock ``max_seconds``
    budget is exhausted, or ``max_frames`` is hit. Over ~5s a slow walker is a
    minority at any pixel, so the median resolves to the shelf. Empty-shelf
    audits read clean immediately and never escalate, staying fast.

    Returns ``(frames, escalated)``. Opens the device once and holds it for the
    whole window, so only used for cameras that are NOT already streaming.
    """
    frames: list[Any] = []
    escalated = False
    capture = None
    try:
        capture = open_video_capture(parse_video_reference(camera))
        started = time.monotonic()
        target = max(1, count)
        for index in range(target):
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame.copy())
            if index < target - 1 and interval > 0:
                time.sleep(interval)

        # Escalation: extend the window while the scene stays busy and we have
        # budget left. Skip entirely when escalation is disabled (max_seconds<=0)
        # or the initial burst is too small to compute motion.
        if max_seconds > 0 and len(frames) >= 2:
            while (
                len(frames) < max_frames
                and (time.monotonic() - started) < max_seconds
            ):
                _, coverage = motion_occlusion_mask(frames)
                if coverage < escalate_coverage:
                    break  # clean enough — stop early
                escalated = True
                if escalate_interval > 0:
                    time.sleep(escalate_interval)
                ok, frame = capture.read()
                if not ok:
                    break
                frames.append(frame.copy())
    finally:
        if capture is not None:
            capture.release()
    if not frames:
        raise RuntimeError(f"Failed to read a frame from {camera!r}.")
    return frames, escalated


def run_detection(
    frame,
    options: StreamOptions,
    *,
    burst_frames: list[Any] | None = None,
    baseline_frames: list[Any] | None = None,
    escalated: bool = False,
) -> dict[str, Any]:
    """Run detection on a frame, optionally using a temporal clean plate.

    When ``burst_frames`` holds 2+ frames, detection runs on their per-pixel
    median (removing anyone who moved) and a motion mask flags detections /
    regions that stayed occluded. The single ``frame`` is used as the display
    fallback and shape reference.

    ``baseline_frames`` are additional DOWNSCALED frames from recent audit
    history (Plan 6, long-baseline clean plate). They are folded into the
    median ONLY — never into the motion mask, which needs close-in-time frames
    to detect movement — so a slow / lingering customer that survives the
    sub-second burst is still out-voted by the minutes-long baseline in which
    they are a tiny minority. The motion mask (and thus obscured flags / view
    obstruction) is always computed from the close-in-time burst alone.
    """
    frames = [f for f in (burst_frames or []) if f is not None]
    if not frames:
        frames = [frame]

    model = load_model(options.weights)

    # Occlusion mask ALWAYS from the close-in-time burst (movement needs
    # adjacent-in-time frames; the long baseline would wash motion out).
    mask, occlusion_coverage = motion_occlusion_mask(frames)
    occlusion_boxes = occlusion_regions(mask)
    view_obstructed = occlusion_coverage >= VIEW_OBSTRUCTED_COVERAGE

    # Clean plate from burst + long baseline. Baseline frames may be a different
    # (downscaled) resolution, so unify everything to a common shape first; the
    # result is resized back to the burst's native resolution for detection so
    # planogram coordinates and the annotated image keep full resolution.
    native_h, native_w = frames[-1].shape[:2]
    baseline = [f for f in (baseline_frames or []) if f is not None]
    plate_source = frames + baseline
    if len(plate_source) > 1:
        unified = unify_frames(plate_source)
        clean_plate = median_clean_plate(unified)
        if clean_plate.shape[0] != native_h or clean_plate.shape[1] != native_w:
            clean_plate = cv2.resize(
                clean_plate, (native_w, native_h), interpolation=cv2.INTER_AREA
            )
    else:
        clean_plate = frames[-1]

    results = predict_with_model(
        model,
        options.weights,
        source=clean_plate,
        imgsz=options.imgsz,
        conf=options.conf,
        iou=options.iou,
        device=options.device,
        max_det=options.max_det,
        verbose=False,
    )
    result = results[0] if results else None
    annotated_frame = draw_predictions(result, clean_plate, model) if result else clean_plate
    encoded, jpeg = cv2.imencode(".jpg", annotated_frame)
    if not encoded:
        raise RuntimeError("Could not encode annotated image.")

    height, width = clean_plate.shape[:2]
    detections = detection_payload(result, model, width, height)

    # Flag detections whose box overlaps the motion mask so the decision layer
    # can treat those facings as obscured rather than genuinely empty.
    obscured_count = 0
    for det in detections:
        box = det.get("box") or {}
        is_obscured = detection_obscured(mask, box)
        det["obscured"] = is_obscured
        if is_obscured:
            obscured_count += 1

    gap_count = sum(1 for item in detections if "gap" in item["label"].lower())
    product_count = sum(1 for item in detections if "gap" not in item["label"].lower())

    return {
        "annotatedImage": image_data_url(jpeg.tobytes()),
        "detections": detections,
        "summary": {
            "total": len(detections),
            "gapCount": gap_count,
            "productCount": product_count,
            "obscuredCount": obscured_count,
        },
        "occlusion": {
            "coverage": round(occlusion_coverage, 4),
            "viewObstructed": view_obstructed,
            "regions": occlusion_boxes,
            "burstFrames": len(frames),
            "baselineFrames": len(baseline),
            "escalated": bool(escalated),
        },
        "image": {"width": width, "height": height},
        "model": str(options.weights.expanduser().resolve()),
        "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def probe_cameras(limit: int) -> list[dict[str, str]]:
    cameras: list[dict[str, str]] = []
    for index in range(limit):
        if probe_camera_index(index):
            name = camera_display_name(index)
            # ``name`` is the raw device product name (e.g. "Integrated Camera").
            # ``label`` is what the UI shows; include the index so identical
            # device names remain distinguishable.
            label = f"{name} (Camera {index})" if name else f"Camera {index}"
            cameras.append(
                {
                    "id": str(index),
                    "label": label,
                    "name": name or f"Camera {index}",
                }
            )
    return cameras


def available_models() -> list[dict[str, str]]:
    models = [
        {
            "id": str(DEFAULT_WEIGHTS),
            "label": DEFAULT_WEIGHTS.name,
            "path": str(DEFAULT_WEIGHTS),
        }
    ]
    export_dir = DEFAULT_WEIGHTS.parent
    if export_dir.exists():
        for path in sorted(export_dir.glob("*.onnx")):
            resolved = str(path.resolve())
            if resolved == str(DEFAULT_WEIGHTS.resolve()):
                continue
            models.append({"id": resolved, "label": path.name, "path": resolved})
        for path in sorted(export_dir.glob("*.pt")):
            resolved = str(path.resolve())
            models.append({"id": resolved, "label": path.name, "path": resolved})
    return models


def _coerce_float(*values: Any, default: float) -> float:
    """First non-None value coerced to float, else ``default``. Tolerates junk."""
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _coerce_bool(*values: Any, default: bool) -> bool:
    """First non-None value coerced to bool, else ``default``."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return default


def parse_options(payload: dict[str, Any]) -> StreamOptions:
    return StreamOptions(
        camera=str(payload.get("camera") or os.getenv("VIDEO_REFERENCE", "0")),
        weights=Path(str(payload.get("weights") or payload.get("model") or DEFAULT_WEIGHTS)),
        imgsz=int(payload.get("imgsz") or 640),
        conf=float(payload.get("conf") or 0.25),
        iou=float(payload.get("iou") or 0.7),
        device=str(payload["device"]) if payload.get("device") else None,
        max_det=int(payload.get("maxDet") or payload.get("max_det") or 300),
        max_fps=float(payload.get("maxFps") or payload.get("max_fps") or 30),
        burst_frames=int(
            payload.get("burstFrames")
            or payload.get("burst_frames")
            or DEFAULT_BURST_FRAMES
        ),
        burst_interval=float(
            payload.get("burstInterval")
            or payload.get("burst_interval")
            or DEFAULT_BURST_INTERVAL
        ),
        burst_max_seconds=_coerce_float(
            payload.get("burstMaxSeconds"),
            payload.get("burst_max_seconds"),
            default=BURST_MAX_SECONDS,
        ),
        use_audit_history=_coerce_bool(
            payload.get("useAuditHistory"),
            payload.get("use_audit_history"),
            default=True,
        ),
    )


class StreamRequestHandler(BaseHTTPRequestHandler):
    server_version = "YoloRetailStream/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "visionBackend": "local-weights",
                    "defaultWeights": str(DEFAULT_WEIGHTS),
                    "weightsPresent": DEFAULT_WEIGHTS.exists(),
                }
            )
        elif path == "/api/v1/stream/cameras":
            cameras = probe_cameras(limit=10)
            self._send_json(
                {
                    "cameras": cameras,
                    "defaultCamera": cameras[0]["id"] if cameras else "0",
                }
            )
        elif path == "/api/v1/stream/models":
            models = available_models()
            self._send_json(
                {
                    "models": models,
                    "defaultModel": models[0]["id"] if models else str(DEFAULT_WEIGHTS),
                }
            )
        elif path == "/api/v1/stream/statuses":
            self._send_json(registry.statuses())
        elif path == "/api/v1/stream/status":
            camera = self._query_param("camera")
            if camera is None:
                # No camera specified: report every active camera at once.
                self._send_json(registry.statuses())
            else:
                self._send_json(registry.status(camera))
        elif path == "/api/v1/stream/video":
            camera = self._query_param("camera") or os.getenv("VIDEO_REFERENCE", "0")
            self._send_mjpeg(camera)
        else:
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        # Refuse oversized bodies up front: every POST here reads (and detect
        # endpoints base64-decode) the whole body into memory, so an unbounded
        # Content-Length is an OOM/DoS vector. Bail before reading a byte.
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            content_length = 0
        if content_length > MAX_REQUEST_BYTES:
            self._send_json(
                {
                    "error": (
                        f"Request body exceeds the {MAX_REQUEST_BYTES} byte limit "
                        f"({content_length} bytes)."
                    )
                },
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        if path == "/api/v1/stream/start":
            payload = self._read_json()
            try:
                status = registry.start(parse_options(payload))
            except Exception as exc:
                self._send_json(
                    {"status": "error", "error": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json(status)
        elif path == "/api/v1/stream/stop":
            payload = self._read_json()
            camera = payload.get("camera")
            if camera is None:
                camera = self._query_param("camera")
            if camera is None:
                registry.stop_all()
                self._send_json(registry.statuses())
            else:
                self._send_json(registry.stop(str(camera)))
        elif path == "/api/v1/detect/image":
            self._handle_detect_image()
        elif path == "/api/v1/detect/capture":
            self._handle_detect_capture()
        else:
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def _query_param(self, name: str) -> str | None:
        query = parse_qs(urlparse(self.path).query)
        values = query.get(name)
        if not values:
            return None
        return values[0]

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        # Defense-in-depth: do_POST already rejects oversized Content-Length, but
        # never read more than the cap even if that guard is bypassed.
        body = self.rfile.read(min(length, MAX_REQUEST_BYTES))
        return json.loads(body.decode("utf-8"))

    def _handle_detect_image(self) -> None:
        payload = self._read_json()
        image_base64 = str(payload.get("imageBase64") or "")
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]
        if not image_base64:
            self._send_json(
                {"error": "Expected JSON field imageBase64."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            image_bytes = base64.b64decode(image_base64)
            frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError("Could not decode uploaded image.")
            result = run_detection(frame, parse_options(payload))
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json(result)

    def _handle_detect_capture(self) -> None:
        payload = self._read_json()
        options = parse_options(payload)

        # If this camera is already streaming, reuse recent live frames from its
        # ring buffer so we do not reopen the capture device (which the worker
        # already holds). A short burst lets us median out anyone who moved, and
        # the long-baseline audit history clears slow / lingering customers.
        active = registry.get(options.camera)
        if active is not None:
            frames = active.recent_raw_frames(options.burst_frames)
            if not frames:
                latest = active.latest_raw_frame()
                frames = [latest] if latest is not None else []
            if frames:
                baseline = (
                    active.audit_history_frames()
                    if options.use_audit_history
                    else []
                )
                try:
                    result = run_detection(
                        frames[-1],
                        options,
                        burst_frames=frames,
                        baseline_frames=baseline,
                    )
                    result["camera"] = options.camera
                    # Fold this audit's frame into the long baseline for next time.
                    if options.use_audit_history:
                        active.record_audit_frame(frames[-1])
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(result)
                return

        # Not streaming: grab a self-contained burst and median it into a clean
        # plate so a passing customer does not trip a false gap / camera_issue.
        # The burst escalates over a longer window when the view is still busy
        # (a customer choosing / picking items), while empty-shelf audits read
        # clean immediately and stay fast. A per-camera baseline of recent audit
        # frames extends the clean plate to span minutes.
        try:
            frames, escalated = capture_burst_adaptive(
                options.camera,
                options.burst_frames,
                options.burst_interval,
                max_seconds=options.burst_max_seconds,
            )
            baseline = (
                _audit_history_store.get(options.camera)
                if options.use_audit_history
                else []
            )
            result = run_detection(
                frames[-1],
                options,
                burst_frames=frames,
                baseline_frames=baseline,
                escalated=escalated,
            )
            result["camera"] = options.camera
            if options.use_audit_history:
                _audit_history_store.record(options.camera, frames[-1])
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json(result)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_mjpeg(self, camera: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        last_frame_id = 0
        while True:
            active = registry.get(camera)
            if active is None:
                # Stream was stopped (or never started) for this camera.
                break
            frame_result = active.wait_for_frame(last_frame_id)
            if frame_result is None:
                if active.status()["status"] in {"error", "idle"}:
                    break
                continue
            last_frame_id, frame = frame_result
            try:
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve local YOLO webcam detections as an HTTP MJPEG stream."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), StreamRequestHandler)
    print(f"Streaming API listening on http://{args.host}:{args.port}")
    print(f"Default local weights: {DEFAULT_WEIGHTS}")
    print("Open the frontend stream page, select a camera, and click Start streaming.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        registry.stop_all()
        server.server_close()


if __name__ == "__main__":
    main()

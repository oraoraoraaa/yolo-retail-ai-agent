from __future__ import annotations

import argparse
import base64
import json
import os
import threading
import time
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
    camera_display_name,
    draw_predictions,
    get_detection_names,
    open_video_capture,
    parse_video_reference,
    probe_camera_index,
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


class DetectionStream:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._latest_jpeg: bytes | None = None
        self._latest_raw_frame: Any | None = None
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

                results = model.predict(
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
                    # worker for exclusive access to the capture device.
                    self._latest_raw_frame = frame.copy()
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


def run_detection(frame, options: StreamOptions) -> dict[str, Any]:
    model = load_model(options.weights)
    results = model.predict(
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
        raise RuntimeError("Could not encode annotated image.")

    height, width = frame.shape[:2]
    detections = detection_payload(result, model, width, height)
    return {
        "annotatedImage": image_data_url(jpeg.tobytes()),
        "detections": detections,
        "summary": {
            "total": len(detections),
            "gapCount": sum(1 for item in detections if "gap" in item["label"].lower()),
            "productCount": sum(1 for item in detections if "gap" not in item["label"].lower()),
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
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length)
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

        # If this camera is already streaming, reuse the latest live frame so we
        # do not have to reopen the capture device (which a single worker already
        # holds). This is what lets a camera stream and audit at the same time.
        active = registry.get(options.camera)
        if active is not None:
            frame = active.latest_raw_frame()
            if frame is not None:
                try:
                    result = run_detection(frame, options)
                    result["camera"] = options.camera
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(result)
                return

        capture = None
        try:
            capture = open_video_capture(parse_video_reference(options.camera))
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Failed to read a frame from {options.camera!r}.")
            result = run_detection(frame, options)
            result["camera"] = options.camera
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        finally:
            if capture is not None:
                capture.release()

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

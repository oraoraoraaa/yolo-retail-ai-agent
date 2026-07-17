from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import cv2

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

from detection import draw_predictions, open_video_capture, parse_video_reference

VIDEO_REFERENCE = os.getenv("VIDEO_REFERENCE", "0")
DEFAULT_WEIGHTS = (
    Path(__file__).resolve().parent.parent
    / "train"
    / "export"
    / "gap-product-chinese-yolo11n.onnx"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream a webcam through a local ONNX model and show annotated frames."
    )
    parser.add_argument(
        "--camera",
        default=VIDEO_REFERENCE,
        help=(
            "OpenCV camera index or video path/URL. On Linux, index 0 maps to "
            "/dev/video0. On macOS, camera indices use AVFoundation."
        ),
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default=DEFAULT_WEIGHTS,
        help="Path to a local ONNX or YOLO weight file.",
    )
    parser.add_argument("--imgsz", type=int, default=640, help="Inference image size.")
    parser.add_argument(
        "--conf", type=float, default=0.25, help="Confidence threshold."
    )
    parser.add_argument("--iou", type=float, default=0.7, help="IoU threshold for NMS.")
    parser.add_argument(
        "--device",
        default=None,
        help="Inference device, e.g. cpu, 0, 0,1. Leave unset for the default.",
    )
    parser.add_argument(
        "--max-det", type=int, default=300, help="Maximum detections per frame."
    )
    parser.add_argument("--max-fps", type=float, default=30)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    weights = args.weights.expanduser().resolve()
    if not weights.exists():
        raise SystemExit(f"Weights file does not exist: {weights}")

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise SystemExit(
            "ultralytics is not installed. Install the model-local requirements before running inference."
        ) from exc

    video_reference = parse_video_reference(args.camera)
    capture = open_video_capture(video_reference)
    window_name = "Local ONNX Webcam"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    ok, preview_frame = capture.read()
    if ok:
        cv2.imshow(window_name, preview_frame)
        cv2.waitKey(1)

    print(f"Opened video source: {video_reference!r}")
    print(f"Loading local model: {weights}")
    model = YOLO(str(weights))
    print("Streaming. Press q in the window to quit.")

    min_frame_interval = 1 / args.max_fps if args.max_fps > 0 else 0
    last_inference_at = 0.0
    try:
        while True:
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
                imgsz=args.imgsz,
                conf=args.conf,
                iou=args.iou,
                device=args.device,
                max_det=args.max_det,
                verbose=False,
            )
            result = results[0] if results else None
            annotated_frame = (
                draw_predictions(result, frame, model) if result else frame
            )
            cv2.imshow(window_name, annotated_frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

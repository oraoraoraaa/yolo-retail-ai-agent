from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import cv2

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import supervision as sv

box_annotator = sv.BoxAnnotator()
label_annotator = sv.LabelAnnotator()
VIDEO_REFERENCE = os.getenv("VIDEO_REFERENCE", "0")


def parse_video_reference(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream a webcam through a local ONNX model and show annotated frames."
    )
    parser.add_argument(
        "--camera",
        default=VIDEO_REFERENCE,
        help=(
            "OpenCV camera index or video path/URL. On Linux, index 0 maps to "
            "/dev/video0, index 8 maps to /dev/video8. This is not the lsusb "
            "bus/device number."
        ),
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default="../train/export/goods-and-gaps-chinese-2-yolo11n.onnx",
        help="Path to a local ONNX model file, for example ./weights/best.onnx.",
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


def open_video_capture(video_reference: int | str) -> cv2.VideoCapture:
    if isinstance(video_reference, int):
        capture = cv2.VideoCapture(video_reference, cv2.CAP_V4L2)
    else:
        capture = cv2.VideoCapture(video_reference)
    if not capture.isOpened():
        raise SystemExit(
            f"Could not open camera/video source {video_reference!r}. "
            "Try --camera 0, --camera 1, or a /dev/videoX path."
        )
    return capture


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


def draw_predictions(result: object, frame, model: object):
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
    print(f"Loading local ONNX model: {weights}")
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

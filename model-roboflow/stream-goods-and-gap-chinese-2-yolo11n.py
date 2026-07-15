import argparse
import os
import time
import cv2
import onnxruntime

os.environ.setdefault("CORE_MODEL_GAZE_ENABLED", "False")
os.environ.setdefault("CORE_MODEL_SAM_ENABLED", "False")
os.environ.setdefault("CORE_MODEL_YOLO_WORLD_ENABLED", "False")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault(
    "ONNXRUNTIME_EXECUTION_PROVIDERS",
    '["CUDAExecutionProvider", "CPUExecutionProvider"]',
)

import supervision as sv
from inference import get_model

MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID", "goods-and-gap-chinese/2")
VIDEO_REFERENCE = os.getenv("VIDEO_REFERENCE", "0")

box_annotator = sv.BoxAnnotator()
label_annotator = sv.LabelAnnotator()


def parse_video_reference(value):
    try:
        return int(value)
    except ValueError:
        return value


def parse_args():
    parser = argparse.ArgumentParser(
        description="Stream a webcam through a Roboflow model and show annotated frames."
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
        "--model-id",
        default=MODEL_ID,
        help="Roboflow model id, for example 'goods-and-gap-chinese/2'.",
    )
    parser.add_argument("--max-fps", type=float, default=30)
    return parser.parse_args()


def normalize_result(result):
    if isinstance(result, list):
        result = result[0] if result else {}
    if hasattr(result, "dict"):
        return result.dict(by_alias=True, exclude_none=True)
    if hasattr(result, "model_dump"):
        return result.model_dump(by_alias=True, exclude_none=True)
    return result


def draw_predictions(result, frame):
    result = normalize_result(result)
    predictions = result.get("predictions")
    if predictions is None:
        return frame

    detections = sv.Detections.from_inference(result)

    labels = []
    class_names = detections.data.get("class_name", [])
    for i in range(len(detections)):
        name = class_names[i] if i < len(class_names) else "object"
        conf = detections.confidence[i] if detections.confidence is not None else 0
        labels.append(f"{name} {conf:.2f}")

    frame = box_annotator.annotate(scene=frame, detections=detections)
    return label_annotator.annotate(scene=frame, detections=detections, labels=labels)


def open_video_capture(video_reference):
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


def main():
    args = parse_args()
    api_key = os.getenv("ROBOFLOW_API_KEY")
    if not api_key:
        raise SystemExit("Set ROBOFLOW_API_KEY before running this script.")

    video_reference = parse_video_reference(args.camera)
    capture = open_video_capture(video_reference)
    window_name = "Roboflow Webcam"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    ok, preview_frame = capture.read()
    if ok:
        cv2.imshow(window_name, preview_frame)
        cv2.waitKey(1)

    print(f"Opened video source: {video_reference!r}")
    print(f"Loading Roboflow model: {args.model_id}")
    model = get_model(model_id=args.model_id, api_key=api_key)
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

            result = model.infer(frame)
            annotated_frame = draw_predictions(result, frame)
            cv2.imshow(window_name, annotated_frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

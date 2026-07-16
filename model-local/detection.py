from __future__ import annotations

import cv2
import supervision as sv

box_annotator = sv.BoxAnnotator()
label_annotator = sv.LabelAnnotator()


def parse_video_reference(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def open_video_capture(video_reference: int | str) -> cv2.VideoCapture:
    if isinstance(video_reference, int):
        capture = cv2.VideoCapture(video_reference, cv2.CAP_V4L2)
    else:
        capture = cv2.VideoCapture(video_reference)
    if not capture.isOpened():
        raise RuntimeError(
            f"Could not open camera/video source {video_reference!r}. "
            "Try camera 0, camera 1, or a /dev/videoX path."
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

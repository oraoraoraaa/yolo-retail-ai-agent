import os
import cv2
import supervision as sv
from inference import InferencePipeline

API_KEY = os.environ["ROBOFLOW_API_KEY"]

WORKSPACE_NAME = "rin-miyazaki"
WORKFLOW_ID = "goods-and-gap-chinese-vgoods-and-gap-chinese-2-yolo11n-t1-logic"
VIDEO_REFERENCE = 0  # default webcam. Try 1, 2, etc. for another camera.

box_annotator = sv.BoxAnnotator()
label_annotator = sv.LabelAnnotator()


def draw_predictions(result, video_frame):
    frame = video_frame.image.copy()

    predictions = result.get("predictions")
    if predictions is None:
        cv2.imshow("Roboflow Webcam", frame)
        cv2.waitKey(1)
        return

    detections = sv.Detections.from_inference(predictions)

    labels = []
    class_names = detections.data.get("class_name", [])
    for i in range(len(detections)):
        name = class_names[i] if i < len(class_names) else "object"
        conf = detections.confidence[i] if detections.confidence is not None else 0
        labels.append(f"{name} {conf:.2f}")

    frame = box_annotator.annotate(scene=frame, detections=detections)
    frame = label_annotator.annotate(scene=frame, detections=detections, labels=labels)

    cv2.imshow("Roboflow Webcam", frame)

    # Press q to close the window
    if cv2.waitKey(1) & 0xFF == ord("q"):
        raise KeyboardInterrupt


pipeline = InferencePipeline.init_with_workflow(
    api_key=API_KEY,
    workspace_name=WORKSPACE_NAME,
    workflow_id=WORKFLOW_ID,
    video_reference=VIDEO_REFERENCE,
    on_prediction=draw_predictions,
    max_fps=30,
)

try:
    pipeline.start()
    pipeline.join()
except KeyboardInterrupt:
    pipeline.terminate()
finally:
    cv2.destroyAllWindows()

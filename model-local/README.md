# Model Local Webcam Inference

This script opens a webcam or video source, runs a local ONNX model on each frame, and displays annotated bounding boxes in an OpenCV window.

## Setup

Install the local model dependencies:

```bash
uv sync
```

## Run

Pass the local ONNX file path with `--weights`:

```bash
uv run main.py --weights /path/to/model.onnx
```

Or run with default path(`../train/export/goods-and-gaps-chinese-2-yolo11n.onnx`):

```bash
uv run main.py --camera <camera_number>
```

Choose a specific camera:

```bash
uv run main.py --weights /path/to/model.onnx --camera 0
```

On Linux, OpenCV camera index `0` maps to `/dev/video0`, `1` maps to `/dev/video1`, and so on.

## Options

```bash
uv run main.py --help
```

- `--camera`: OpenCV camera index, device path, video file, or stream URL. Defaults to `0`.
- `--weights`: Required path to a local ONNX model file.
- `--imgsz`: Inference image size. Defaults to `640`.
- `--conf`: Confidence threshold. Defaults to `0.25`.
- `--iou`: IoU threshold for NMS. Defaults to `0.7`.
- `--device`: Inference device. Defaults to the Ultralytics default.
- `--max-det`: Maximum detections per frame. Defaults to `300`.
- `--max-fps`: Maximum inference FPS. Defaults to `30`.

Press `q` in the display window to stop the stream.

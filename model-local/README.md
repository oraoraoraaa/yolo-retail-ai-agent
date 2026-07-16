# Model Local Webcam Inference

These scripts run a webcam or video source through a local ONNX model and draw annotated bounding boxes.

- `main-on-screen.py` opens a local OpenCV preview window.
- `stream_server.py` exposes the same annotated frames to the frontend as an HTTP MJPEG stream.

## Setup

Install the local model dependencies:

```bash
uv sync
```

## Run

### Frontend Stream Integration

Start the local stream service:

```bash
uv run stream_server.py
```

By default it listens on `http://localhost:8001` and uses `../train/export/goods-and-gaps-chinese-2-yolo11n.onnx`.
Open the frontend, go to **Camera Stream**, select the camera, and click **Start streaming**.

Available stream endpoints:

- `GET /api/v1/stream/cameras`: probe local OpenCV camera indices.
- `POST /api/v1/stream/start`: start inference, for example `{ "camera": "0" }`.
- `GET /api/v1/stream/video`: MJPEG stream of annotated frames.
- `POST /api/v1/stream/stop`: stop the active camera stream.

### Window on-screen Test

Pass the local ONNX file path with `--weights`:

```bash
uv run main-on-screen.py --weights /path/to/model.onnx
```

Or run with default path(`../train/export/goods-and-gaps-chinese-2-yolo11n.onnx`):

```bash
uv run main-on-screen.py --camera <camera_number>
```

Choose a specific camera:

```bash
uv run main-on-screen.py --weights /path/to/model.onnx --camera 0
```

On Linux, OpenCV camera index `0` maps to `/dev/video0`, `1` maps to `/dev/video1`, and so on.

## Options

```bash
uv run main-on-screen.py --help
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

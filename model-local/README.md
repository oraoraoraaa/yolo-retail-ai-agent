# Model Local Webcam Inference

These scripts run a webcam or video source through a **local** ONNX/YOLO weight
file and draw annotated bounding boxes. This is the **only** runtime vision
backend used by the app stack (frontend stream/audit + agent audits).

- `stream_server.py` exposes annotated frames and single-image detection as an HTTP API (port `8001`).
- `main-on-screen.py` opens a local OpenCV preview window for manual testing.
- `detection.py` shared helpers (camera backends, drawing, labels).

## Setup

Install the local model dependencies:

```bash
uv sync
```

Default weights (repo-relative):

```text
../train/export/goods-and-gaps-chinese-2-yolo11n.onnx
```

## Run

### Frontend Stream Integration

Start the local stream service:

```bash
uv run stream_server.py
```

By default it listens on `http://localhost:8001`.
Open the frontend, go to **Camera Stream**, select the camera, and click **Start streaming**.

Available stream endpoints:

- `GET /health`: service + weights status.
- `GET /api/v1/stream/cameras`: probe local OpenCV camera indices (macOS / Linux / Windows backends).
- `GET /api/v1/stream/models`: list selectable local model weights under `train/export/`.
- `POST /api/v1/stream/start`: JSON `{ "camera": "0" }` starts annotated streaming.
- `GET /api/v1/stream/video`: MJPEG stream of annotated frames.
- `POST /api/v1/stream/stop`: stop the active camera stream.
- `POST /api/v1/detect/image`: JSON image payload → annotated image + detection JSON.
- `POST /api/v1/detect/capture`: JSON `{ camera, model }` → one camera capture detection.

### Window on-screen Test

```bash
uv run main-on-screen.py --weights ../train/export/goods-and-gaps-chinese-2-yolo11n.onnx
```

Or with the default path:

```bash
uv run main-on-screen.py --camera 0
```

## Options

```bash
uv run main-on-screen.py --help
```

- `--camera`: OpenCV camera index, device path, video file, or stream URL. Defaults to `0`.
- `--weights`: Path to a local ONNX/YOLO model file.
- `--imgsz`: Inference image size. Defaults to `640`.
- `--conf`: Confidence threshold. Defaults to `0.25`.
- `--iou`: IoU threshold for NMS. Defaults to `0.7`.
- `--device`: Inference device. Defaults to the Ultralytics default.
- `--max-det`: Maximum detections per frame. Defaults to `300`.
- `--max-fps`: Maximum inference FPS. Defaults to `30`.

Press `q` in the display window to stop the stream.

## Camera backends

`detection.open_video_capture` / `probe_camera_index` try platform-appropriate
backends:

| OS | Preferred backend | Fallback |
| --- | --- | --- |
| Linux | `CAP_V4L2` | `CAP_ANY` |
| macOS | `CAP_AVFOUNDATION` | `CAP_ANY` |
| Windows | `CAP_DSHOW` / `CAP_MSMF` | `CAP_ANY` |

## Tests

```bash
python -m pytest tests
```

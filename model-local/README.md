# Model Local Webcam Inference

Local ONNX/YOLO weight files only — the sole runtime vision backend for the app.

- `stream_server.py` — HTTP API on port `8001` (stream + detect)
- `main-on-screen.py` — OpenCV preview window
- `detection.py` — shared camera backends + drawing helpers

## Setup (uv)

```bash
uv sync
```

Default weights: `../train/export/goods-and-gaps-chinese-2-yolo11n.onnx`

## Run

```bash
uv run stream_server.py
# http://localhost:8001
```

On-screen test:

```bash
uv run main-on-screen.py --weights ../train/export/goods-and-gaps-chinese-2-yolo11n.onnx
# or defaults:
uv run main-on-screen.py --camera 0
```

### Endpoints

- `GET /health`
- `GET /api/v1/stream/cameras`
- `GET /api/v1/stream/models`
- `POST /api/v1/stream/start` — `{ "camera": "0" }`
- `GET /api/v1/stream/video` — MJPEG
- `POST /api/v1/stream/stop`
- `POST /api/v1/detect/image`
- `POST /api/v1/detect/capture`

## Camera backends

| OS | Preferred | Fallback |
| --- | --- | --- |
| Linux | `CAP_V4L2` | `CAP_ANY` |
| macOS | `CAP_AVFOUNDATION` | `CAP_ANY` |
| Windows | `CAP_DSHOW` / `CAP_MSMF` | `CAP_ANY` |

## Tests

```bash
uv run pytest
```

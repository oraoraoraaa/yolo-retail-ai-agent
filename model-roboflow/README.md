# Model Webcam Inference

This script opens a webcam or video source, sends frames to a Roboflow model, and displays the annotated bounding-box output in an OpenCV window.

It uses a direct OpenCV capture loop with Roboflow's local `inference` model API. It does not call the serverless still-image Workflow endpoint for `goods-and-gap-chinese/2`; Roboflow's deployment prompt notes that live video uses a different path.

## Setup

Install the model dependencies, then set your Roboflow API key:

```bash
uv sync
export ROBOFLOW_API_KEY="your_roboflow_api_key"
```

> Optional: Specify Cache Directory or Use Cached Data
>
> ```bash
> export MODEL_CACHE_DIR="$PWD/model-cache"
> ```

## Run

Use the default model, `goods-and-gap-chinese/2`, with the default camera:

```bash
./.venv/bin/python stream-goods-and-gap-chinese-2-yolo11n.py
```

Choose a specific camera:

```bash
./.venv/bin/python stream-goods-and-gap-chinese-2-yolo11n.py --camera 0
```

On Linux, OpenCV camera index `0` maps to `/dev/video0`, `1` maps to `/dev/video1`, and so on. Check with:

```bash
ls /dev/video*
```

Or use `v4l2-ctl` to examine video files information:

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --info
```

You can also pass a device path, video file, or stream URL:

```bash
./.venv/bin/python stream-goods-and-gap-chinese-2-yolo11n.py --camera /dev/video0
```

## Options

```bash
./.venv/bin/python stream-goods-and-gap-chinese-2-yolo11n.py --help
```

- `--camera`: OpenCV camera index, device path, video file, or stream URL. Defaults to `0`.
- `--model-id`: Roboflow model id. Defaults to `goods-and-gap-chinese/2`.
- `--max-fps`: Maximum inference FPS. Defaults to `30`.

Press `q` in the display window to stop the stream.

## About the Roboflow Workflow prompt

The copied Roboflow deployment prompt is for the still-image workflow:

- Workspace: `rin-miyazaki`
- Workflow id: `goods-and-gap-chinese-vstream-goods-and-gap-chinese-2-yolo11n-t1-logic`
- Declared input: `image`

That workflow should be integrated only after grounding it with Roboflow MCP calls such as `workflows_get` and `workflows_run`. Those tools are not available in this local session, so the workflow response shape has not been verified here.

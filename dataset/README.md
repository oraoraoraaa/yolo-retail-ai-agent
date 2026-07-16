# Dataset helpers

Download Roboflow shelf datasets for YOLO training.

Roboflow is used **only for dataset download**, not for runtime inference
(runtime vision is local weights via `model-local/`).

## Setup (uv)

```bash
cd dataset
uv sync
```

## Download

```bash
export ROBOFLOW_API_KEY=...   # optional; scripts may still prompt
uv run python sku-1kimg-yolov8.py
uv run python sku-gap-700img-yolov8.py
```

API key docs: https://docs.roboflow.com/developer/authentication/find-your-roboflow-api-key

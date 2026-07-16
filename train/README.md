# Gap Detection

Reusable YOLO scripts for training, validating, predicting, and exporting shelf
gap-detection models.

## Dataset

Provide the dataset root and dataset YAML when running scripts (YAML may be
relative to the dataset root, e.g. `data.yaml`).

Roboflow exports may contain polygon labels. By default the scripts prepare a
derived detection dataset (images linked, polygons → YOLO boxes) under the run
artifacts directory, leaving the source dataset unchanged.

## Install (uv)

```bash
cd train
uv sync
```

## Train

```bash
uv run python train.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --model yolo11m.pt \
  --epochs 300 \
  --imgsz 1024 \
  --batch -1 \
  --cache
```

Artifacts: `artifacts/<dataset-name>/train`  
Prepared detection data: `artifacts/<dataset-name>/_prepared_detection`

Smaller baseline example:

```bash
uv run python train.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --model yolo11n.pt \
  --epochs 300 \
  --imgsz 1024 \
  --batch -1
```

## Validate

```bash
uv run python validate.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --data data.yaml \
  --weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --split val
```

## Predict

```bash
uv run python predict.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --data data.yaml \
  --weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --source ../dataset/goods-and-gaps-chinese-2/valid/images
```

## Export

```bash
uv run python export.py \
  --weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --format onnx
```

## Runtime weights used by the app

```text
train/export/goods-and-gaps-chinese-2-yolo11n.onnx
```

Loaded by [`model-local/stream_server.py`](../model-local/stream_server.py).
The agent does **not** run YOLO itself.

## Trained Data

If local training is impractical, download pre-trained runs (Google Drive):

### sku-gap-700img-1

- [20260714024207-yolov8m](https://drive.google.com/drive/folders/1AMQq7KjH9x6AUVZdDsB0YwjcriO1Q9QP?usp=sharing)

```text
train/
├── artifacts/
│   └── <dataset-name>/
│       └── train/
│           └── weights/
│               ├── best.pt
│               └── last.pt
└── export/
    └── goods-and-gaps-chinese-2-yolo11n.onnx
```

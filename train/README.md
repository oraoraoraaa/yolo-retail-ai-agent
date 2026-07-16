# Gap Detection

This folder contains reusable YOLO scripts for training, validating, predicting, and exporting object detection models on YOLO-format shelf datasets.

## Dataset

Provide the dataset root and dataset YAML explicitly when running the scripts.

The YAML can be relative to the dataset root, for example `data.yaml`.

Roboflow exports can contain polygon/segmentation labels even when you want a detector. The training, validation, and prediction scripts prepare a derived detection dataset by default under the run artifacts directory:

- images are linked to the source dataset
- polygon labels are converted to YOLO `class x_center y_center width height` boxes
- the source dataset is left unchanged

For `dataset/goods-and-gaps-chinese-2`, this matters: most labels are polygons, and the dataset is small and imbalanced (`gap` has far fewer boxes than `product`). High image size is important because shelf products and empty gaps are small.

## Install

Install the model dependency from this folder:

```bash
pip install -r requirements.txt
```

## Train

```bash
python train.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --model yolo11m.pt \
  --epochs 300 \
  --imgsz 1024 \
  --batch -1 \
  --cache
```

Training artifacts are written to `artifacts/<dataset-name>/train` by default. The prepared detection dataset is written to `artifacts/<dataset-name>/_prepared_detection`.

If YOLO11m underperforms Roboflow YOLO11n on this 85-image dataset, also train a YOLO11n or YOLO11s baseline locally with the same command. A larger model can overfit a small dataset, so bigger is not automatically better.

Useful options:

```bash
python train.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --model yolo11n.pt \
  --epochs 300 \
  --imgsz 1024 \
  --batch -1
```

## Validate

```bash
python validate.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --data data.yaml \
  --weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --split val
```

## Predict

Run inference on a folder or single image and save annotated outputs with boxes:

```bash
python predict.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --data data.yaml \
  --weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --source ../dataset/goods-and-gaps-chinese-2/valid/images
```

The resulting images are written under `<the_artifact_path>/predict` by default.

## Export

```bash
python export.py \
  --weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --format onnx
```

## Runtime weights used by the app

After export, place (or keep) ONNX weights under:

```text
train/export/goods-and-gaps-chinese-2-yolo11n.onnx
```

The app stack loads these via [`model-local/stream_server.py`](../model-local/stream_server.py).
The agent backend does **not** run YOLO itself; it forwards images to model-local.

## Trained Data

If training on your devices is not realistic, download trained data using the following links (google drive).

### sku-gap-700img-1

- [20260714024207-yolov8m](https://drive.google.com/drive/folders/1AMQq7KjH9x6AUVZdDsB0YwjcriO1Q9QP?usp=sharing)

Put downloaded training runs under `train/artifacts/<dataset-name>/train/` (or
export ONNX into `train/export/` for app inference):

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

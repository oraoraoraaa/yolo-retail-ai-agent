# Gap Detection

This folder contains the YOLOv8 scripts for training a one-class detector that finds `gap` regions in shelf images.

## Dataset

The scripts expect the dataset at:

- `dataset/sku-gap-700img-1/data.yaml`

The class name should be `gap`.

## Install

Install the model dependency from this folder:

```bash
pip install -r model/gap-detection/requirements.txt
```

## Train

```bash
python train.py \
  --data ../../dataset/sku-gap-700img-1/data.yaml \
  --model yolov8n.pt \
  --epochs 100 \
  --imgsz 640 \
  --batch 16
```

Training artifacts are written to `artifacts/gap-detection/train` by default.

## Validate

```bash
python validate.py \
  --weights ../../artifacts/gap-detection/train/weights/best.pt \
  --split val
```

## Predict

Run inference on a folder or single image and save annotated outputs with boxes:

```bash
python predict.py \
  --weights ../../artifacts/gap-detection/train/weights/best.pt \
  --source ../../dataset/sku-gap-700img-1/valid/images
```

The resulting images are written under `artifacts/gap-detection/predict` by default.

## Export

```bash
python export.py \
  --weights ../../artifacts/gap-detection/train/weights/best.pt \
  --format onnx
```

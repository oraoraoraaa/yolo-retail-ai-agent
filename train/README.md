# Gap Detection

This folder contains reusable YOLOv8 scripts for training, validating, predicting, and exporting object detection models on any YOLO-format dataset.

## Dataset

Provide the dataset root and dataset YAML explicitly when running the scripts.

The YAML can be relative to the dataset root, for example `data.yaml`.

## Install

Install the model dependency from this folder:

```bash
pip install -r requirements.txt
```

## Train

```bash
python train.py \
  --dataset-dir <the_dataset_dir> \
  --data data.yaml \
  --model yolo11m.pt \
  --epochs 300 \
  --imgsz 640 \
  --batch 16
```

Training artifacts are written to `artifacts/gap-detection/train` by default.

## Validate

```bash
python validate.py \
  --dataset-dir <the_dataset_dir> \
  --data data.yaml \
  --weights <the_artifact_path>/train/weights/best.pt \
  --split val
```

## Predict

Run inference on a folder or single image and save annotated outputs with boxes:

```bash
python predict.py \
  --dataset-dir <the_dataset_dir> \
  --data data.yaml \
  --weights <the_artifact_path>/train/weights/best.pt \
  --source <the_dataset_dir>/valid/images
```

The resulting images are written under `<the_artifact_path>/predict` by default.

## Export

```bash
python export.py \
  --weights <the_artifact_path>/train/weights/best.pt \
  --format onnx
```

## Trained Data

If training on your devices is not realistic, download trained data using the following links (google drive).

### sku-gap-700img-1

- [20260714024207-yolov8m](https://drive.google.com/drive/folders/1AMQq7KjH9x6AUVZdDsB0YwjcriO1Q9QP?usp=sharing)

Put download data as the following file tree:

```text
/
├── artifacts/
│   └── gap-detection/
│       └── train/
│           ├── weights/
│           │   ├── best.pt
│           │   └── last.pt
│           ├── args.yaml
│           ├── BoxF1_curve.png
│           ├── BoxP_curve.png
│           ├── BoxPR_curve.png
│           ├── BoxR_curve.png
│           ├── confusion_matrix_normalized.png
│           ├── confusion_matrix.png
│           ├── labels.jpg
│           ├── results.csv
│           ├── results.png
│           ├── train_batch0.jpg
│           ├── train_batch1.jpg
│           ├── train_batch2.jpg
│           ├── train_batch2880.jpg
│           ├── train_batch2881.jpg
│           ├── train_batch2882.jpg
│           ├── val_batch0_labels.jpg
│           ├── val_batch0_pred.jpg
│           ├── val_batch1_labels.jpg
│           ├── val_batch1_pred.jpg
│           ├── val_batch2_labels.jpg
│           └── val_batch2_pred.jpg
```

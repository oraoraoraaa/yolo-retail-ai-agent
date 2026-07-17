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

## Datasets in this folder

| Directory | Classes | Role |
| --- | --- | --- |
| `gap-product-chinese-2` | gap + product | Small fully labeled seed (~122 images) |
| `sku-gap-700img-1` | **gap only** | Larger shelf set (~700 images); products unlabeled |
| `sku-1kimg-1` | product-style SKU crops | Optional product prior (SKU-110K style) |
| `sku-gap-700img-1-with-products` | gap + **pseudo** product | Built by `train/merge_datasets.py pseudo-label` |
| `merged-gap-product` | gap + product | Built by `train/merge_datasets.py merge` / `build` |

Downloaded / generated dataset trees are **not** committed (see root
`.gitignore`). Rebuild locally with the scripts above, then the merge pipeline
in [`train/README.md`](../train/README.md).

## Using the gap-only 700-image set for two-class training

`sku-gap-700img-1` only annotates empty slots. Training YOLO on it alone
never teaches the `product` class. The intended workflow:

1. Train a teacher on `gap-product-chinese-2` (or reuse
   `train/artifacts/gap-product-chinese-2/train/weights/best.pt`).
2. Pseudo-label products on `sku-gap-700img-1` (keep human gaps).
3. Merge into `merged-gap-product`.
4. Train with `train/train.py --dataset-dir ../dataset/merged-gap-product`.

```bash
cd ../train
uv run python merge_datasets.py build \
  --teacher-weights artifacts/gap-product-chinese-2/train/weights/best.pt \
  --device 0
```

See **Class imbalance** and **Eval report** sections in
[`train/README.md`](../train/README.md).

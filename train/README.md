# Gap Detection

Reusable YOLO scripts for training, validating, predicting, and exporting shelf
gap-detection models (`0=gap`, `1=product`).

## Dataset

Provide the dataset root and dataset YAML when running scripts (YAML may be
relative to the dataset root, e.g. `data.yaml`).

Roboflow exports may contain polygon labels. By default the scripts prepare a
derived detection dataset (images linked, polygons → YOLO boxes) under the run
artifacts directory, leaving the source dataset unchanged.

| Dataset | Images | Labels | Notes |
| --- | --- | --- | --- |
| `goods-and-gaps-chinese-2` | ~122 | gap + product | Fully labeled seed set (tiny) |
| `sku-gap-700img-1` | ~724 | **gap only** | Large; needs product pseudo-labels before two-class training |
| `merged-gap-product` | ~800+ | gap + product | Built by `merge_datasets.py` (recommended train root) |

## Install (uv)

```bash
cd train
uv sync
```

## Class imbalance (gap rare vs product)

On `goods-and-gaps-chinese-2` train split the raw counts are roughly:

* gap ≈ 141 boxes
* product ≈ 5856 boxes
* **~1 : 40** gap:product

Products dominate, so a vanilla detector overfits to products and under-recalls
gaps — the class the retail agent needs for restock / phantom-inventory alerts.

### What we do

1. **Canonical two-class scheme** — `0=gap`, `1=product` everywhere (merged
   datasets, eval report, runtime ONNX).
2. **Gap-image oversampling** (default on via `--balance-gaps`) — train images
   that contain ≥1 gap are duplicated `gap_image_oversample` times (default
   **2**) during detection prep so the sampler sees empty slots more often.
3. **Loss / aug knobs** — light Ultralytics `copy_paste` (default **0.1**) and
   optional higher `cls` loss gain if the head collapses to one class.
4. **Do not drop products** to “balance” counts — products teach shelf structure
   and stop the model painting free pixels as gaps.
5. **Evaluate gap recall separately** — overall mAP hides rare-class failure.
   Use `eval_report.py` (below).
6. **Runtime conf** — keep product conf around **0.25–0.35**; for gap alerts
   prefer the lower recommended threshold from the eval report (often
   **~0.15–0.25**).

Policy defaults live in [`imbalance.py`](imbalance.py)
(`DEFAULT_IMBALANCE_POLICY`). Full guidance is also appended to every eval
report Markdown file.

### What not to do

* Do not train on **gap-only** labels without product boxes/pseudo-labels —
  the model never learns the product class boundary.
* Do not set an extremely high conf (e.g. 0.6+) for shelf audits; that kills
  gap recall on small empty slots.

## Enlarge the tiny fully-labeled set (pseudo-label + merge)

`sku-gap-700img-1` has ~700 images with **gap-only** annotations. To use it for
two-class training without hand-labeling every product:

1. Train (or reuse) a **teacher** on `goods-and-gaps-chinese-2` (gap+product).
2. Run the teacher on every gap-only image; keep high-confidence **product**
   boxes that do not heavily overlap human gap labels.
3. Write two-class labels: human gaps (class 0) + pseudo products (class 1).
4. Merge with the fully labeled seed set into one YOLO root that `train.py`
   consumes unchanged.

Human gap labels are never overwritten. Sidecar
`pseudo_label_meta.json` records per-image pseudo counts for audit / re-run.

### One-shot build (recommended)

```bash
cd train
uv run python merge_datasets.py build \
  --teacher-weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --gap-dataset-dir ../dataset/sku-gap-700img-1 \
  --fully-labeled-dir ../dataset/goods-and-gaps-chinese-2 \
  --pseudo-output-dir ../dataset/sku-gap-700img-1-with-products \
  --merged-output-dir ../dataset/merged-gap-product \
  --conf 0.35 \
  --device 0
```

### Step by step

```bash
# 1) Pseudo-label products onto the gap-only set
uv run python merge_datasets.py pseudo-label \
  --gap-dataset-dir ../dataset/sku-gap-700img-1 \
  --teacher-weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --output-dir ../dataset/sku-gap-700img-1-with-products \
  --conf 0.35

# 2) Merge fully labeled + pseudo-labeled
uv run python merge_datasets.py merge \
  --fully-labeled-dir ../dataset/goods-and-gaps-chinese-2 \
  --pseudo-gap-dir ../dataset/sku-gap-700img-1-with-products \
  --output-dir ../dataset/merged-gap-product
```

Then train with the existing script (no API changes beyond dataset path).
Default `--model` is **`yolo11m.pt`** — recommended for the merged ~800-image set
(dense shelves, small gaps). Omit `--model` to use that default:

```bash
uv run python train.py \
  --dataset-dir ../dataset/merged-gap-product \
  --epochs 100 \
  --imgsz 1024 \
  --batch -1 \
  --balance-gaps \
  --device 0
```

## Model choice

| Model | When to use |
| --- | --- |
| **`yolo11m` (default)** | Merged dataset / production train on a 4060-class GPU |
| `yolo11n` | Smoke tests, CPU, or final edge export after m has been validated |
| `yolo11l` / larger | Only if gap mAP plateaus on m and VRAM allows |

`yolo11n` is too light once product pseudo-labels densify every shelf: it
underfits small gaps and the product/gap boundary. Keep exporting ONNX from
whatever size you train; runtime can still use a distilled nano later.

## Train

```bash
uv run python train.py \
  --dataset-dir ../dataset/merged-gap-product \
  --epochs 100 \
  --imgsz 1024 \
  --batch -1 \
  --cache \
  --device 0
```

(Same as above — defaults to `yolo11m.pt`.)

Artifacts: `artifacts/<dataset-name>/train`  
Prepared detection data: `artifacts/<dataset-name>/_prepared_detection`

Smaller baseline / smoke example:

```bash
uv run python train.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --model yolo11n.pt \
  --epochs 5 \
  --imgsz 640 \
  --batch 8
```

Useful imbalance flags (defaults favor gap recall):

| Flag | Default | Meaning |
| --- | --- | --- |
| `--model` | `yolo11m.pt` | Base checkpoint (see Model choice) |
| `--balance-gaps` / `--no-balance-gaps` | on | Oversample gap images + light copy-paste |
| `--gap-image-oversample N` | 2 (when balanced) | Extra copies of each train image with ≥1 gap |
| `--copy-paste P` | 0.1 (when balanced) | Ultralytics copy-paste probability |
| `--cls G` | 1.0 (when balanced) | Classification loss gain |

## Validate

```bash
uv run python validate.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --data data.yaml \
  --weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --split val
```

## Eval report (mAP + gap recall + conf thresholds)

Ultralytics `val` alone is not enough: overall mAP is dominated by the
abundant `product` class. For restock alerts we care about **gap recall** at
an acceptable precision.

```bash
uv run python eval_report.py \
  --dataset-dir ../dataset/goods-and-gaps-chinese-2 \
  --weights artifacts/goods-and-gaps-chinese-2/train/weights/best.pt \
  --split val \
  --device 0
```

Writes under `runs/eval_report/` (override with `--project` / `--name`):

* `eval_report.md` — human-readable tables
* `eval_report.json` — machine-readable metrics

Contents:

1. **mAP50 / mAP50-95** overall + per-class (from Ultralytics `model.val`)
2. **Gap confidence sweep** — precision / recall / F1 at confs
   `0.05 … 0.60` via IoU matching on gap boxes only
3. **Recommended conf thresholds**
   * `balanced_f1` — max gap F1 (good default)
   * `high_gap_recall` — max recall with precision ≥ floor (default 0.30) —
     prefer for restock / phantom-inventory alerts
   * `high_gap_precision` — max precision with recall ≥ floor (default 0.50) —
     when false gap alerts are costly
4. Class-imbalance guidance block

Suggested runtime defaults for shelf audits: use the report’s
**high_gap_recall** conf for gap alerts, and keep product filtering around
**0.25–0.35**.

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

## Tests

```bash
cd train
uv run pytest
```

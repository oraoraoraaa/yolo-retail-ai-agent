# Automated Inventory & Smart Retail Agent

---

## 1. Project Objectives

The goal of this project is to build an autonomous retail Agent that uses computer vision technology to audit physical shelves in real time. By detecting products, gaps, and misplacements, this Agent eliminates the discrepancy between digital database records and the actual physical reality of the store.

### "Phantom Inventory"

Relying solely on sales data in traditional databases creates three primary blind spots:

* **Product Misplacement:** When customers leave a product on the wrong shelf, that item becomes invisible to other customers who actually want to buy it. The database still lists it as in-stock, but its actual sales drop to zero. The Agent identifies misplaced items and alerts staff to return them to their proper location.
* **Theft and Shrinkage:** Stolen or damaged items bypass the checkout scanner. Because these items remain "in-stock" in the database, automated reorder triggers are never tripped. The Agent detects that the physical shelf is empty, flags the anomaly, and sends a reorder notification.
* **Restocking Delays:** A database might show ample inventory, but the items are actually sitting forgotten in the backroom. The project's frontend can display the empty shelf state; when the Agent detects a gap, it cross-references backroom inventory data and alerts employees to move stock to the sales floor.

---

## 2. AI Agent Workflow

The system operates in a continuous, three-step cycle:

1. **Perception:** An object detection model processes video streams or photos of the shelves to localize products and empty spaces.
2. **Reasoning:** The AI Agent cross-references the visual detections against a real-time database or a digital store planogram.
3. **Action:** The Agent automatically executes appropriate operations, such as generating supplier purchase orders, dispatching notifications to store staff, or dynamically adjusting prices based on supply and demand.

### Robustness in a busy store

The system needs a full view of the shelf to detect gaps — but the busiest
stores (exactly the ones that most need auditing) constantly have customers
walking between the camera and the shelf. A single snapshot of a shopper
standing in front of a facing reads as a `Gap`, and one blocking the lens reads
as zero detections (a false "camera broken" alert). To keep the audit
trustworthy without a person-detection model, perception and reasoning are
hardened with three cooperating layers:

1. **Temporal clean plate.** Each audit captures a short burst of frames and
   detects on their per-pixel median. Anyone who moves is a minority across the
   window, so the composite resolves to the shelf behind them.
2. **Occlusion gating.** A motion mask (frame differencing on the fixed camera)
   flags regions that are still busy. Facings under the mask are marked
   *obscured*, never *empty*, so they cannot open a restock ticket — and a
   view mostly filled by motion is treated as "temporarily blocked," not a
   broken camera.
3. **Temporal debounce.** A finding must persist across several audits inside a
   time window before it opens a ticket. A shopper walking past makes a gap
   that vanishes next audit and is filtered; a genuinely empty shelf persists
   and is ticketed. This trades a little latency for far higher precision.

Implementation and tuning knobs: [`model-local/README.md`](../model-local/README.md)
and [`backend/README.md`](../backend/README.md).

---

## 3. Structure

Due to the vast variety of products, this project inherently faces an extreme many-class classification problem. Training a model to directly distinguish between thousands of specific brands is highly challenging. Instead, this project adopts an efficient, coordinate-based "Gap Detection" approach.

### I. Training a Binary "Gap Detection" Model

Instead of forcing the model to differentiate between hundreds of different brands (e.g., Coke vs. Pepsi), a lightweight object detection architecture like **YOLOv8 / YOLO11** is trained to detect only two states:

1. `Product`
2. `Empty Shelf Space (Gap)`

### II. Establishing a Digital Planogram

A digital map of the store layout (the planogram) is created. This database maps specific physical shelf coordinates directly to the products designated for those slots.

* *Example:* `Coordinates (X: 12, Y: 45) = Brand Y Soda`

```text
+-------------------------------------------------------+
|  Shelf 1  [Product]       [Product]      [Product]    |
+-------------------------------------------------------+
|  Shelf 2  [Product]      ┌───────────┐   [Product]    |
|                          │   GAP     │                |
|                          │ (X, Y)    │ <─── Match with| Planogram!
+--------------------------└───────────┘----------------+
|  Shelf 3  [Product]       [Product]      [Product]    |
+-------------------------------------------------------+
```

### III. Coordinate-Based Logical Reasoning

AI Agent code is implemented to merge the visual model's outputs with the planogram coordinates to infer missing inventory:

1. The computer vision model detects an `Empty Shelf Space (Gap)` at a specific coordinate.
2. The AI Agent queries that exact coordinate within the digital planogram.
3. The Agent deduces: *"There is a gap at coordinates (X:12, Y:45). According to the planogram, Brand Y Soda belongs here. Therefore, Brand Y Soda is currently out of stock."*

## 4. Implementation

### I. Dataset Preparation

#### PLAN A

```text
Step 1: SKU-110K (1000 Images)    Step 2: Local Store (200 Images)     Step 3: Combine & Train
┌──────────────────────────┐      ┌───────────────────────────┐       ┌─────────────────────────┐
│ • Convert products to 0  │  ──> │ • Label products as 0     │  ──>  │ Train a single YOLO     │
│ • LEAVE GAPS UNLABELED   │      │ • Label gaps as 1         │       │ model on all 1,000      │
└──────────────────────────┘      └───────────────────────────┘       └─────────────────────────┘
```

For the 1000 images from SKU-110K, the dataset can be downloaded using this [python script](../dataset/sku-1kimg-yolov8.py).

For the 200 local stores images, use the following workflow:

```text
[ Local 200 Images ] ──> [ Pre-trained YOLOv8 Model ] ──> [ Auto-Generated Product Boxes ]
                                                                     │
[ Final Dataset ] <─── [ Manually Draw Only Gaps (Fast) ] <──────────┘
```

#### PLAN B

Directly use a dataset with gaps labeled. The dataset can be downloaded using this [python script](../dataset/sku-gap-700img-yolov8.py).

#### PLAN B+ (recommended for this repo): gap-only 700 + fully labeled seed

`sku-gap-700img-1` is large (~700 images) but **gap-only**. Training two-class
YOLO on it alone never learns `product`. Use the teacher → pseudo-label → merge
pipeline in [`train/merge_datasets.py`](../train/merge_datasets.py):

1. Teacher: detector trained on `gap-product-chinese-2` (gap + product).
2. Pseudo-label: run teacher on every `sku-gap-700img-1` image; keep high-conf
   product boxes that do not overlap human gaps; keep human gap boxes as-is.
3. Merge into `dataset/merged-gap-product` and train with existing `train.py`.

Class imbalance (gap rare vs product) and the eval report (mAP + gap recall +
recommended conf thresholds) are documented in [`train/README.md`](../train/README.md).

```bash
cd train
uv run python merge_datasets.py build \
  --teacher-weights artifacts/gap-product-chinese-2/train/weights/best.pt \
  --device 0
# default --model is yolo11m.pt (recommended for the enlarged merged set)
uv run python train.py --dataset-dir ../dataset/merged-gap-product --balance-gaps --device 0
uv run python eval_report.py --dataset-dir ../dataset/merged-gap-product \
  --weights artifacts/merged-gap-product/train/weights/best.pt --split val
```

### II. Training, export, and local inference

Train / validate / predict / export scripts live under [`train/`](../train/):

```bash
cd train
uv sync
# default backbone: yolo11m.pt — use --model yolo11n.pt only for smoke/edge trials
uv run python train.py --dataset-dir ../dataset/merged-gap-product --balance-gaps --device 0
uv run python export.py --weights artifacts/<dataset>/train/weights/best.pt --format onnx
```

Exported local weights used by the app are stored under:

```text
train/export/gap-product-chinese-yolo11n.onnx
```

**All runtime vision requests** (camera stream, image audit, agent image analysis)
are processed by [`model-local/`](../model-local) using those local weight files:

```bash
cd model-local
uv sync
uv run stream_server.py   # http://127.0.0.1:8001
```

The backend (`backend/`) never loads the detector itself; it forwards
images to model-local. Roboflow cloud inference is not part of the app path.

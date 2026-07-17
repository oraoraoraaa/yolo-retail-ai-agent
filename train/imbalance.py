"""Class-imbalance helpers for gap vs product shelf detection.

On shelf images, products dominate and gaps are rare. Example from
``gap-product-chinese-2`` (train split, raw labels):

* gap (class 0): ~141 boxes
* product (class 1): ~5856 boxes
* roughly **1 : 40** gap:product

That skew makes a vanilla detector overfit to products and under-recall
gaps — the class the retail agent actually needs for restock / phantom
inventory alerts.

This module documents the levers we expose and computes sampling weights
for optional gap-image oversampling during dataset prep.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from common import IMAGE_SUFFIXES, image_to_label_path


# Canonical class order used across merged datasets and runtime ONNX export.
CANONICAL_NAMES: dict[int, str] = {0: "gap", 1: "product"}
GAP_CLASS_ID = 0
PRODUCT_CLASS_ID = 1


@dataclass(frozen=True)
class ClassCounts:
    """Per-class box counts for one dataset split (or whole dataset)."""

    boxes: dict[int, int]
    images: int
    images_with_gap: int
    images_with_product: int
    empty_label_files: int

    @property
    def total_boxes(self) -> int:
        return sum(self.boxes.values())

    def ratio(self, rare: int = GAP_CLASS_ID, common: int = PRODUCT_CLASS_ID) -> float | None:
        rare_n = self.boxes.get(rare, 0)
        common_n = self.boxes.get(common, 0)
        if rare_n <= 0:
            return None
        return common_n / rare_n


@dataclass(frozen=True)
class ImbalancePolicy:
    """Recommended training / inference knobs for rare-gap detection.

    These are *defaults for documentation and CLI flags*, not hard-coded
    into Ultralytics internals. Prefer measuring with ``eval_report.py``
    after training and adjusting conf thresholds for runtime.
    """

    # Ultralytics ``cls`` loss gain. Raising it pushes the head to care more
    # about class identity; combined with oversampling it helps rare gaps.
    cls_loss_gain: float = 1.0
    # Duplicate each train image that contains ≥1 gap this many extra times
    # in the prepared dataset (0 = no oversampling).
    gap_image_oversample: int = 2
    # Copy-paste augmentation probability (helps paste rare objects).
    copy_paste: float = 0.1
    # Prefer slightly lower train conf only at eval time for gap recall
    # sweeps — runtime still uses the recommended threshold from the report.
    default_runtime_conf: float = 0.25
    # Shelf audits should bias toward gap recall over product precision.
    prefer_gap_recall: bool = True


DEFAULT_IMBALANCE_POLICY = ImbalancePolicy()


def count_label_file(path: Path) -> Counter[int]:
    counts: Counter[int] = Counter()
    if not path.exists():
        return counts
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        class_id = int(float(stripped.split()[0]))
        counts[class_id] += 1
    return counts


def summarize_split(images_dir: Path) -> ClassCounts:
    boxes: Counter[int] = Counter()
    images = 0
    images_with_gap = 0
    images_with_product = 0
    empty_label_files = 0

    if not images_dir.exists():
        return ClassCounts({}, 0, 0, 0, 0)

    for image_path in sorted(
        path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
    ):
        images += 1
        label_path = image_to_label_path(image_path)
        file_counts = count_label_file(label_path)
        if not file_counts:
            empty_label_files += 1
        boxes.update(file_counts)
        if file_counts.get(GAP_CLASS_ID, 0) > 0:
            images_with_gap += 1
        if file_counts.get(PRODUCT_CLASS_ID, 0) > 0:
            images_with_product += 1

    return ClassCounts(
        boxes=dict(boxes),
        images=images,
        images_with_gap=images_with_gap,
        images_with_product=images_with_product,
        empty_label_files=empty_label_files,
    )


def format_class_counts(counts: ClassCounts, names: dict[int, str] | None = None) -> str:
    names = names or CANONICAL_NAMES
    parts = []
    for class_id in sorted(set(counts.boxes) | set(names)):
        label = names.get(class_id, str(class_id))
        parts.append(f"{label}={counts.boxes.get(class_id, 0)}")
    ratio = counts.ratio()
    ratio_txt = f"{ratio:.1f}:1 product:gap" if ratio is not None else "n/a"
    return (
        f"images={counts.images} empty_labels={counts.empty_label_files} "
        f"boxes[{', '.join(parts)}] total={counts.total_boxes} "
        f"images_with_gap={counts.images_with_gap} ratio≈{ratio_txt}"
    )


def images_with_class(images_dir: Path, class_id: int = GAP_CLASS_ID) -> list[Path]:
    hits: list[Path] = []
    if not images_dir.exists():
        return hits
    for image_path in sorted(
        path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
    ):
        counts = count_label_file(image_to_label_path(image_path))
        if counts.get(class_id, 0) > 0:
            hits.append(image_path)
    return hits


def oversample_factor_for_image(label_path: Path, policy: ImbalancePolicy) -> int:
    """Return how many *extra* copies to write (0 means keep single original)."""
    if policy.gap_image_oversample <= 0:
        return 0
    counts = count_label_file(label_path)
    if counts.get(GAP_CLASS_ID, 0) <= 0:
        return 0
    return policy.gap_image_oversample


def remap_class_id(
    source_id: int,
    source_names: dict[int, str],
    target_names: dict[int, str] | None = None,
) -> int | None:
    """Map a source class id into the canonical gap/product scheme.

    Unknown labels (e.g. single-class ``object`` from SKU-110K product crops)
    map to ``product`` when the name is product-like, else ``None`` (drop).
    """
    target_names = target_names or CANONICAL_NAMES
    reverse_target = {name.lower(): idx for idx, name in target_names.items()}
    raw_name = source_names.get(source_id, str(source_id)).strip().lower()

    if raw_name in reverse_target:
        return reverse_target[raw_name]

    product_aliases = {"product", "object", "sku", "item", "goods", "good"}
    gap_aliases = {"gap", "empty", "hole", "oos", "out_of_stock", "space"}
    if raw_name in product_aliases:
        return reverse_target["product"]
    if raw_name in gap_aliases:
        return reverse_target["gap"]
    return None


def imbalance_guidance_markdown(counts: ClassCounts | None = None) -> str:
    """Human-facing guidance block for README / eval reports."""
    observed = ""
    if counts is not None:
        observed = f"\nObserved on the current split: `{format_class_counts(counts)}`.\n"

    policy = DEFAULT_IMBALANCE_POLICY
    return f"""## Class imbalance (gap rare vs product)

Shelf scenes are naturally imbalanced: most facings are products; empty
slots (gaps) are sparse. Training on raw counts without mitigation tends to
produce high product mAP and **low gap recall** — the opposite of what the
audit agent needs.
{observed}
### What we do about it

1. **Canonical two-class scheme** — `0=gap`, `1=product` everywhere (merged
   datasets, eval report, runtime ONNX).
2. **Gap-image oversampling** — train images that contain at least one gap
   are duplicated ``gap_image_oversample`` times (default
   `{policy.gap_image_oversample}`) when preparing the detection dataset so
   the sampler sees empty slots more often.
3. **Loss / aug knobs** — raise Ultralytics ``cls`` loss gain if the head
   collapses to one class; enable light ``copy_paste`` so rare gap crops can
   be pasted onto product-heavy shelves.
4. **Do not fake balance by dropping products** — products are still needed
   so the model learns shelf structure and does not paint every free pixel
   as a gap.
5. **Evaluate gap recall separately** — overall mAP hides rare-class
   failure. Use ``eval_report.py`` for per-class mAP50/mAP50-95, gap
   precision/recall/F1, and recommended confidence thresholds biased toward
   gap recall.
6. **Runtime conf is class-aware in spirit** — keep product conf around
   0.25–0.35; for gap alerts prefer the lower recommended threshold from
   the eval report (often ~0.15–0.25) so empty slots are not missed.

### What not to do

* Do not train on gap-only labels without product negatives/pseudo-labels —
  the model never learns the product class boundary.
* Do not set an extremely high conf (e.g. 0.6+) for shelf audits; that
  kills gap recall on small empty slots.
"""


def iter_named_counts(
    boxes: dict[int, int], names: Iterable[tuple[int, str]] | None = None
) -> list[tuple[str, int]]:
    if names is None:
        names = sorted(CANONICAL_NAMES.items())
    return [(name, int(boxes.get(idx, 0))) for idx, name in names]

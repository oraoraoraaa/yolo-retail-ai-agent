"""Merge YOLO datasets and pseudo-label missing product boxes.

Problem
-------
``goods-and-gaps-chinese-2`` is fully labeled (gap + product) but tiny
(~122 images). ``sku-gap-700img-1`` is ~700 images with **gap-only** labels —
training on it alone teaches the model the gap class but never the product
class, so it cannot draw the product/gap boundary the agent needs.

Approach
--------
1. Train (or reuse) a teacher detector on the fully labeled two-class set.
2. Run the teacher on every ``sku-gap-700img-1`` image and keep high-confidence
   **product** boxes that do not heavily overlap existing human gap labels.
3. Write a new two-class label file per image: human gaps (class 0) +
   pseudo products (class 1).
4. Merge with the fully labeled set into one YOLO root that
   ``train.py`` / ``validate.py`` / ``eval_report.py`` can consume unchanged.

Human gap labels are never overwritten. Pseudo products are marked only in
sidecar metadata so they can be audited / re-run with a better teacher later.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from common import (
    IMAGE_SUFFIXES,
    convert_label_file,
    dump_dataset_yaml,
    ensure_path,
    image_to_label_path,
    link_or_copy,
    load_dataset_yaml,
    normalize_names,
    prepare_detection_dataset,
    resolve_data_yaml,
    resolve_split_images_dir,
    segment_or_box_to_box,
)
from imbalance import (
    CANONICAL_NAMES,
    GAP_CLASS_ID,
    PRODUCT_CLASS_ID,
    ClassCounts,
    format_class_counts,
    remap_class_id,
    summarize_split,
)


SPLITS = ("train", "valid", "test")
SPLIT_KEY_ALIASES = {"train": "train", "val": "valid", "valid": "valid", "test": "test"}


@dataclass
class Box:
    class_id: int
    x: float
    y: float
    w: float
    h: float
    conf: float = 1.0
    source: str = "human"  # human | pseudo

    def as_yolo_line(self) -> str:
        return f"{self.class_id} {self.x:.6f} {self.y:.6f} {self.w:.6f} {self.h:.6f}"

    def xyxy(self) -> tuple[float, float, float, float]:
        x1 = self.x - self.w / 2
        y1 = self.y - self.h / 2
        x2 = self.x + self.w / 2
        y2 = self.y + self.h / 2
        return x1, y1, x2, y2


def parse_yolo_boxes(label_path: Path, source_names: dict[int, str] | None = None) -> list[Box]:
    if not label_path.exists():
        return []
    source_names = source_names or CANONICAL_NAMES
    boxes: list[Box] = []
    for line_number, raw in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) < 5:
            raise ValueError(f"Invalid label row in {label_path}:{line_number}: {raw}")
        source_id = int(float(parts[0]))
        mapped = remap_class_id(source_id, source_names)
        if mapped is None:
            continue
        values = [float(v) for v in parts[1:]]
        x, y, w, h = segment_or_box_to_box(values)
        boxes.append(Box(class_id=mapped, x=x, y=y, w=w, h=h, conf=1.0, source="human"))
    return boxes


def box_iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a.xyxy()
    bx1, by1, bx2, by2 = b.xyxy()
    inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    inter_w, inter_h = max(0.0, inter_x2 - inter_x1), max(0.0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def filter_pseudo_products(
    human_boxes: list[Box],
    product_candidates: list[Box],
    *,
    max_gap_iou: float = 0.3,
    min_conf: float = 0.35,
    min_box_area: float = 1e-4,
) -> list[Box]:
    """Keep product predictions that do not collide with human gaps."""
    gaps = [b for b in human_boxes if b.class_id == GAP_CLASS_ID]
    kept: list[Box] = []
    for cand in product_candidates:
        if cand.class_id != PRODUCT_CLASS_ID:
            continue
        if cand.conf < min_conf:
            continue
        if cand.w * cand.h < min_box_area:
            continue
        if any(box_iou(cand, gap) >= max_gap_iou for gap in gaps):
            continue
        # Suppress near-duplicate product boxes (greedy NMS by conf).
        if any(box_iou(cand, other) >= 0.7 for other in kept):
            continue
        kept.append(
            Box(
                class_id=PRODUCT_CLASS_ID,
                x=cand.x,
                y=cand.y,
                w=cand.w,
                h=cand.h,
                conf=cand.conf,
                source="pseudo",
            )
        )
    return kept


def write_label_file(path: Path, boxes: list[Box]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Stable order: gaps first, then products; human before pseudo within class.
    ordered = sorted(boxes, key=lambda b: (b.class_id, 0 if b.source == "human" else 1, -b.conf))
    body = "\n".join(b.as_yolo_line() for b in ordered)
    path.write_text(body + ("\n" if body else ""), encoding="utf-8")


def copy_split_images_and_labels(
    *,
    source_root: Path,
    source_yaml: Path,
    data: dict[str, Any],
    dest_root: Path,
    prefix: str,
    source_names: dict[int, str],
    remap_only: bool = False,
) -> dict[str, int]:
    """Copy/link one dataset into dest with unique filename prefixes.

    When ``remap_only`` is True, labels are remapped to canonical ids without
    adding pseudo products (used for the fully labeled seed set).
    """
    stats = {split: 0 for split in SPLITS}
    for yaml_key, split_name in (("train", "train"), ("val", "valid"), ("test", "test")):
        if yaml_key not in data and split_name not in data:
            # Roboflow YAMLs use train/val/test; some use valid.
            alt = "valid" if yaml_key == "val" else yaml_key
            if alt not in data:
                continue
            yaml_key = alt
        if yaml_key not in data:
            continue
        images_dir = resolve_split_images_dir(source_root, source_yaml, data[yaml_key])
        out_images = dest_root / split_name / "images"
        out_labels = dest_root / split_name / "labels"
        out_images.mkdir(parents=True, exist_ok=True)
        out_labels.mkdir(parents=True, exist_ok=True)

        for image_path in sorted(
            p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES
        ):
            # Empty prefix keeps the source filename (pseudo-label already unique-names).
            dest_name = f"{prefix}__{image_path.name}" if prefix else image_path.name
            dest_stem = Path(dest_name).stem
            link_or_copy(image_path, out_images / dest_name)
            # Always convert polygons→boxes into a temp then remap ids.
            tmp_label = out_labels / f".tmp_{dest_stem}.txt"
            convert_label_file(image_to_label_path(image_path), tmp_label)
            boxes = parse_yolo_boxes(tmp_label, source_names)
            if remap_only:
                write_label_file(out_labels / f"{dest_stem}.txt", boxes)
            else:
                # Caller will overwrite with pseudo-augmented labels later.
                write_label_file(out_labels / f"{dest_stem}.txt", boxes)
            tmp_label.unlink(missing_ok=True)
            stats[split_name] += 1
    return stats


def predict_products_for_image(
    model: Any,
    image_path: Path,
    *,
    conf: float,
    imgsz: int,
    device: str | None,
    names: dict[int, str],
) -> list[Box]:
    results = model.predict(
        source=str(image_path),
        conf=conf,
        imgsz=imgsz,
        device=device,
        verbose=False,
    )
    if not results:
        return []
    result = results[0]
    boxes_obj = result.boxes
    if boxes_obj is None or len(boxes_obj) == 0:
        return []

    # Model names may be {0:'gap',1:'product'} or list-like.
    model_names = getattr(result, "names", None) or names
    if isinstance(model_names, list):
        model_names = {i: n for i, n in enumerate(model_names)}
    model_names = {int(k): str(v) for k, v in dict(model_names).items()}

    out: list[Box] = []
    xywhn = boxes_obj.xywhn.cpu().numpy()
    confs = boxes_obj.conf.cpu().numpy()
    clss = boxes_obj.cls.cpu().numpy().astype(int)
    for (x, y, w, h), score, cls_id in zip(xywhn, confs, clss, strict=False):
        mapped = remap_class_id(int(cls_id), model_names)
        if mapped != PRODUCT_CLASS_ID:
            continue
        out.append(
            Box(
                class_id=PRODUCT_CLASS_ID,
                x=float(x),
                y=float(y),
                w=float(w),
                h=float(h),
                conf=float(score),
                source="pseudo",
            )
        )
    return out


def pseudo_label_gap_dataset(
    *,
    gap_dataset_dir: Path,
    teacher_weights: Path,
    output_dir: Path,
    conf: float = 0.35,
    max_gap_iou: float = 0.3,
    imgsz: int = 1024,
    device: str | None = None,
    prefix: str = "gap700",
) -> dict[str, Any]:
    gap_yaml = resolve_data_yaml(gap_dataset_dir, Path("data.yaml"))
    gap_data = load_dataset_yaml(gap_yaml)
    gap_names = normalize_names(gap_data.get("names"), gap_data.get("nc"))
    gap_root = gap_yaml.parent.resolve()

    output_dir = Path(output_dir).expanduser().resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "ultralytics is required for pseudo-labeling. Run: cd train && uv sync"
        ) from exc

    model = YOLO(str(ensure_path(teacher_weights)))
    meta: dict[str, Any] = {
        "teacher_weights": str(teacher_weights),
        "gap_dataset": str(gap_dataset_dir),
        "conf": conf,
        "max_gap_iou": max_gap_iou,
        "imgsz": imgsz,
        "images": {},
        "totals": {"human_gaps": 0, "pseudo_products": 0, "images": 0},
    }

    prepared_yaml = {
        "path": str(output_dir),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": 2,
        "names": [CANONICAL_NAMES[0], CANONICAL_NAMES[1]],
    }

    for yaml_key, split_name in (("train", "train"), ("val", "valid"), ("test", "test")):
        if yaml_key not in gap_data:
            # some exports use "valid"
            if split_name == "valid" and "valid" in gap_data:
                yaml_key = "valid"
            else:
                continue
        images_dir = resolve_split_images_dir(gap_root, gap_yaml, gap_data[yaml_key])
        out_images = output_dir / split_name / "images"
        out_labels = output_dir / split_name / "labels"
        out_images.mkdir(parents=True, exist_ok=True)
        out_labels.mkdir(parents=True, exist_ok=True)

        for image_path in sorted(
            p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES
        ):
            dest_name = f"{prefix}__{image_path.name}"
            dest_stem = Path(dest_name).stem
            link_or_copy(image_path, out_images / dest_name)

            human = parse_yolo_boxes(image_to_label_path(image_path), gap_names)
            # Force all human boxes from gap-only set to class gap if source was single-class gap.
            human = [
                Box(
                    class_id=GAP_CLASS_ID if b.class_id == GAP_CLASS_ID else b.class_id,
                    x=b.x,
                    y=b.y,
                    w=b.w,
                    h=b.h,
                    conf=1.0,
                    source="human",
                )
                for b in human
                if b.class_id == GAP_CLASS_ID
            ]

            candidates = predict_products_for_image(
                model,
                image_path,
                conf=conf,
                imgsz=imgsz,
                device=device,
                names=CANONICAL_NAMES,
            )
            products = filter_pseudo_products(
                human, candidates, max_gap_iou=max_gap_iou, min_conf=conf
            )
            merged = human + products
            write_label_file(out_labels / f"{dest_stem}.txt", merged)

            meta["images"][f"{split_name}/{dest_name}"] = {
                "human_gaps": len(human),
                "pseudo_products": len(products),
                "product_conf_mean": (
                    sum(p.conf for p in products) / len(products) if products else 0.0
                ),
            }
            meta["totals"]["human_gaps"] += len(human)
            meta["totals"]["pseudo_products"] += len(products)
            meta["totals"]["images"] += 1

    dump_dataset_yaml(prepared_yaml, output_dir / "data.yaml")
    (output_dir / "pseudo_label_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return meta


def merge_datasets(
    *,
    fully_labeled_dir: Path,
    pseudo_gap_dir: Path,
    output_dir: Path,
    full_prefix: str = "gag",
    gap_prefix: str = "",
) -> dict[str, Any]:
    """Merge a fully labeled two-class set with a pseudo-labeled gap set.

    ``gap_prefix`` defaults to empty because ``pseudo_label_gap_dataset`` already
    writes uniquely prefixed filenames (``gap700__…``). Passing ``gap700`` again
    would create ``gap700__gap700__…`` stems.
    """
    full_yaml = resolve_data_yaml(fully_labeled_dir, Path("data.yaml"))
    full_data = load_dataset_yaml(full_yaml)
    full_names = normalize_names(full_data.get("names"), full_data.get("nc"))
    full_root = full_yaml.parent.resolve()

    pseudo_yaml = resolve_data_yaml(pseudo_gap_dir, Path("data.yaml"))
    pseudo_data = load_dataset_yaml(pseudo_yaml)
    pseudo_root = pseudo_yaml.parent.resolve()

    output_dir = Path(output_dir).expanduser().resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stats_full = copy_split_images_and_labels(
        source_root=full_root,
        source_yaml=full_yaml,
        data=full_data,
        dest_root=output_dir,
        prefix=full_prefix,
        source_names=full_names,
        remap_only=True,
    )
    # Pseudo set is already canonical; just re-prefix into merge root.
    stats_gap = copy_split_images_and_labels(
        source_root=pseudo_root,
        source_yaml=pseudo_yaml,
        data=pseudo_data,
        dest_root=output_dir,
        prefix=gap_prefix,
        source_names=CANONICAL_NAMES,
        remap_only=True,
    )

    merged_yaml = {
        "path": str(output_dir),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": 2,
        "names": [CANONICAL_NAMES[0], CANONICAL_NAMES[1]],
        "sources": {
            "fully_labeled": str(fully_labeled_dir),
            "pseudo_gap": str(pseudo_gap_dir),
        },
    }
    dump_dataset_yaml(merged_yaml, output_dir / "data.yaml")

    summary: dict[str, Any] = {"full_counts": {}, "gap_counts": {}, "merged_counts": {}}
    for split in SPLITS:
        split_images = output_dir / split / "images"
        summary["merged_counts"][split] = format_class_counts(summarize_split(split_images))
    summary["copied"] = {"fully_labeled": stats_full, "pseudo_gap": stats_gap}
    (output_dir / "merge_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pseudo-label products on gap-only shelves and/or merge with the "
            "fully labeled goods-and-gaps set for two-class YOLO training."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_pseudo = sub.add_parser(
        "pseudo-label",
        help="Add product boxes to a gap-only dataset using a teacher model.",
    )
    p_pseudo.add_argument(
        "--gap-dataset-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "dataset" / "sku-gap-700img-1",
        help="Root of the gap-only YOLO dataset.",
    )
    p_pseudo.add_argument(
        "--teacher-weights",
        type=Path,
        required=True,
        help="Two-class detector weights (gap+product), e.g. best.pt from goods-and-gaps.",
    )
    p_pseudo.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "dataset"
        / "sku-gap-700img-1-with-products",
        help="Where to write the two-class pseudo-labeled dataset.",
    )
    p_pseudo.add_argument("--conf", type=float, default=0.35, help="Min product confidence.")
    p_pseudo.add_argument(
        "--max-gap-iou",
        type=float,
        default=0.3,
        help="Drop product boxes that overlap a human gap above this IoU.",
    )
    p_pseudo.add_argument("--imgsz", type=int, default=1024)
    p_pseudo.add_argument("--device", default=None)
    p_pseudo.add_argument("--prefix", default="gap700")

    p_merge = sub.add_parser(
        "merge",
        help="Merge fully labeled + pseudo-labeled gap datasets into one YOLO root.",
    )
    p_merge.add_argument(
        "--fully-labeled-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "dataset"
        / "goods-and-gaps-chinese-2",
    )
    p_merge.add_argument(
        "--pseudo-gap-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "dataset"
        / "sku-gap-700img-1-with-products",
    )
    p_merge.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "dataset" / "merged-gap-product",
    )
    p_merge.add_argument("--full-prefix", default="gag")
    p_merge.add_argument(
        "--gap-prefix",
        default="",
        help=(
            "Filename prefix for the pseudo-gap set. Default empty: "
            "pseudo-label already writes unique gap700__* names; re-prefixing "
            "would produce gap700__gap700__* stems."
        ),
    )

    p_all = sub.add_parser(
        "build",
        help="Pseudo-label then merge in one shot (recommended).",
    )
    p_all.add_argument(
        "--gap-dataset-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "dataset" / "sku-gap-700img-1",
    )
    p_all.add_argument(
        "--fully-labeled-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "dataset"
        / "goods-and-gaps-chinese-2",
    )
    p_all.add_argument(
        "--teacher-weights",
        type=Path,
        required=True,
        help="Two-class teacher weights for product pseudo-labels.",
    )
    p_all.add_argument(
        "--pseudo-output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "dataset"
        / "sku-gap-700img-1-with-products",
    )
    p_all.add_argument(
        "--merged-output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "dataset" / "merged-gap-product",
    )
    p_all.add_argument("--conf", type=float, default=0.35)
    p_all.add_argument("--max-gap-iou", type=float, default=0.3)
    p_all.add_argument("--imgsz", type=int, default=1024)
    p_all.add_argument("--device", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "pseudo-label":
        meta = pseudo_label_gap_dataset(
            gap_dataset_dir=args.gap_dataset_dir,
            teacher_weights=args.teacher_weights,
            output_dir=args.output_dir,
            conf=args.conf,
            max_gap_iou=args.max_gap_iou,
            imgsz=args.imgsz,
            device=args.device,
            prefix=args.prefix,
        )
        print(json.dumps(meta["totals"], indent=2))
        print(f"Pseudo-labeled dataset: {args.output_dir}")
        print(f"Metadata: {Path(args.output_dir) / 'pseudo_label_meta.json'}")
        return

    if args.command == "merge":
        summary = merge_datasets(
            fully_labeled_dir=args.fully_labeled_dir,
            pseudo_gap_dir=args.pseudo_gap_dir,
            output_dir=args.output_dir,
            full_prefix=args.full_prefix,
            gap_prefix=args.gap_prefix,
        )
        print(json.dumps(summary, indent=2))
        print(f"Merged dataset: {args.output_dir}")
        return

    if args.command == "build":
        meta = pseudo_label_gap_dataset(
            gap_dataset_dir=args.gap_dataset_dir,
            teacher_weights=args.teacher_weights,
            output_dir=args.pseudo_output_dir,
            conf=args.conf,
            max_gap_iou=args.max_gap_iou,
            imgsz=args.imgsz,
            device=args.device,
        )
        print("Pseudo-label totals:", json.dumps(meta["totals"]))
        summary = merge_datasets(
            fully_labeled_dir=args.fully_labeled_dir,
            pseudo_gap_dir=args.pseudo_output_dir,
            output_dir=args.merged_output_dir,
        )
        print("Merged summary:", json.dumps(summary, indent=2))
        print()
        print("Next — train on the merged set with existing scripts:")
        print(
            "  # default --model is yolo11m.pt (recommended for ~800-image merged set)"
        )
        print(
            "  uv run python train.py "
            f"--dataset-dir {args.merged_output_dir} "
            "--epochs 100 --imgsz 1024 --batch -1 --balance-gaps --device 0"
        )
        print(
            "  uv run python eval_report.py "
            f"--dataset-dir {args.merged_output_dir} "
            "--weights artifacts/merged-gap-product/train/weights/best.pt --split val"
        )
        return

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()

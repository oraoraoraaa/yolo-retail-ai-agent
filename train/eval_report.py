"""Simple evaluation report: mAP, gap recall, recommended conf thresholds.

Writes a Markdown + JSON report under the run directory so shelf-gap
deployments can pick a confidence threshold without re-reading Ultralytics
plots by hand.

Why a dedicated report?
-----------------------
Overall mAP is dominated by the abundant ``product`` class. For restock
alerts we care about **gap recall** at an acceptable precision. This script:

1. Runs ``model.val`` for standard mAP50 / mAP50-95 (overall + per-class).
2. Sweeps confidence thresholds on the same split and scores gap boxes with
   a simple IoU matcher.
3. Recommends:
   * a **balanced** conf (max gap F1)
   * a **high-recall** conf (max recall with precision ≥ floor)
   * a **high-precision** conf (max precision with recall ≥ floor)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from common import (
    DEFAULT_DATASET_DIR,
    DEFAULT_RUNS_DIR,
    ensure_path,
    image_to_label_path,
    load_dataset_yaml,
    normalize_names,
    prepare_detection_dataset,
    resolve_data_yaml,
    resolve_split_images_dir,
    IMAGE_SUFFIXES,
)
from imbalance import (
    CANONICAL_NAMES,
    GAP_CLASS_ID,
    PRODUCT_CLASS_ID,
    format_class_counts,
    imbalance_guidance_markdown,
    summarize_split,
)


@dataclass
class ThresholdScore:
    conf: float
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


@dataclass
class BoxXYXY:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float = 1.0

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


def yolo_to_xyxy(x: float, y: float, w: float, h: float, width: int, height: int) -> BoxXYXY:
    bw, bh = w * width, h * height
    cx, cy = x * width, y * height
    return BoxXYXY(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)


def iou(a: BoxXYXY, b: BoxXYXY) -> float:
    x1, y1 = max(a.x1, b.x1), max(a.y1, b.y1)
    x2, y2 = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def load_gap_gt(label_path: Path, width: int, height: int, gap_id: int = GAP_CLASS_ID) -> list[BoxXYXY]:
    if not label_path.exists():
        return []
    boxes: list[BoxXYXY] = []
    for raw in label_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        parts = stripped.split()
        class_id = int(float(parts[0]))
        if class_id != gap_id:
            continue
        # prepared labels are always xywh; tolerate polygons via first 4 after class? no — use bbox of poly if needed
        values = [float(v) for v in parts[1:]]
        if len(values) == 4:
            x, y, w, h = values
        else:
            xs, ys = values[0::2], values[1::2]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            x = (x_min + x_max) / 2
            y = (y_min + y_max) / 2
            w = x_max - x_min
            h = y_max - y_min
        boxes.append(yolo_to_xyxy(x, y, w, h, width, height))
    return boxes


def match_gaps(
    gt: list[BoxXYXY],
    pred: list[BoxXYXY],
    iou_thresh: float = 0.5,
) -> tuple[int, int, int]:
    """Greedy conf-descending matching. Returns tp, fp, fn."""
    if not pred and not gt:
        return 0, 0, 0
    if not pred:
        return 0, 0, len(gt)
    if not gt:
        return 0, len(pred), 0

    remaining = set(range(len(gt)))
    tp = 0
    ordered = sorted(pred, key=lambda b: b.conf, reverse=True)
    for p in ordered:
        best_j = None
        best_iou = iou_thresh
        for j in remaining:
            score = iou(p, gt[j])
            if score >= best_iou:
                best_iou = score
                best_j = j
        if best_j is not None:
            tp += 1
            remaining.remove(best_j)
    fp = len(pred) - tp
    fn = len(remaining)
    return tp, fp, fn


def score_threshold(tp: int, fp: int, fn: int, conf: float) -> ThresholdScore:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return ThresholdScore(conf, tp, fp, fn, precision, recall, f1)


def recommend_thresholds(
    scores: list[ThresholdScore],
    *,
    min_precision_for_recall: float = 0.30,
    min_recall_for_precision: float = 0.50,
) -> dict[str, Any]:
    if not scores:
        return {}
    balanced = max(scores, key=lambda s: (s.f1, s.recall, -s.conf))
    high_recall_candidates = [s for s in scores if s.precision >= min_precision_for_recall]
    high_recall = (
        max(high_recall_candidates, key=lambda s: (s.recall, s.f1, -s.conf))
        if high_recall_candidates
        else max(scores, key=lambda s: (s.recall, s.f1, -s.conf))
    )
    high_precision_candidates = [s for s in scores if s.recall >= min_recall_for_precision]
    high_precision = (
        max(high_precision_candidates, key=lambda s: (s.precision, s.f1, -s.conf))
        if high_precision_candidates
        else max(scores, key=lambda s: (s.precision, s.f1, -s.conf))
    )
    return {
        "balanced_f1": asdict(balanced),
        "high_gap_recall": asdict(high_recall),
        "high_gap_precision": asdict(high_precision),
        "notes": {
            "balanced_f1": "Max gap F1 — good default for model-local conf.",
            "high_gap_recall": (
                f"Max gap recall among thresholds with precision ≥ {min_precision_for_recall:.2f}. "
                "Prefer for restock / phantom-inventory alerts."
            ),
            "high_gap_precision": (
                f"Max gap precision among thresholds with recall ≥ {min_recall_for_precision:.2f}. "
                "Prefer when false gap alerts are costly."
            ),
        },
    }


def extract_map_metrics(metrics: Any, names: dict[int, str]) -> dict[str, Any]:
    """Best-effort extraction of Ultralytics DetMetrics fields."""
    out: dict[str, Any] = {"overall": {}, "per_class": {}}

    # box.map / map50 / mp / mr are common attributes on metrics.box
    box = getattr(metrics, "box", metrics)
    for key, attr in (
        ("mAP50-95", "map"),
        ("mAP50", "map50"),
        ("mAP75", "map75"),
        ("precision", "mp"),
        ("recall", "mr"),
    ):
        value = getattr(box, attr, None)
        if value is not None:
            try:
                out["overall"][key] = float(value)
            except (TypeError, ValueError):
                out["overall"][key] = value

    # Per-class maps
    maps = getattr(box, "maps", None)
    ap_class_index = getattr(box, "ap_class_index", None)
    if maps is not None:
        try:
            maps_list = list(maps)
        except TypeError:
            maps_list = []
        if ap_class_index is not None:
            try:
                indices = list(ap_class_index)
            except TypeError:
                indices = list(range(len(maps_list)))
        else:
            indices = list(range(len(maps_list)))
        for idx, class_id in enumerate(indices):
            if idx >= len(maps_list):
                break
            class_id_int = int(class_id)
            name = names.get(class_id_int, str(class_id_int))
            out["per_class"][name] = {"mAP50-95": float(maps_list[idx])}

    # class_result(i) -> (p, r, ap50, ap)
    class_result = getattr(box, "class_result", None)
    if callable(class_result) and ap_class_index is not None:
        try:
            indices = list(ap_class_index)
        except TypeError:
            indices = []
        for i, class_id in enumerate(indices):
            try:
                p, r, ap50, ap = class_result(i)
            except Exception:
                continue
            name = names.get(int(class_id), str(class_id))
            entry = out["per_class"].setdefault(name, {})
            entry.update(
                {
                    "precision": float(p),
                    "recall": float(r),
                    "mAP50": float(ap50),
                    "mAP50-95": float(ap),
                }
            )
    return out


def sweep_gap_thresholds(
    model: Any,
    images: list[Path],
    *,
    gap_id: int,
    confs: list[float],
    imgsz: int,
    device: str | None,
    iou_match: float,
    max_det: int,
) -> list[ThresholdScore]:
    # Aggregate TP/FP/FN across images per conf threshold.
    totals = {c: {"tp": 0, "fp": 0, "fn": 0} for c in confs}

    # Run once at the lowest conf, then filter — much faster than N val passes.
    min_conf = min(confs) if confs else 0.05
    for image_path in images:
        results = model.predict(
            source=str(image_path),
            conf=min_conf,
            imgsz=imgsz,
            device=device,
            max_det=max_det,
            verbose=False,
        )
        if not results:
            continue
        result = results[0]
        height, width = result.orig_shape
        gt = load_gap_gt(image_to_label_path(image_path), width, height, gap_id=gap_id)

        pred_all: list[BoxXYXY] = []
        boxes = result.boxes
        if boxes is not None and len(boxes) > 0:
            xyxy = boxes.xyxy.cpu().numpy()
            conf_arr = boxes.conf.cpu().numpy()
            cls_arr = boxes.cls.cpu().numpy().astype(int)
            # Map model class names → gap id if needed
            model_names = result.names or {}
            if isinstance(model_names, list):
                model_names = {i: n for i, n in enumerate(model_names)}
            reverse = {str(v).lower(): int(k) for k, v in dict(model_names).items()}
            model_gap_id = reverse.get("gap", gap_id)
            for (x1, y1, x2, y2), score, cls_id in zip(xyxy, conf_arr, cls_arr, strict=False):
                if int(cls_id) != model_gap_id:
                    continue
                pred_all.append(BoxXYXY(float(x1), float(y1), float(x2), float(y2), float(score)))

        for conf in confs:
            preds = [b for b in pred_all if b.conf >= conf]
            tp, fp, fn = match_gaps(gt, preds, iou_thresh=iou_match)
            totals[conf]["tp"] += tp
            totals[conf]["fp"] += fp
            totals[conf]["fn"] += fn

    return [
        score_threshold(totals[c]["tp"], totals[c]["fp"], totals[c]["fn"], c) for c in confs
    ]


def render_markdown(report: dict[str, Any]) -> str:
    overall = report.get("map", {}).get("overall", {})
    per_class = report.get("map", {}).get("per_class", {})
    rec = report.get("recommended_conf", {})
    lines = [
        "# Gap detection evaluation report",
        "",
        f"- Weights: `{report.get('weights')}`",
        f"- Dataset: `{report.get('dataset_dir')}`",
        f"- Split: `{report.get('split')}`",
        f"- Images evaluated: **{report.get('num_images')}**",
        f"- Class counts: `{report.get('class_counts')}`",
        "",
        "## mAP (Ultralytics val)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for key in ("mAP50", "mAP50-95", "mAP75", "precision", "recall"):
        if key in overall:
            lines.append(f"| {key} | {overall[key]:.4f} |")
    lines += ["", "### Per-class", "", "| Class | precision | recall | mAP50 | mAP50-95 |", "| --- | --- | --- | --- | --- |"]
    for name, stats in per_class.items():
        lines.append(
            "| {name} | {p} | {r} | {m50} | {m} |".format(
                name=name,
                p=f"{stats.get('precision', float('nan')):.4f}" if "precision" in stats else "—",
                r=f"{stats.get('recall', float('nan')):.4f}" if "recall" in stats else "—",
                m50=f"{stats.get('mAP50', float('nan')):.4f}" if "mAP50" in stats else "—",
                m=f"{stats.get('mAP50-95', float('nan')):.4f}" if "mAP50-95" in stats else "—",
            )
        )

    lines += ["", "## Gap confidence sweep", "", "| conf | precision | recall | F1 | TP | FP | FN |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in report.get("gap_threshold_curve", []):
        lines.append(
            f"| {row['conf']:.2f} | {row['precision']:.3f} | {row['recall']:.3f} | "
            f"{row['f1']:.3f} | {row['tp']} | {row['fp']} | {row['fn']} |"
        )

    lines += ["", "## Recommended confidence thresholds (gap class)", ""]
    if rec:
        for key in ("balanced_f1", "high_gap_recall", "high_gap_precision"):
            item = rec.get(key) or {}
            note = (rec.get("notes") or {}).get(key, "")
            if not item:
                continue
            lines.append(
                f"- **{key}**: conf=`{item['conf']:.2f}` "
                f"(P={item['precision']:.3f}, R={item['recall']:.3f}, F1={item['f1']:.3f})  "
                f"— {note}"
            )
        lines.append("")
        lines.append(
            "Suggested runtime defaults for shelf audits: use "
            f"**high_gap_recall conf={rec.get('high_gap_recall', {}).get('conf', 0.2):.2f}** "
            "for gap alerts, and keep product filtering around 0.25–0.35."
        )
    else:
        lines.append("_No gap boxes found on this split; cannot recommend thresholds._")

    lines += ["", imbalance_guidance_markdown()]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a simple mAP + gap-recall evaluation report with conf recommendations."
    )
    parser.add_argument("--weights", type=Path, required=True, help="Trained weights (.pt or .onnx).")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--data", type=Path, default=Path("data.yaml"))
    parser.add_argument("--split", choices=("val", "test"), default="val")
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--project", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--name", default="eval_report")
    parser.add_argument(
        "--confs",
        default="0.05,0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.50,0.60",
        help="Comma-separated confidence thresholds for the gap sweep.",
    )
    parser.add_argument("--iou-match", type=float, default=0.5, help="IoU for gap TP matching.")
    parser.add_argument("--max-det", type=int, default=300)
    parser.add_argument(
        "--min-precision-for-recall",
        type=float,
        default=0.30,
        help="Precision floor when picking the high-recall conf.",
    )
    parser.add_argument(
        "--min-recall-for-precision",
        type=float,
        default=0.50,
        help="Recall floor when picking the high-precision conf.",
    )
    parser.add_argument(
        "--no-prepare-detection",
        action="store_true",
        help="Use the source dataset YAML directly.",
    )
    parser.add_argument(
        "--skip-val",
        action="store_true",
        help="Skip Ultralytics model.val (only run the gap conf sweep).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    weights = ensure_path(args.weights)
    data_yaml = resolve_data_yaml(args.dataset_dir, args.data)
    project_dir = args.project.expanduser().resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    save_dir = project_dir / args.name
    save_dir.mkdir(parents=True, exist_ok=True)

    validation_data_yaml = (
        data_yaml
        if args.no_prepare_detection
        else prepare_detection_dataset(data_yaml, project_dir / "_prepared_detection")
    )
    data = load_dataset_yaml(validation_data_yaml)
    names = normalize_names(data.get("names"), data.get("nc"))
    # Prefer canonical naming when present.
    if any(str(v).lower() == "gap" for v in names.values()):
        gap_id = next(i for i, n in names.items() if str(n).lower() == "gap")
    else:
        gap_id = GAP_CLASS_ID

    split_key = "val" if args.split == "val" else "test"
    if split_key not in data and args.split == "val" and "valid" in data:
        split_value = data["valid"]
    else:
        split_value = data[split_key]
    dataset_root = Path(data.get("path") or validation_data_yaml.parent).expanduser().resolve()
    images_dir = resolve_split_images_dir(dataset_root, validation_data_yaml, split_value)
    images = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    counts = summarize_split(images_dir)

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "ultralytics is not installed. Install train deps: cd train && uv sync"
        ) from exc

    model = YOLO(str(weights))
    map_section: dict[str, Any] = {"overall": {}, "per_class": {}}
    if not args.skip_val:
        metrics = model.val(
            data=str(validation_data_yaml),
            split=args.split if args.split in data or args.split == "val" else "test",
            imgsz=args.imgsz,
            batch=args.batch,
            device=args.device,
            workers=args.workers,
            project=str(project_dir),
            name=f"{args.name}_ultralytics",
            exist_ok=True,
        )
        map_section = extract_map_metrics(metrics, names)

    confs = [float(x.strip()) for x in args.confs.split(",") if x.strip()]
    curve = sweep_gap_thresholds(
        model,
        images,
        gap_id=gap_id,
        confs=confs,
        imgsz=args.imgsz,
        device=args.device,
        iou_match=args.iou_match,
        max_det=args.max_det,
    )
    recommendations = recommend_thresholds(
        curve,
        min_precision_for_recall=args.min_precision_for_recall,
        min_recall_for_precision=args.min_recall_for_precision,
    )

    report = {
        "weights": str(weights),
        "dataset_dir": str(Path(args.dataset_dir).expanduser().resolve()),
        "data_yaml": str(validation_data_yaml),
        "split": args.split,
        "num_images": len(images),
        "class_counts": format_class_counts(counts, names),
        "names": {int(k): str(v) for k, v in names.items()},
        "gap_class_id": gap_id,
        "map": map_section,
        "gap_threshold_curve": [asdict(s) for s in curve],
        "recommended_conf": recommendations,
        "runtime_suggestion": {
            "gap_alert_conf": (recommendations.get("high_gap_recall") or {}).get("conf", 0.2),
            "balanced_conf": (recommendations.get("balanced_f1") or {}).get("conf", 0.25),
            "product_conf": 0.25,
        },
    }

    json_path = save_dir / "eval_report.json"
    md_path = save_dir / "eval_report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"Evaluation report (JSON): {json_path}")
    print(f"Evaluation report (Markdown): {md_path}")
    if recommendations.get("balanced_f1"):
        bal = recommendations["balanced_f1"]
        hi_r = recommendations["high_gap_recall"]
        print(
            f"Recommended conf — balanced F1: {bal['conf']:.2f} "
            f"(P={bal['precision']:.3f} R={bal['recall']:.3f}); "
            f"high gap recall: {hi_r['conf']:.2f} "
            f"(P={hi_r['precision']:.3f} R={hi_r['recall']:.3f})"
        )
    if map_section.get("overall"):
        overall = map_section["overall"]
        print(
            "mAP50={m50} mAP50-95={m}".format(
                m50=f"{overall.get('mAP50', float('nan')):.4f}",
                m=f"{overall.get('mAP50-95', float('nan')):.4f}",
            )
        )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    DEFAULT_DATASET_DIR,
    DEFAULT_RUNS_DIR,
    ensure_path,
    prepare_detection_dataset,
    resolve_data_yaml,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a trained YOLO detector.")
    parser.add_argument(
        "--weights",
        type=Path,
        required=True,
        help="Path to trained weights, e.g. best.pt.",
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help="Root directory of the YOLO dataset.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("data.yaml"),
        help="Dataset YAML file, relative to --dataset-dir or an absolute path.",
    )
    parser.add_argument(
        "--split",
        choices=("val", "test"),
        default="val",
        help="Dataset split to evaluate.",
    )
    parser.add_argument("--imgsz", type=int, default=1024, help="Validation image size.")
    parser.add_argument("--batch", type=int, default=16, help="Validation batch size.")
    parser.add_argument(
        "--device", default=None, help="Validation device, e.g. cpu, 0, 0,1."
    )
    parser.add_argument(
        "--workers", type=int, default=8, help="Number of dataloader workers."
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="Directory where validation runs are stored.",
    )
    parser.add_argument("--name", default="val", help="Validation run name.")
    parser.add_argument(
        "--no-prepare-detection",
        action="store_true",
        help="Use the source dataset YAML directly instead of prepared detection labels.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    weights = ensure_path(args.weights)
    data_yaml = resolve_data_yaml(args.dataset_dir, args.data)
    project_dir = args.project.expanduser().resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    validation_data_yaml = (
        data_yaml
        if args.no_prepare_detection
        else prepare_detection_dataset(data_yaml, project_dir / "_prepared_detection")
    )

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise SystemExit(
            "ultralytics is not installed. Install the model requirements before validation."
        ) from exc

    model = YOLO(str(weights))
    metrics = model.val(
        data=str(validation_data_yaml),
        split=args.split,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=str(project_dir),
        name=args.name,
        exist_ok=True,
    )

    save_dir = Path(getattr(metrics, "save_dir", project_dir / args.name))
    print(f"Validation artifacts saved to: {save_dir}")


if __name__ == "__main__":
    main()

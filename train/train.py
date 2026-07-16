from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    DEFAULT_DATASET_DIR,
    DEFAULT_WEIGHTS,
    prepare_detection_dataset,
    resolve_data_yaml,
    resolve_project_dir,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a YOLO detector.")
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
    parser.add_argument("--model", default=DEFAULT_WEIGHTS, help="Base YOLO checkpoint to fine-tune.")
    parser.add_argument(
        "--epochs", type=int, default=100, help="Number of training epochs."
    )
    parser.add_argument("--imgsz", type=int, default=1024, help="Training image size.")
    parser.add_argument(
        "--batch",
        type=int,
        default=-1,
        help="Training batch size. Use -1 for Ultralytics automatic batch sizing.",
    )
    parser.add_argument(
        "--device", default=None, help="Training device, e.g. cpu, 0, 0,1."
    )
    parser.add_argument(
        "--workers", type=int, default=8, help="Number of dataloader workers."
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Directory where training runs are stored. Defaults to artifacts/<dataset-name>.",
    )
    parser.add_argument("--name", default="train", help="Training run name.")
    parser.add_argument(
        "--patience", type=int, default=50, help="Early stopping patience."
    )
    parser.add_argument("--seed", type=int, default=0, help="Random seed.")
    parser.add_argument(
        "--cache", action="store_true", help="Cache images in memory during training."
    )
    parser.add_argument(
        "--no-prepare-detection",
        action="store_true",
        help=(
            "Use the source dataset YAML directly instead of preparing a derived "
            "detection dataset with polygon labels converted to boxes."
        ),
    )
    parser.add_argument(
        "--optimizer",
        default="auto",
        help="Optimizer passed to Ultralytics, e.g. auto, SGD, AdamW.",
    )
    parser.add_argument(
        "--cos-lr",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use cosine learning-rate scheduling.",
    )
    parser.add_argument(
        "--close-mosaic",
        type=int,
        default=20,
        help="Disable mosaic augmentation for the final N epochs.",
    )
    parser.add_argument("--mosaic", type=float, default=1.0, help="Mosaic augmentation probability.")
    parser.add_argument(
        "--scale",
        type=float,
        default=0.5,
        help="Random image scale augmentation gain.",
    )
    parser.add_argument(
        "--degrees",
        type=float,
        default=3.0,
        help="Small rotation augmentation in degrees.",
    )
    parser.add_argument(
        "--translate",
        type=float,
        default=0.1,
        help="Random translation augmentation fraction.",
    )
    parser.add_argument(
        "--fliplr",
        type=float,
        default=0.5,
        help="Horizontal flip augmentation probability.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the last checkpoint in the run directory.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    data_yaml = resolve_data_yaml(args.dataset_dir, args.data)
    project_dir = resolve_project_dir(args.dataset_dir, args.project)
    project_dir.mkdir(parents=True, exist_ok=True)
    training_data_yaml = (
        data_yaml
        if args.no_prepare_detection
        else prepare_detection_dataset(data_yaml, project_dir / "_prepared_detection")
    )

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise SystemExit(
            "ultralytics is not installed. Install the model requirements before training."
        ) from exc

    model = YOLO(args.model)
    results = model.train(
        data=str(training_data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=str(project_dir),
        name=args.name,
        patience=args.patience,
        seed=args.seed,
        cache=args.cache,
        optimizer=args.optimizer,
        cos_lr=args.cos_lr,
        close_mosaic=args.close_mosaic,
        mosaic=args.mosaic,
        scale=args.scale,
        degrees=args.degrees,
        translate=args.translate,
        fliplr=args.fliplr,
        resume=args.resume,
    )

    save_dir = Path(getattr(results, "save_dir", project_dir / args.name))
    print(f"Training complete. Artifacts saved to: {save_dir}")
    print(f"Best weights: {save_dir / 'weights' / 'best.pt'}")


if __name__ == "__main__":
    main()

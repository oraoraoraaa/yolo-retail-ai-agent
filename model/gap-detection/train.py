from __future__ import annotations

import argparse
from pathlib import Path

from common import DEFAULT_DATA_YAML, DEFAULT_RUNS_DIR, DEFAULT_WEIGHTS, ensure_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a YOLOv8 gap detector.")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_YAML,
        help="Path to the YOLO dataset YAML.",
    )
    parser.add_argument(
        "--model", default=DEFAULT_WEIGHTS, help="Base YOLOv8 checkpoint to fine-tune."
    )
    parser.add_argument(
        "--epochs", type=int, default=100, help="Number of training epochs."
    )
    parser.add_argument("--imgsz", type=int, default=640, help="Training image size.")
    parser.add_argument("--batch", type=int, default=16, help="Training batch size.")
    parser.add_argument(
        "--device", default=None, help="Training device, e.g. cpu, 0, 0,1."
    )
    parser.add_argument(
        "--workers", type=int, default=8, help="Number of dataloader workers."
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="Directory where training runs are stored.",
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
        "--resume",
        action="store_true",
        help="Resume from the last checkpoint in the run directory.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    data_yaml = ensure_path(args.data)
    args.project.mkdir(parents=True, exist_ok=True)

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise SystemExit(
            "ultralytics is not installed. Install the model requirements before training."
        ) from exc

    model = YOLO(args.model)
    results = model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=str(args.project),
        name=args.name,
        patience=args.patience,
        seed=args.seed,
        cache=args.cache,
        resume=args.resume,
    )

    save_dir = Path(getattr(results, "save_dir", args.project / args.name))
    print(f"Training complete. Artifacts saved to: {save_dir}")
    print(f"Best weights: {save_dir / 'weights' / 'best.pt'}")


if __name__ == "__main__":
    main()

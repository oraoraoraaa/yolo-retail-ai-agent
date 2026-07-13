from __future__ import annotations

import argparse
from pathlib import Path

from common import DEFAULT_DATA_YAML, DEFAULT_RUNS_DIR, ensure_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a trained YOLOv8 gap detector."
    )
    parser.add_argument(
        "--weights",
        type=Path,
        required=True,
        help="Path to trained weights, e.g. best.pt.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_YAML,
        help="Dataset YAML used during validation.",
    )
    parser.add_argument(
        "--split",
        choices=("val", "test"),
        default="val",
        help="Dataset split to evaluate.",
    )
    parser.add_argument("--imgsz", type=int, default=640, help="Validation image size.")
    parser.add_argument("--batch", type=int, default=16, help="Validation batch size.")
    parser.add_argument(
        "--device", default=None, help="Validation device, e.g. cpu, 0, 0,1."
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="Directory where validation runs are stored.",
    )
    parser.add_argument("--name", default="val", help="Validation run name.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    weights = ensure_path(args.weights)
    data_yaml = ensure_path(args.data)
    args.project.mkdir(parents=True, exist_ok=True)

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise SystemExit(
            "ultralytics is not installed. Install the model requirements before validation."
        ) from exc

    model = YOLO(str(weights))
    metrics = model.val(
        data=str(data_yaml),
        split=args.split,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(args.project),
        name=args.name,
        exist_ok=True,
    )

    save_dir = Path(getattr(metrics, "save_dir", args.project / args.name))
    print(f"Validation artifacts saved to: {save_dir}")


if __name__ == "__main__":
    main()

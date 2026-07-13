from __future__ import annotations

import argparse
from pathlib import Path

from common import DEFAULT_DATA_YAML, DEFAULT_RUNS_DIR, DEFAULT_SOURCE_DIR, ensure_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run gap detection inference with YOLOv8."
    )
    parser.add_argument(
        "--weights",
        type=Path,
        required=True,
        help="Path to trained weights, e.g. best.pt.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Image, directory, or video source.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_YAML,
        help="Dataset YAML for class names.",
    )
    parser.add_argument("--imgsz", type=int, default=640, help="Inference image size.")
    parser.add_argument(
        "--conf", type=float, default=0.25, help="Confidence threshold."
    )
    parser.add_argument("--iou", type=float, default=0.7, help="IoU threshold for NMS.")
    parser.add_argument(
        "--device", default=None, help="Inference device, e.g. cpu, 0, 0,1."
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="Directory where predictions are stored.",
    )
    parser.add_argument("--name", default="predict", help="Prediction run name.")
    parser.add_argument(
        "--save-txt", action="store_true", help="Save detections to text files."
    )
    parser.add_argument(
        "--save-conf",
        action="store_true",
        help="Include confidence scores in saved labels.",
    )
    parser.add_argument(
        "--show", action="store_true", help="Display the results in a window."
    )
    parser.add_argument(
        "--max-det", type=int, default=300, help="Maximum detections per image."
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    weights = ensure_path(args.weights)
    source = ensure_path(args.source) if args.source.exists() else args.source
    args.project.mkdir(parents=True, exist_ok=True)

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise SystemExit(
            "ultralytics is not installed. Install the model requirements before running inference."
        ) from exc

    model = YOLO(str(weights))
    results = model.predict(
        source=str(source),
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        device=args.device,
        project=str(args.project),
        name=args.name,
        exist_ok=True,
        save=True,
        save_txt=args.save_txt,
        save_conf=args.save_conf,
        show=args.show,
        max_det=args.max_det,
    )

    save_dir = Path(results[0].save_dir) if results else args.project / args.name
    print(f"Prediction artifacts saved to: {save_dir}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from pathlib import Path

from common import ensure_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a trained YOLOv8 detector.")
    parser.add_argument(
        "--weights",
        type=Path,
        required=True,
        help="Path to trained weights, e.g. best.pt.",
    )
    parser.add_argument(
        "--format",
        default="onnx",
        choices=("onnx", "torchscript", "openvino", "engine", "coreml", "saved_model"),
        help="Export format.",
    )
    parser.add_argument("--imgsz", type=int, default=640, help="Export image size.")
    parser.add_argument(
        "--device", default=None, help="Export device, e.g. cpu, 0, 0,1."
    )
    parser.add_argument(
        "--half", action="store_true", help="Use half precision where supported."
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    weights = ensure_path(args.weights)

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise SystemExit(
            "ultralytics is not installed. Install the model requirements before exporting."
        ) from exc

    model = YOLO(str(weights))
    export_path = model.export(
        format=args.format, imgsz=args.imgsz, device=args.device, half=args.half
    )
    print(f"Export complete: {export_path}")


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
MODEL_DIR = PACKAGE_DIR.parent
REPO_ROOT = MODEL_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset" / "sku-gap-700img-1"
DEFAULT_DATA_YAML = DATASET_DIR / "data.yaml"
DEFAULT_RUNS_DIR = REPO_ROOT / "artifacts" / "gap-detection"
DEFAULT_WEIGHTS = "yolov8n.pt"
DEFAULT_SOURCE_DIR = DATASET_DIR / "valid" / "images"


def ensure_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Path does not exist: {resolved}")
    return resolved


def ensure_parent_dir(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved

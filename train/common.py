from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_DIR = REPO_ROOT / "dataset"
DEFAULT_WEIGHTS = "yolov8n.pt"


def ensure_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Path does not exist: {resolved}")
    return resolved


def resolve_data_yaml(dataset_dir: str | Path, data_yaml: str | Path) -> Path:
    dataset_root = ensure_path(dataset_dir)
    yaml_path = Path(data_yaml).expanduser()
    if not yaml_path.is_absolute():
        yaml_path = dataset_root / yaml_path
    return ensure_path(yaml_path)


def resolve_project_dir(
    dataset_dir: str | Path, project_dir: str | Path | None = None
) -> Path:
    if project_dir is not None:
        return Path(project_dir).expanduser().resolve()

    dataset_root = ensure_path(dataset_dir)
    return REPO_ROOT / "artifacts" / dataset_root.name


def ensure_parent_dir(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved

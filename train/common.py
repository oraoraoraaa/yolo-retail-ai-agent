from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_DATASET_DIR = REPO_ROOT / "dataset"
DEFAULT_RUNS_DIR = SCRIPT_DIR / "runs"
# Default train backbone for the ~800-image merged gap/product set (and seed set).
# yolo11n is fine for smoke tests / edge export, but underfits dense shelf scenes once
# we scale past the tiny fully-labeled seed. yolo11m fits a 4060 8GB at imgsz=1024
# with batch=-1; step up to yolo11l only if VRAM allows and gap mAP plateaus.
DEFAULT_WEIGHTS = str(SCRIPT_DIR / "yolo11m.pt")
DEFAULT_MODEL_NAME = "yolo11m.pt"
IMAGE_SUFFIXES = {".bmp", ".dng", ".jpeg", ".jpg", ".mpo", ".png", ".tif", ".tiff", ".webp"}


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
    return SCRIPT_DIR / "artifacts" / dataset_root.name


def ensure_parent_dir(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def load_dataset_yaml(data_yaml: str | Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise SystemExit(
            "PyYAML is required to inspect dataset YAML files. It is installed with ultralytics."
        ) from exc

    with Path(data_yaml).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Dataset YAML must contain a mapping: {data_yaml}")
    return data


def dump_dataset_yaml(data: dict[str, Any], output_path: str | Path) -> Path:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise SystemExit(
            "PyYAML is required to write prepared dataset YAML files. It is installed with ultralytics."
        ) from exc

    output = ensure_parent_dir(output_path)
    with output.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False, allow_unicode=True)
    return output


def normalize_names(names: Any, nc: int | None = None) -> dict[int, str]:
    if isinstance(names, dict):
        return {int(k): str(v) for k, v in names.items()}
    if isinstance(names, list):
        return {index: str(name) for index, name in enumerate(names)}
    if nc is None:
        raise ValueError("Dataset YAML must define either names or nc.")
    return {index: str(index) for index in range(nc)}


def resolve_split_images_dir(dataset_root: Path, data_yaml: Path, split_value: Any) -> Path:
    if isinstance(split_value, list):
        raise ValueError("List-style dataset splits are not supported by the local preparer.")

    split_path = Path(str(split_value)).expanduser()
    candidates = []
    if split_path.is_absolute():
        candidates.append(split_path)
    else:
        candidates.extend(
            [
                dataset_root / split_path,
                data_yaml.parent / split_path,
                dataset_root / str(split_path).removeprefix("../"),
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Could not resolve split path {split_value!r}. Checked: {checked}")


def image_to_label_path(image_path: Path) -> Path:
    parts = list(image_path.parts)
    try:
        image_index = len(parts) - 1 - parts[::-1].index("images")
    except ValueError as exc:
        raise ValueError(f"Image path is not inside an images directory: {image_path}") from exc
    parts[image_index] = "labels"
    return Path(*parts).with_suffix(".txt")


def segment_or_box_to_box(values: list[float]) -> tuple[float, float, float, float]:
    if len(values) == 4:
        x, y, w, h = values
        return x, y, w, h
    if len(values) < 6 or len(values) % 2 != 0:
        raise ValueError("YOLO labels must contain xywh boxes or polygon xy pairs.")

    xs = values[0::2]
    ys = values[1::2]
    x_min, x_max = max(0.0, min(xs)), min(1.0, max(xs))
    y_min, y_max = max(0.0, min(ys)), min(1.0, max(ys))
    return (
        (x_min + x_max) / 2,
        (y_min + y_max) / 2,
        max(0.0, x_max - x_min),
        max(0.0, y_max - y_min),
    )


def convert_label_file(source: Path, destination: Path) -> tuple[int, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        destination.write_text("", encoding="utf-8")
        return 0, 0

    lines = []
    converted = 0
    total = 0
    for line_number, raw_line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) < 5:
            raise ValueError(f"Invalid label row in {source}:{line_number}: {raw_line}")
        class_id = int(float(parts[0]))
        values = [float(value) for value in parts[1:]]
        if len(values) != 4:
            converted += 1
        x, y, w, h = segment_or_box_to_box(values)
        lines.append(f"{class_id} {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
        total += 1

    destination.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return total, converted


def link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    try:
        os.symlink(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def prepare_detection_dataset(
    data_yaml: str | Path,
    output_dir: str | Path,
    *,
    gap_image_oversample: int = 0,
) -> Path:
    """Create a YOLO detection dataset with explicit xywh labels.

    Roboflow exports may contain segmentation polygons even when the intended task is
    detection. This prepares a small derived dataset with images linked to the
    originals and labels converted to bounding boxes, leaving the source dataset
    untouched.

    When ``gap_image_oversample`` > 0, train images that contain at least one
    ``gap`` box (class id 0, or any class named ``gap``) are duplicated that many
    extra times so the rare empty-slot class is seen more often. See
    ``imbalance.py`` for the full class-imbalance policy.
    """

    source_yaml = ensure_path(data_yaml)
    dataset_root = source_yaml.parent.resolve()
    prepared_root = Path(output_dir).expanduser().resolve()
    prepared_root.mkdir(parents=True, exist_ok=True)

    data = load_dataset_yaml(source_yaml)
    names = normalize_names(data.get("names"), data.get("nc"))
    gap_ids = {
        index for index, name in names.items() if str(name).strip().lower() == "gap"
    }
    if not gap_ids:
        gap_ids = {0}

    prepared_yaml = {
        "path": str(prepared_root),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": len(names),
        "names": [names[index] for index in sorted(names)],
    }

    total_labels = 0
    converted_labels = 0
    oversampled_images = 0
    for split_key, output_split in (("train", "train"), ("val", "valid"), ("test", "test")):
        if split_key not in data:
            # Roboflow YAMLs sometimes use "valid" instead of "val".
            if split_key == "val" and "valid" in data:
                split_key = "valid"
            else:
                continue
        images_dir = resolve_split_images_dir(dataset_root, source_yaml, data[split_key])
        output_images_dir = prepared_root / output_split / "images"
        output_labels_dir = prepared_root / output_split / "labels"
        output_images_dir.mkdir(parents=True, exist_ok=True)
        output_labels_dir.mkdir(parents=True, exist_ok=True)

        seen_stems: set[str] = set()
        for image_path in sorted(
            path for path in images_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
        ):
            source_label = image_to_label_path(image_path)
            copies = 1
            if output_split == "train" and gap_image_oversample > 0:
                label_text = (
                    source_label.read_text(encoding="utf-8") if source_label.exists() else ""
                )
                has_gap = False
                for raw in label_text.splitlines():
                    stripped = raw.strip()
                    if not stripped:
                        continue
                    if int(float(stripped.split()[0])) in gap_ids:
                        has_gap = True
                        break
                if has_gap:
                    copies = 1 + gap_image_oversample
                    oversampled_images += 1

            for copy_index in range(copies):
                stem = image_path.stem if copy_index == 0 else f"{image_path.stem}__gapx{copy_index}"
                image_name = (
                    image_path.name
                    if copy_index == 0
                    else f"{stem}{image_path.suffix}"
                )
                seen_stems.add(stem)
                link_or_copy(image_path, output_images_dir / image_name)
                label_count, converted_count = convert_label_file(
                    source_label,
                    output_labels_dir / f"{stem}.txt",
                )
                total_labels += label_count
                converted_labels += converted_count

        for stale_label in output_labels_dir.glob("*.txt"):
            if stale_label.stem not in seen_stems:
                stale_label.unlink()

    output_yaml = dump_dataset_yaml(prepared_yaml, prepared_root / "data.yaml")
    extra = ""
    if gap_image_oversample > 0:
        extra = (
            f"; gap-image oversample x{gap_image_oversample} on {oversampled_images} train images"
        )
    print(
        "Prepared detection dataset: "
        f"{output_yaml} ({converted_labels}/{total_labels} polygon labels converted to boxes"
        f"{extra})"
    )
    return output_yaml

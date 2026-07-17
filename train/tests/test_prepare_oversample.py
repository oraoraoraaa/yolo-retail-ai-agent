"""Detection prep + gap oversampling."""

from __future__ import annotations

from pathlib import Path

import yaml

from common import prepare_detection_dataset


def _make_mini_dataset(root: Path) -> Path:
    for split in ("train", "valid", "test"):
        (root / split / "images").mkdir(parents=True)
        (root / split / "labels").mkdir(parents=True)

    # train: one gap image, one product-only image
    (root / "train" / "images" / "gap.jpg").write_bytes(b"fake")
    (root / "train" / "labels" / "gap.txt").write_text(
        "0 0.5 0.5 0.2 0.2\n1 0.2 0.2 0.1 0.1\n", encoding="utf-8"
    )
    (root / "train" / "images" / "prod.jpg").write_bytes(b"fake")
    (root / "train" / "labels" / "prod.txt").write_text(
        "1 0.5 0.5 0.2 0.2\n", encoding="utf-8"
    )
    (root / "valid" / "images" / "v.jpg").write_bytes(b"fake")
    (root / "valid" / "labels" / "v.txt").write_text(
        "0 0.5 0.5 0.1 0.1\n", encoding="utf-8"
    )

    data_yaml = root / "data.yaml"
    data_yaml.write_text(
        yaml.safe_dump(
            {
                "train": "train/images",
                "val": "valid/images",
                "test": "test/images",
                "nc": 2,
                "names": ["gap", "product"],
            }
        ),
        encoding="utf-8",
    )
    return data_yaml


def test_prepare_detection_oversamples_gap_train_images(tmp_path: Path) -> None:
    data_yaml = _make_mini_dataset(tmp_path / "src")
    prepared = prepare_detection_dataset(
        data_yaml,
        tmp_path / "prepared",
        gap_image_oversample=2,
    )
    train_images = Path(prepared).parent / "train" / "images"
    names = sorted(p.name for p in train_images.iterdir())
    # original gap + 2 extras + product-only = 4
    assert "gap.jpg" in names
    assert "gap__gapx1.jpg" in names
    assert "gap__gapx2.jpg" in names
    assert "prod.jpg" in names
    assert len(names) == 4
    # valid is not oversampled
    valid_images = Path(prepared).parent / "valid" / "images"
    assert len(list(valid_images.iterdir())) == 1

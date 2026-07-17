"""Unit tests for class-imbalance helpers (no GPU / no ultralytics train)."""

from __future__ import annotations

from pathlib import Path

from imbalance import (
    CANONICAL_NAMES,
    GAP_CLASS_ID,
    PRODUCT_CLASS_ID,
    ClassCounts,
    ImbalancePolicy,
    format_class_counts,
    imbalance_guidance_markdown,
    oversample_factor_for_image,
    remap_class_id,
    summarize_split,
)


def _write_yolo_split(root: Path, boxes_by_stem: dict[str, list[str]]) -> Path:
    images = root / "images"
    labels = root / "labels"
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    for stem, lines in boxes_by_stem.items():
        # tiny placeholder "image" file (suffix only matters for discovery)
        (images / f"{stem}.jpg").write_bytes(b"")
        (labels / f"{stem}.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )
    return images


def test_summarize_split_counts_and_ratio(tmp_path: Path) -> None:
    images = _write_yolo_split(
        tmp_path / "train",
        {
            "a": ["0 0.1 0.1 0.2 0.2", "1 0.5 0.5 0.1 0.1", "1 0.6 0.6 0.1 0.1"],
            "b": ["1 0.2 0.2 0.1 0.1"],  # product only
            "c": [],  # empty labels
        },
    )
    counts = summarize_split(images)
    assert counts.images == 3
    assert counts.boxes[GAP_CLASS_ID] == 1
    assert counts.boxes[PRODUCT_CLASS_ID] == 3
    assert counts.images_with_gap == 1
    assert counts.images_with_product == 2
    assert counts.empty_label_files == 1
    assert counts.ratio() == 3.0


def test_format_class_counts_includes_ratio() -> None:
    counts = ClassCounts(
        boxes={0: 10, 1: 400},
        images=5,
        images_with_gap=3,
        images_with_product=5,
        empty_label_files=0,
    )
    text = format_class_counts(counts)
    assert "gap=10" in text
    assert "product=400" in text
    assert "40.0:1 product:gap" in text


def test_oversample_factor_only_for_gap_images(tmp_path: Path) -> None:
    labels = tmp_path / "labels"
    labels.mkdir()
    gap_label = labels / "gap.txt"
    prod_label = labels / "prod.txt"
    gap_label.write_text("0 0.1 0.1 0.2 0.2\n", encoding="utf-8")
    prod_label.write_text("1 0.1 0.1 0.2 0.2\n", encoding="utf-8")
    policy = ImbalancePolicy(gap_image_oversample=2)
    assert oversample_factor_for_image(gap_label, policy) == 2
    assert oversample_factor_for_image(prod_label, policy) == 0
    assert oversample_factor_for_image(gap_label, ImbalancePolicy(gap_image_oversample=0)) == 0


def test_remap_class_id_aliases() -> None:
    names = {0: "Empty", 1: "object", 2: "unknown_brand"}
    assert remap_class_id(0, names) == GAP_CLASS_ID
    assert remap_class_id(1, names) == PRODUCT_CLASS_ID
    assert remap_class_id(2, names) is None
    assert remap_class_id(0, {0: "gap"}) == GAP_CLASS_ID
    assert remap_class_id(1, {1: "product"}) == PRODUCT_CLASS_ID


def test_imbalance_guidance_markdown_mentions_canonical_scheme() -> None:
    md = imbalance_guidance_markdown()
    assert "0=gap" in md
    assert "eval_report.py" in md
    assert CANONICAL_NAMES[0] == "gap"

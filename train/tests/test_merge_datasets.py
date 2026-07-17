"""Unit tests for product pseudo-label filtering and label merge helpers."""

from __future__ import annotations

from pathlib import Path

from merge_datasets import Box, filter_pseudo_products, parse_yolo_boxes, write_label_file
from imbalance import GAP_CLASS_ID, PRODUCT_CLASS_ID


def test_filter_pseudo_products_drops_gap_overlap_and_low_conf() -> None:
    human = [Box(class_id=GAP_CLASS_ID, x=0.5, y=0.5, w=0.2, h=0.2, source="human")]
    candidates = [
        Box(class_id=PRODUCT_CLASS_ID, x=0.5, y=0.5, w=0.15, h=0.15, conf=0.9),  # overlaps gap
        Box(class_id=PRODUCT_CLASS_ID, x=0.2, y=0.2, w=0.1, h=0.1, conf=0.2),  # low conf
        Box(class_id=PRODUCT_CLASS_ID, x=0.8, y=0.8, w=0.1, h=0.1, conf=0.8),  # keep
        Box(class_id=GAP_CLASS_ID, x=0.1, y=0.1, w=0.1, h=0.1, conf=0.9),  # wrong class
    ]
    kept = filter_pseudo_products(human, candidates, max_gap_iou=0.3, min_conf=0.35)
    assert len(kept) == 1
    assert kept[0].x == 0.8
    assert kept[0].source == "pseudo"
    assert kept[0].class_id == PRODUCT_CLASS_ID


def test_filter_pseudo_products_nms_duplicates() -> None:
    human: list[Box] = []
    candidates = [
        Box(class_id=PRODUCT_CLASS_ID, x=0.5, y=0.5, w=0.2, h=0.2, conf=0.9),
        Box(class_id=PRODUCT_CLASS_ID, x=0.51, y=0.5, w=0.2, h=0.2, conf=0.8),
    ]
    kept = filter_pseudo_products(human, candidates, min_conf=0.35)
    assert len(kept) == 1
    assert kept[0].conf == 0.9


def test_parse_and_write_roundtrip(tmp_path: Path) -> None:
    label = tmp_path / "a.txt"
    label.write_text(
        "0 0.1 0.2 0.3 0.4\n1 0.5 0.5 0.1 0.1\n",
        encoding="utf-8",
    )
    boxes = parse_yolo_boxes(label, {0: "gap", 1: "product"})
    assert [b.class_id for b in boxes] == [GAP_CLASS_ID, PRODUCT_CLASS_ID]
    out = tmp_path / "out.txt"
    write_label_file(out, boxes)
    text = out.read_text(encoding="utf-8").strip().splitlines()
    assert text[0].startswith("0 ")
    assert text[1].startswith("1 ")


def test_parse_gap_only_single_class_names() -> None:
    label = Path  # silence unused if any
    _ = label
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as td:
        p = Path(td) / "g.txt"
        p.write_text("0 0.4 0.4 0.1 0.1\n", encoding="utf-8")
        boxes = parse_yolo_boxes(p, {0: "gap"})
        assert len(boxes) == 1
        assert boxes[0].class_id == GAP_CLASS_ID

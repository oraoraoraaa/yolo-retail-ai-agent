"""CLI imbalance knob resolution for train.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_train_module():
    path = Path(__file__).resolve().parents[1] / "train.py"
    spec = importlib.util.spec_from_file_location("train_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


train_script = _load_train_module()
build_parser = train_script.build_parser
resolve_imbalance_knobs = train_script.resolve_imbalance_knobs


def test_balance_gaps_defaults() -> None:
    args = build_parser().parse_args([])
    knobs = resolve_imbalance_knobs(args)
    assert knobs["gap_image_oversample"] == 2
    assert knobs["copy_paste"] == 0.1
    assert knobs["cls"] == 1.0


def test_no_balance_gaps() -> None:
    args = build_parser().parse_args(["--no-balance-gaps"])
    knobs = resolve_imbalance_knobs(args)
    assert knobs["gap_image_oversample"] == 0
    assert knobs["copy_paste"] == 0.0
    assert knobs["cls"] == 0.5


def test_explicit_overrides() -> None:
    args = build_parser().parse_args(
        ["--balance-gaps", "--gap-image-oversample", "5", "--copy-paste", "0.2", "--cls", "1.5"]
    )
    knobs = resolve_imbalance_knobs(args)
    assert knobs == {"gap_image_oversample": 5, "copy_paste": 0.2, "cls": 1.5}

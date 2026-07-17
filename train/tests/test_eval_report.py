"""Unit tests for gap threshold scoring (no ultralytics needed)."""

from __future__ import annotations

from eval_report import (
    BoxXYXY,
    match_gaps,
    recommend_thresholds,
    score_threshold,
    yolo_to_xyxy,
)


def test_yolo_to_xyxy_center() -> None:
    box = yolo_to_xyxy(0.5, 0.5, 0.2, 0.4, width=100, height=200)
    assert abs(box.x1 - 40.0) < 1e-6
    assert abs(box.y1 - 60.0) < 1e-6
    assert abs(box.x2 - 60.0) < 1e-6
    assert abs(box.y2 - 140.0) < 1e-6


def test_match_gaps_tp_fp_fn() -> None:
    gt = [BoxXYXY(0, 0, 10, 10), BoxXYXY(20, 20, 30, 30)]
    pred = [
        BoxXYXY(1, 1, 9, 9, conf=0.9),  # matches first
        BoxXYXY(100, 100, 110, 110, conf=0.8),  # fp
    ]
    tp, fp, fn = match_gaps(gt, pred, iou_thresh=0.5)
    assert tp == 1
    assert fp == 1
    assert fn == 1


def test_match_gaps_empty() -> None:
    assert match_gaps([], []) == (0, 0, 0)
    assert match_gaps([BoxXYXY(0, 0, 1, 1)], []) == (0, 0, 1)
    assert match_gaps([], [BoxXYXY(0, 0, 1, 1, conf=0.5)]) == (0, 1, 0)


def test_score_threshold_and_recommendations() -> None:
    scores = [
        score_threshold(tp=8, fp=2, fn=2, conf=0.2),  # P=0.8 R=0.8 F1=0.8
        score_threshold(tp=9, fp=6, fn=1, conf=0.1),  # high recall, lower P
        score_threshold(tp=5, fp=0, fn=5, conf=0.5),  # high precision
    ]
    rec = recommend_thresholds(
        scores,
        min_precision_for_recall=0.3,
        min_recall_for_precision=0.5,
    )
    assert rec["balanced_f1"]["conf"] == 0.2
    assert rec["high_gap_recall"]["conf"] == 0.1
    assert rec["high_gap_precision"]["conf"] == 0.5

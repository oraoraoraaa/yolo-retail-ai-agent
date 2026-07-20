"""Tests for temporal anti-occlusion helpers (no camera hardware required)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Allow importing detection.py without installing the package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import detection  # noqa: E402


def _solid(height: int, width: int, color: int) -> np.ndarray:
    return np.full((height, width, 3), color, dtype=np.uint8)


def test_median_clean_plate_single_frame_returns_input() -> None:
    frame = _solid(10, 10, 100)
    out = detection.median_clean_plate([frame])
    assert out is frame


def test_median_clean_plate_requires_a_frame() -> None:
    with pytest.raises(ValueError):
        detection.median_clean_plate([])
    with pytest.raises(ValueError):
        detection.median_clean_plate([None])


def test_median_clean_plate_removes_transient_occluder() -> None:
    """A shelf (value 200) is briefly occluded by a dark blob in a minority of
    frames. The per-pixel median should resolve back to the shelf."""
    shelf = _solid(20, 20, 200)
    frames = [shelf.copy() for _ in range(5)]
    # One frame has a dark occluder covering the top-left quadrant.
    occluded = shelf.copy()
    occluded[0:10, 0:10] = 0
    frames[2] = occluded

    plate = detection.median_clean_plate(frames)
    # Majority (4/5) frames show the shelf, so median removes the occluder.
    assert int(plate[5, 5, 0]) == 200
    assert plate.shape == shelf.shape


def test_motion_occlusion_mask_flags_moving_region() -> None:
    """A blob that moves across frames is flagged by the motion mask; a static
    background is not."""
    base = _solid(40, 40, 180)
    frames = [base.copy() for _ in range(4)]
    # Put a dark blob in a different corner each frame (clear motion).
    frames[0][0:15, 0:15] = 0
    frames[2][25:40, 25:40] = 0

    mask, coverage = detection.motion_occlusion_mask(frames)
    assert mask.shape == base.shape[:2]
    assert coverage > 0.0
    # Some moved pixels are flagged.
    assert int(np.count_nonzero(mask)) > 0


def test_motion_occlusion_mask_static_scene_low_coverage() -> None:
    base = _solid(30, 30, 120)
    frames = [base.copy() for _ in range(4)]
    mask, coverage = detection.motion_occlusion_mask(frames)
    assert coverage == 0.0
    assert int(np.count_nonzero(mask)) == 0


def test_motion_occlusion_mask_single_frame_is_empty() -> None:
    mask, coverage = detection.motion_occlusion_mask([_solid(10, 10, 50)])
    assert coverage == 0.0
    assert mask.shape == (10, 10)


def test_occlusion_regions_returns_normalized_boxes() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[10:60, 20:70] = 255  # a big blob (25% of frame)
    regions = detection.occlusion_regions(mask, min_area_frac=0.01)
    assert regions
    region = regions[0]
    assert 0.0 <= region["x1"] < region["x2"] <= 1.0
    assert 0.0 <= region["y1"] < region["y2"] <= 1.0


def test_occlusion_regions_ignores_speckle() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[0:2, 0:2] = 255  # tiny 4-pixel blob, below min area
    regions = detection.occlusion_regions(mask, min_area_frac=0.01)
    assert regions == []


def test_detection_obscured_true_when_box_over_mask() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[0:50, 0:50] = 255
    box = {"x1": 5, "y1": 5, "x2": 45, "y2": 45}
    assert detection.detection_obscured(mask, box) is True


def test_detection_obscured_false_when_box_clear() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[0:50, 0:50] = 255
    box = {"x1": 60, "y1": 60, "x2": 90, "y2": 90}
    assert detection.detection_obscured(mask, box) is False


def test_detection_obscured_false_on_empty_mask() -> None:
    assert detection.detection_obscured(None, {"x1": 0, "y1": 0, "x2": 1, "y2": 1}) is False
    empty = np.zeros((0, 0), dtype=np.uint8)
    assert detection.detection_obscured(empty, {"x1": 0, "y1": 0, "x2": 1, "y2": 1}) is False


# --- Long-baseline clean plate (Plan 6) helpers ---------------------------


def test_downscale_frame_reduces_width_preserving_aspect() -> None:
    frame = _solid(200, 400, 100)  # h=200, w=400
    out = detection.downscale_frame(frame, 100)
    assert out.shape[1] == 100  # width capped
    assert out.shape[0] == 50  # aspect ratio preserved (200 * 100/400)


def test_downscale_frame_noop_when_already_small() -> None:
    frame = _solid(50, 80, 100)
    out = detection.downscale_frame(frame, 640)
    assert out is frame  # unchanged when already narrow enough
    assert detection.downscale_frame(frame, 0) is frame  # disabled


def test_unify_frames_brings_mismatched_shapes_together() -> None:
    big = _solid(200, 400, 100)
    small = _solid(50, 100, 120)
    unified = detection.unify_frames([big, small])
    # All frames share one shape → medianable.
    shapes = {f.shape for f in unified}
    assert len(shapes) == 1


def test_long_baseline_median_out_votes_a_lingerer() -> None:
    """A customer lingering over a facing survives a short burst (they're the
    majority of those few close-in-time frames), but a minutes-long baseline of
    the clean shelf out-votes them so the median resolves to the shelf.

    This is the core Plan 6 property: the burst alone would keep the occluder,
    the baseline flips the median back to the shelf.
    """
    shelf = _solid(20, 20, 200)
    # Short burst: 3 frames, all showing the occluder (a lingerer, not moving).
    occluded = shelf.copy()
    occluded[:, :] = 0
    burst = [occluded.copy() for _ in range(3)]
    # Burst-only median keeps the occluder (occluder is the majority).
    burst_only = detection.median_clean_plate(detection.unify_frames(burst))
    assert int(burst_only[10, 10, 0]) == 0

    # Long baseline: many clean-shelf frames from earlier audits.
    baseline = [shelf.copy() for _ in range(9)]
    combined = detection.median_clean_plate(detection.unify_frames(burst + baseline))
    # Now the shelf is the majority → median resolves to the shelf.
    assert int(combined[10, 10, 0]) == 200

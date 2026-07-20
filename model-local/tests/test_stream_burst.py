"""Adaptive burst + long-baseline audit-history tests (no camera / no model).

These cover the vision-side occlusion layers added for the busy-store defect:
- ``capture_burst_adaptive`` escalates the capture window while the scene is
  busy and stops early once it reads clean, bounded by a time / frame budget.
- ``AuditHistoryStore`` retains one downscaled frame per audit per camera and
  ages old frames out.

Both use a fake ``cv2.VideoCapture`` so no hardware or YOLO weights are needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import stream_server  # noqa: E402


def _solid(color: int, h: int = 40, w: int = 40) -> np.ndarray:
    return np.full((h, w, 3), color, dtype=np.uint8)


class _FakeCapture:
    """Yields a scripted list of frames, then reports failure."""

    def __init__(self, frames: list[np.ndarray]) -> None:
        self._frames = frames
        self._i = 0
        self.released = False

    def read(self):
        if self._i >= len(self._frames):
            return False, None
        frame = self._frames[self._i]
        self._i += 1
        return True, frame

    def isOpened(self) -> bool:  # noqa: N802 - cv2 API name
        return True

    def release(self) -> None:
        self.released = True


def _patch_capture(monkeypatch: pytest.MonkeyPatch, frames: list[np.ndarray]) -> _FakeCapture:
    cap = _FakeCapture(frames)
    monkeypatch.setattr(stream_server, "open_video_capture", lambda ref: cap)
    # Make the burst run instantly.
    monkeypatch.setattr(stream_server.time, "sleep", lambda *_: None)
    return cap


def test_adaptive_burst_stops_early_on_clean_scene(monkeypatch: pytest.MonkeyPatch) -> None:
    """A static (clean) scene has ~zero motion, so escalation never triggers and
    only the initial burst frames are captured."""
    clean = [_solid(200) for _ in range(7)]
    _patch_capture(monkeypatch, clean + [_solid(200) for _ in range(50)])
    frames, escalated = stream_server.capture_burst_adaptive(
        "0", count=7, interval=0.0, max_seconds=8.0, escalate_coverage=0.15
    )
    assert len(frames) == 7  # no escalation frames added
    assert escalated is False


def test_adaptive_burst_escalates_while_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scene where a blob keeps moving across frames stays above the escalation
    coverage, so the burst keeps extending until the frame budget is hit."""
    frames_script: list[np.ndarray] = []
    # Build many frames with a blob that jumps around → persistent motion.
    for i in range(60):
        f = _solid(180)
        x = (i * 7) % 30
        f[x : x + 10, x : x + 10] = 0
        frames_script.append(f)
    _patch_capture(monkeypatch, frames_script)
    frames, escalated = stream_server.capture_burst_adaptive(
        "0",
        count=4,
        interval=0.0,
        max_seconds=100.0,  # time not the limiter here
        escalate_coverage=0.001,  # basically "any motion escalates"
        escalate_interval=0.0,
        max_frames=12,
    )
    assert escalated is True
    assert len(frames) == 12  # stopped at the frame budget


def test_adaptive_burst_disabled_returns_fixed_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_capture(monkeypatch, [_solid(100) for _ in range(20)])
    frames, escalated = stream_server.capture_burst_adaptive(
        "0", count=5, interval=0.0, max_seconds=0.0
    )
    assert len(frames) == 5
    assert escalated is False


def test_audit_history_store_records_and_ages(monkeypatch: pytest.MonkeyPatch) -> None:
    store = stream_server.AuditHistoryStore()
    clock = {"t": 1000.0}
    monkeypatch.setattr(stream_server.time, "monotonic", lambda: clock["t"])

    store.record("cam-A", _solid(200, h=100, w=1280))
    # Recorded frame is downscaled to the configured width.
    got = store.get("cam-A", max_age_seconds=180)
    assert len(got) == 1
    assert got[0].shape[1] == stream_server.AUDIT_HISTORY_FRAME_WIDTH

    # A second camera does not bleed into the first.
    store.record("cam-B", _solid(50))
    assert len(store.get("cam-A")) == 1

    # Age the first frame out of the window.
    clock["t"] += 500.0
    store.record("cam-A", _solid(100))
    fresh = store.get("cam-A", max_age_seconds=180)
    assert len(fresh) == 1  # old frame aged out, only the fresh one remains

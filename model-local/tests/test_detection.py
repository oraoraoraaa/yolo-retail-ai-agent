"""Tests for model-local camera backend helpers (no hardware required)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Allow importing detection.py without installing the package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import detection  # noqa: E402


def test_parse_video_reference_int() -> None:
    assert detection.parse_video_reference("0") == 0
    assert detection.parse_video_reference("12") == 12


def test_parse_video_reference_path() -> None:
    assert detection.parse_video_reference("/dev/video0") == "/dev/video0"
    assert detection.parse_video_reference("rtsp://cam/stream") == "rtsp://cam/stream"


def test_camera_backends_include_fallback() -> None:
    backends = detection.camera_backends()
    assert backends, "expected at least CAP_ANY"
    # CAP_ANY must always be present as last-resort fallback
    import cv2

    assert cv2.CAP_ANY in backends


def test_camera_backends_macos_prefers_avfoundation(monkeypatch: pytest.MonkeyPatch) -> None:
    import cv2

    monkeypatch.setattr(detection.sys, "platform", "darwin")
    backends = detection.camera_backends()
    if hasattr(cv2, "CAP_AVFOUNDATION"):
        assert backends[0] == cv2.CAP_AVFOUNDATION
    assert cv2.CAP_ANY in backends
    assert cv2.CAP_V4L2 not in backends or backends[0] != cv2.CAP_V4L2


def test_camera_backends_linux_prefers_v4l2(monkeypatch: pytest.MonkeyPatch) -> None:
    import cv2

    monkeypatch.setattr(detection.sys, "platform", "linux")
    backends = detection.camera_backends()
    if hasattr(cv2, "CAP_V4L2"):
        assert backends[0] == cv2.CAP_V4L2
    assert cv2.CAP_ANY in backends


def test_open_video_capture_tries_multiple_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    import cv2

    monkeypatch.setattr(detection.sys, "platform", "darwin")
    backends = detection.camera_backends()
    calls: list[int] = []

    def fake_capture(index: int, backend: int = 0) -> MagicMock:
        calls.append(backend)
        cap = MagicMock()
        # Fail until the last backend so we exercise the loop.
        cap.isOpened.return_value = backend == backends[-1]
        return cap

    with patch.object(cv2, "VideoCapture", side_effect=fake_capture):
        capture = detection.open_video_capture(0)
        assert capture.isOpened() is True
    assert calls == backends


def test_open_video_capture_raises_when_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    import cv2

    def always_closed(index: int, backend: int = 0) -> MagicMock:
        cap = MagicMock()
        cap.isOpened.return_value = False
        return cap

    with patch.object(cv2, "VideoCapture", side_effect=always_closed):
        with pytest.raises(RuntimeError, match="Could not open camera"):
            detection.open_video_capture(0)


def test_probe_camera_index_true_when_open() -> None:
    import cv2

    def open_ok(index: int, backend: int = 0) -> MagicMock:
        cap = MagicMock()
        cap.isOpened.return_value = True
        return cap

    with patch.object(cv2, "VideoCapture", side_effect=open_ok):
        assert detection.probe_camera_index(0) is True


def test_probe_camera_index_false_when_closed() -> None:
    import cv2

    def always_closed(index: int, backend: int = 0) -> MagicMock:
        cap = MagicMock()
        cap.isOpened.return_value = False
        return cap

    with patch.object(cv2, "VideoCapture", side_effect=always_closed):
        assert detection.probe_camera_index(0) is False


def test_get_detection_names_from_dict() -> None:
    model = MagicMock()
    model.names = {0: "product", 1: "gap"}
    assert detection.get_detection_names(model, None)[1] == "gap"


def test_get_detection_names_from_list() -> None:
    model = MagicMock()
    model.names = ["product", "gap"]
    names = detection.get_detection_names(model, None)
    assert names[0] == "product"
    assert names[1] == "gap"

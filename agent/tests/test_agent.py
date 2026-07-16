"""Agent unit tests (offline LLM + local-vision client)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings, reset_settings
from app.main import app
from app.services.agent import RetailAgent
from app.services.detector import GapDetector, reset_detector
from app.services.store import RecordStore


@pytest.fixture(autouse=True)
def _clean_singletons(monkeypatch: pytest.MonkeyPatch):
    """Isolate each test from process-wide singletons and env state."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL_VISION_BASE_URL", "http://vision.test")
    monkeypatch.setenv(
        "LOCAL_VISION_MODEL",
        "train/export/goods-and-gaps-chinese-2-yolo11n.onnx",
    )
    reset_settings()
    reset_detector()
    # Reset agent + store singletons by clearing module globals.
    import app.services.agent as agent_mod
    import app.services.store as store_mod

    agent_mod._agent = None
    store_mod._store = None
    yield
    reset_settings()
    reset_detector()
    agent_mod._agent = None
    store_mod._store = None


def test_offline_detection_action_english() -> None:
    agent = RetailAgent(Settings(openai_api_key=""))
    assert agent._offline_detection_action(0, 0, "en") == "Check camera and shelf visibility"
    assert agent._offline_detection_action(0, 5, "en") == "No action needed"
    assert agent._offline_detection_action(3, 10, "en") == "Restock 3 gap(s)"


def test_offline_detection_action_chinese() -> None:
    agent = RetailAgent(Settings(openai_api_key=""))
    assert agent._offline_detection_action(0, 0, "zh") == "检查摄像头与货架可见性"
    assert agent._offline_detection_action(0, 5, "zh") == "无需操作"
    assert agent._offline_detection_action(2, 8, "zh") == "补货 2 个空位"


def test_summarize_detection_json_offline() -> None:
    agent = RetailAgent(Settings(openai_api_key=""))
    action, explanation = agent.summarize_detection_json(
        {
            "summary": {"total": 4, "gapCount": 1, "productCount": 3},
            "detections": [{"label": "gap"}, {"label": "product"}],
        },
        planogram_response=None,
        language="en",
    )
    assert action == "Restock 1 gap(s)"
    assert "gap candidate" in explanation.lower()


def test_mock_chat_without_llm() -> None:
    agent = RetailAgent(Settings(openai_api_key=""))
    reply = agent.chat("How many gaps?", history=[], language="en")
    assert "You asked" in reply
    assert "OPENAI_API_KEY" in reply or "not configured" in reply.lower()


def test_gap_detector_unavailable_when_service_down(httpx_mock=None) -> None:
    """When model-local is unreachable, detector returns unavailable (no crash)."""
    settings = Settings(
        openai_api_key="",
        local_vision_base_url="http://127.0.0.1:9",
        local_vision_timeout=0.2,
    )
    detector = GapDetector(settings)
    result = detector.analyze(b"fake-image-bytes")
    assert result.available is False
    assert result.unavailable_reason is not None
    assert "Local vision service is unavailable" in result.unavailable_reason


def test_gap_detector_parses_success_response(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(local_vision_base_url="http://vision.test")
    detector = GapDetector(settings)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "detections": [
                    {"label": "product", "confidence": 0.9},
                    {"label": "gap", "confidence": 0.8},
                ],
                "summary": {"total": 2, "gapCount": 1, "productCount": 1},
            }

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, json: dict[str, Any] | None = None) -> FakeResponse:
            assert url.endswith("/api/v1/detect/image")
            assert json is not None
            assert "imageBase64" in json
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    result = detector.analyze(b"\xff\xd8\xff")  # minimal bytes
    assert result.available is True
    assert result.gap_count == 1
    assert result.product_count == 1
    assert result.vision_model_response is not None


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["visionBackend"] == "model-local"
    assert "localVisionBaseUrl" in body
    assert "weightsPath" in body


def test_analyze_detections_endpoint_offline() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/audit/analyze-detections",
        json={
            "visionModelResponse": {
                "summary": {"total": 3, "gapCount": 2, "productCount": 1},
                "detections": [],
            },
            "planogramResponse": None,
            "language": "en",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["suggestedAction"] == "Restock 2 gap(s)"
    assert "explanation" in body


def test_chat_endpoint_offline() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "Hello agent", "history": [], "language": "en"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "reply" in body
    assert "Hello agent" in body["reply"]


def test_database_records_seeded() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/database/records")
    assert response.status_code == 200
    body = response.json()
    assert len(body["records"]) >= 1


def test_settings_default_weights_path() -> None:
    settings = get_settings()
    path = settings.local_vision_model_path
    assert path.name.endswith(".onnx") or "export" in str(path)
    assert settings.local_vision_base_url.startswith("http")


def test_record_store_query() -> None:
    store = RecordStore()
    store.add("audit", "Test audit", "2 gaps")
    hits = store.query(keyword="gaps")
    assert any("gaps" in r.summary.lower() for r in hits)
    typed = store.query(record_type="audit")
    assert all(r.type == "audit" for r in typed)

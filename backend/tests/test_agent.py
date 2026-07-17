"""Agent unit tests (offline LLM + local-vision client + SQL store + auth)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings, reset_settings
from app.db.session import dispose_engine, init_db
from app.main import app
from app.services.agent import RetailAgent
from app.services.detector import GapDetector, reset_detector
from app.services.store import RecordStore, reset_store


@pytest.fixture(autouse=True)
def _clean_singletons(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolate each test from process-wide singletons and env state."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL_VISION_BASE_URL", "http://vision.test")
    monkeypatch.setenv(
        "LOCAL_VISION_MODEL",
        "train/export/gap-product-chinese-yolo11n.onnx",
    )
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-at-least-32-bytes-long!!")
    data_dir = tmp_path / "data"
    media_dir = data_dir / "media"
    db_path = data_dir / "test.db"
    data_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEDIA_DIR", str(media_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    reset_settings()
    dispose_engine()
    reset_detector()
    reset_store()

    import app.services.agent as agent_mod
    import app.services.planogram_store as planogram_mod
    from app.services.closed_loop import reset_closed_loop_agent
    from app.services.ticket_store import reset_ticket_store

    agent_mod._agent = None
    planogram_mod._store = None
    reset_ticket_store()
    reset_closed_loop_agent()

    init_db()

    yield

    reset_settings()
    dispose_engine()
    reset_detector()
    reset_store()
    agent_mod._agent = None
    planogram_mod._store = None
    reset_ticket_store()
    reset_closed_loop_agent()


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


@pytest.mark.asyncio
async def test_summarize_detection_json_offline() -> None:
    agent = RetailAgent(Settings(openai_api_key=""))
    action, explanation = await agent.summarize_detection_json(
        {
            "summary": {"total": 4, "gapCount": 1, "productCount": 3},
            "detections": [{"label": "gap"}, {"label": "product"}],
        },
        planogram_response=None,
        language="en",
    )
    assert action == "Restock 1 gap(s)"
    assert "gap candidate" in explanation.lower()


@pytest.mark.asyncio
async def test_mock_chat_without_llm() -> None:
    agent = RetailAgent(Settings(openai_api_key=""))
    reply = await agent.chat("How many gaps?", history=[], language="en")
    assert "You asked" in reply
    assert "OPENAI_API_KEY" in reply or "not configured" in reply.lower()


@pytest.mark.asyncio
async def test_gap_detector_unavailable_when_service_down() -> None:
    """When model-local is unreachable, detector returns unavailable (no crash)."""
    settings = Settings(
        openai_api_key="",
        local_vision_base_url="http://127.0.0.1:9",
        local_vision_timeout=0.2,
    )
    detector = GapDetector(settings)
    result = await detector.analyze(b"fake-image-bytes")
    assert result.available is False
    assert result.unavailable_reason is not None
    assert "Local vision service is unavailable" in result.unavailable_reason


@pytest.mark.asyncio
async def test_gap_detector_parses_success_response(monkeypatch: pytest.MonkeyPatch) -> None:
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

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any] | None = None) -> FakeResponse:
            assert url.endswith("/api/v1/detect/image")
            assert json is not None
            assert "imageBase64" in json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    result = await detector.analyze(b"\xff\xd8\xff")  # minimal bytes
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
    assert body["authEnabled"] is False
    assert "databaseUrlScheme" in body


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
            "sourceLabel": "unit-test-shelf.jpg",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["suggestedAction"] == "Restock 2 gap(s)"
    assert "explanation" in body
    assert body["recordId"]

    # Audit should be persisted with detection JSON.
    record = client.get(f"/api/v1/database/records/{body['recordId']}")
    assert record.status_code == 200
    saved = record.json()
    assert saved["type"] == "audit"
    assert saved["detectionJson"] is not None
    assert saved["detectionJson"]["summary"]["gapCount"] == 2


def test_analyze_detections_persists_image() -> None:
    client = TestClient(app)
    # 1x1 PNG
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    response = client.post(
        "/api/v1/audit/analyze-detections",
        json={
            "visionModelResponse": {
                "summary": {"total": 1, "gapCount": 1, "productCount": 0},
                "detections": [{"label": "gap"}],
            },
            "language": "en",
            "imageBase64": f"data:image/png;base64,{tiny_png_b64}",
            "sourceLabel": "tiny.png",
        },
    )
    assert response.status_code == 200
    record_id = response.json()["recordId"]
    saved = client.get(f"/api/v1/database/records/{record_id}").json()
    assert saved["imageRef"]
    assert saved["imageUrl"]
    media = client.get(saved["imageUrl"])
    assert media.status_code == 200
    assert media.content[:8] == b"\x89PNG\r\n\x1a\n"


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


def test_record_store_persists_across_instances() -> None:
    store_a = RecordStore()
    created = store_a.add(
        "audit",
        "Persisted audit",
        "has detection",
        detection_json={"summary": {"gapCount": 4}},
    )
    reset_store()
    store_b = RecordStore()
    again = store_b.get(created.id)
    assert again is not None
    assert again.detection_json is not None
    assert again.detection_json["summary"]["gapCount"] == 4


def test_planogram_seed_and_match() -> None:
    from app.services.planogram_match import match_planogram
    from app.services.planogram_store import PlanogramStore

    store = PlanogramStore()
    planograms = store.list()
    assert len(planograms) >= 1
    active = store.get(store.get_active_id() or "")
    assert active is not None

    result = match_planogram(
        active,
        {
            "image": {"width": 100, "height": 100},
            "detections": [
                {
                    "label": "gap",
                    "confidence": 0.91,
                    "normalizedBox": {"x1": 0.05, "y1": 0.05, "x2": 0.2, "y2": 0.25},
                }
            ],
            "summary": {"total": 1, "gapCount": 1, "productCount": 0},
        },
    )
    assert result.planogram_id == active.id
    assert len(result.gap_matches) == 1
    assert result.gap_matches[0]["slotId"]
    assert result.missing_items
    assert "Brand Y Soda" in result.missing_items[0]["itemName"]


def test_planogram_endpoints() -> None:
    client = TestClient(app)
    listed = client.get("/api/v1/planograms")
    assert listed.status_code == 200
    body = listed.json()
    assert body["planograms"]
    active_id = body["activePlanogramId"]
    assert active_id

    created = client.post(
        "/api/v1/planograms",
        json={
            "name": "Test Bay",
            "description": "unit test",
            "slots": [
                {
                    "id": "slot-test",
                    "x": 0.0,
                    "y": 0.0,
                    "width": 0.4,
                    "height": 0.4,
                    "itemName": "Test SKU",
                    "itemPrice": 1.5,
                    "itemStock": 5,
                    "sku": "T-1",
                    "notes": "",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    assert created.json()["slots"][0]["id"] == "slot-test"

    activated = client.put("/api/v1/planograms/active", json={"planogramId": plan_id})
    assert activated.status_code == 200
    assert activated.json()["activePlanogramId"] == plan_id

    matched = client.post(
        f"/api/v1/planograms/{plan_id}/match",
        json={
            "visionModelResponse": {
                "detections": [
                    {
                        "label": "gap",
                        "confidence": 0.8,
                        "normalizedBox": {"x1": 0.0, "y1": 0.0, "x2": 0.3, "y2": 0.3},
                    }
                ]
            }
        },
    )
    assert matched.status_code == 200
    match_body = matched.json()
    assert match_body["missingItems"]
    assert match_body["missingItems"][0]["itemName"] == "Test SKU"
    assert match_body["missingItems"][0]["slotId"] == "slot-test"

    # Offline path is pure (no await needed) when LLM is disabled.
    offline = RetailAgent(Settings(openai_api_key=""))
    action, explanation = offline._mock_detection_json_reply(
        total=1,
        gaps=1,
        products=0,
        language="en",
        planogram_response=match_body,
    )
    assert "Test SKU" in action or "Restock" in action
    assert "Test Bay" in explanation or "Test SKU" in explanation


def test_chat_multipart_attachment_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Oversized chat image uploads are rejected with 413."""
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "64")
    monkeypatch.setenv("MAX_CHAT_IMAGES", "2")
    reset_settings()
    import app.services.agent as agent_mod

    agent_mod._agent = None

    client = TestClient(app)
    big = b"\xff\xd8\xff" + (b"0" * 200)
    response = client.post(
        "/api/v1/agent/chat",
        data={"message": "describe this", "history": "[]", "language": "en"},
        files=[("images", ("shelf.jpg", big, "image/jpeg"))],
    )
    assert response.status_code == 413


def test_analyze_detections_rejects_huge_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_BASE64_CHARS", "32")
    reset_settings()
    import app.services.agent as agent_mod

    agent_mod._agent = None

    client = TestClient(app)
    response = client.post(
        "/api/v1/audit/analyze-detections",
        json={
            "visionModelResponse": {
                "summary": {"total": 0, "gapCount": 0, "productCount": 0},
                "detections": [],
            },
            "language": "en",
            "imageBase64": "data:image/png;base64," + ("A" * 64),
        },
    )
    assert response.status_code == 413


def test_auth_login_and_protect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When AUTH_ENABLED=true, protected routes require a Bearer token."""
    # Reconfigure settings for this test only.
    data_dir = tmp_path / "auth-data"
    media_dir = data_dir / "media"
    db_path = data_dir / "auth.db"
    data_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET", "auth-test-secret-at-least-32-bytes-long")
    monkeypatch.setenv("AUTH_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_ADMIN_PASSWORD", "secret123")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEDIA_DIR", str(media_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    reset_settings()
    dispose_engine()
    reset_store()
    import app.services.planogram_store as planogram_mod

    planogram_mod._store = None
    init_db()

    client = TestClient(app)
    status = client.get("/api/v1/auth/status")
    assert status.status_code == 200
    assert status.json()["authEnabled"] is True
    assert status.json()["authenticated"] is False

    denied = client.get("/api/v1/database/records")
    assert denied.status_code == 401

    bad = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret123"})
    assert ok.status_code == 200
    token = ok.json()["accessToken"]
    assert token

    allowed = client.get(
        "/api/v1/database/records",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert allowed.status_code == 200
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

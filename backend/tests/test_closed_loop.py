"""Closed-loop agent: tickets, webhooks, detect/decide/dispatch/verify."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.db.session import dispose_engine, init_db
from app.main import app
from app.schemas.tickets import WebhookEndpoint, WebhookProviderConfig, WebhookSettings
from app.services.closed_loop import extract_findings, get_closed_loop_agent, reset_closed_loop_agent
from app.services.ticket_store import get_ticket_store, reset_ticket_store
from app.services.webhooks import (
    build_webhook_body,
    load_webhook_settings,
    resolve_endpoint_for_ticket,
    save_webhook_settings,
)


@pytest.fixture(autouse=True)
def _clean_singletons(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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

    from app.config import reset_settings
    from app.services.detector import reset_detector
    from app.services.store import reset_store

    reset_settings()
    dispose_engine()
    reset_detector()
    reset_store()
    reset_ticket_store()
    reset_closed_loop_agent()

    import app.services.agent as agent_mod
    import app.services.planogram_store as planogram_mod

    agent_mod._agent = None
    planogram_mod._store = None

    init_db()
    yield

    reset_settings()
    dispose_engine()
    reset_detector()
    reset_store()
    reset_ticket_store()
    reset_closed_loop_agent()
    agent_mod._agent = None
    planogram_mod._store = None


def _vision(*, total: int, gaps: int, products: int, detections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if detections is None:
        detections = []
        if total == 0 and gaps == 0 and products == 0:
            detections = []
        else:
            for _ in range(gaps):
                detections.append(
                    {"label": "gap", "normalizedBox": {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.3}}
                )
            for _ in range(products):
                detections.append(
                    {
                        "label": "product",
                        "normalizedBox": {"x1": 0.3, "y1": 0.3, "x2": 0.4, "y2": 0.5},
                    }
                )
    return {
        "summary": {"total": total, "gapCount": gaps, "productCount": products},
        "detections": detections,
    }


def test_extract_findings_camera_issue() -> None:
    findings = extract_findings(_vision(total=0, gaps=0, products=0), None, language="en")
    assert len(findings) == 1
    assert findings[0].issue_type == "camera_issue"
    assert set(findings[0].assignee_roles) == {"floor_staff", "manager"}
    assert findings[0].assignee_role in findings[0].assignee_roles


def test_extract_findings_sku_dedupe_and_dual_tickets() -> None:
    """Same SKU across many facings → one shelf_empty (+ OOS when stock=0)."""
    vision = {
        "summary": {"total": 4, "gapCount": 3, "productCount": 1},
        "detections": [
            {"label": "gap"},
            {"label": "gap"},
            {"label": "gap"},
            {"label": "product"},
        ],
    }
    planogram = {
        "planogramId": "pg-1",
        "planogramName": "Bay A",
        "missingItems": [
            {"slotId": "slot-1", "itemName": "Cola", "sku": "SKU-1", "itemStock": 0},
            {"slotId": "slot-2", "itemName": "Cola", "sku": "SKU-1", "itemStock": 0},
            {"slotId": "slot-3", "itemName": "Cola", "sku": "SKU-1", "itemStock": 0},
        ],
        "matches": [
            {
                "status": "product",
                "slot": {
                    "id": "slot-4",
                    "itemName": "Water",
                    "sku": "SKU-2",
                    "itemStock": 20,
                },
            },
            {
                "status": "product",
                "slot": {
                    "id": "slot-5",
                    "itemName": "Water",
                    "sku": "SKU-2",
                    "itemStock": 15,
                },
            },
        ],
    }
    findings = extract_findings(vision, planogram, language="en")
    by_type = {}
    for finding in findings:
        by_type.setdefault(finding.issue_type, []).append(finding)

    # gap facings with stock 0 → both shelf_empty and out_of_stock, one each for SKU-1
    assert len(by_type.get("shelf_empty", [])) == 1
    assert len(by_type.get("out_of_stock", [])) == 1
    assert by_type["shelf_empty"][0].assignee_role == "floor_staff"
    assert by_type["out_of_stock"][0].assignee_role == "backroom"
    assert by_type["shelf_empty"][0].sku == "SKU-1"
    # different SKU still on shelf with low stock → one low_stock for SKU-2
    assert len(by_type.get("low_stock", [])) == 1
    assert by_type["low_stock"][0].priority == "high"  # stock 15 <= 50
    assert by_type["low_stock"][0].sku == "SKU-2"
    assert "misplaced" not in by_type


def test_extract_findings_out_of_stock_not_misplaced_for_stacks() -> None:
    """Stacked product boxes must not open misplaced tickets (common on shelves)."""
    vision = {
        "summary": {"total": 3, "gapCount": 1, "productCount": 2},
        "detections": [
            {"label": "gap", "normalizedBox": {"x1": 0.0, "y1": 0.0, "x2": 0.2, "y2": 0.2}},
            {"label": "product", "normalizedBox": {"x1": 0.4, "y1": 0.4, "x2": 0.7, "y2": 0.7}},
            {"label": "product", "normalizedBox": {"x1": 0.45, "y1": 0.45, "x2": 0.72, "y2": 0.72}},
        ],
    }
    planogram = {
        "planogramId": "pg-1",
        "planogramName": "Bay A",
        "missingItems": [
            {
                "slotId": "slot-1",
                "itemName": "Cola",
                "sku": "SKU-1",
                "itemStock": 4,
            }
        ],
        "matches": [],
    }
    findings = extract_findings(vision, planogram, language="en")
    issue_types = {f.issue_type for f in findings}
    assert "shelf_empty" in issue_types
    assert "out_of_stock" not in issue_types  # stock 4 > 0
    assert "misplaced" not in issue_types


@pytest.mark.asyncio
async def test_closed_loop_creates_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dispatch(ticket, settings=None, **kwargs):  # type: ignore[no-untyped-def]
        return {"ok": True, "channel": "slack", "ticketId": ticket.id, "skipped": False}

    monkeypatch.setattr("app.services.closed_loop.dispatch_ticket", fake_dispatch)
    monkeypatch.setattr(
        "app.services.closed_loop.dispatch_notification",
        AsyncMock(return_value={"ok": True, "skipped": False}),
    )

    agent = get_closed_loop_agent()
    vision = _vision(total=1, gaps=1, products=0)
    planogram = {
        "planogramId": "pg-1",
        "planogramName": "Bay A",
        "missingItems": [{"slotId": "s1", "itemName": "Water", "sku": "W-1", "itemStock": 2}],
        "matches": [],
    }
    first = await agent.run(vision, planogram, language="en", dispatch=True, dedupe=True)
    assert first.tickets_created
    assert first.dispatched
    assert first.tickets_created[0].status == "dispatched"

    second = await agent.run(vision, planogram, language="en", dispatch=True, dedupe=True)
    assert not second.tickets_created
    assert second.tickets_updated


@pytest.mark.asyncio
async def test_verify_closes_or_escalates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dispatch(ticket, settings=None, **kwargs):  # type: ignore[no-untyped-def]
        return {"ok": True, "channel": "wecom", "ticketId": ticket.id, "skipped": False}

    monkeypatch.setattr("app.services.closed_loop.dispatch_ticket", fake_dispatch)

    store = get_ticket_store()
    ticket = store.create(
        issue_type="out_of_stock",
        priority="high",
        assignee_role="backroom",
        title="Out of stock: Water",
        description="gap",
        sku="W-1",
        slot_id="s1",
        planogram_id="pg-1",
        fingerprint="fp-water",
        status="done",
    )

    agent = get_closed_loop_agent()
    closed = await agent.verify(
        ticket.id,
        {
            "summary": {"total": 1, "gapCount": 0, "productCount": 1},
            "detections": [
                {"label": "product", "normalizedBox": {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2}}
            ],
        },
        {
            "planogramId": "pg-1",
            "missingItems": [],
            "matches": [{"status": "product", "slot": {"id": "s1", "sku": "W-1", "itemStock": 2}}],
        },
        language="en",
    )
    assert closed.verified is True
    assert closed.ticket.status == "verified"

    ticket2 = store.create(
        issue_type="out_of_stock",
        priority="high",
        assignee_role="backroom",
        title="Out of stock: Juice",
        description="gap",
        sku="J-1",
        slot_id="s2",
        planogram_id="pg-1",
        fingerprint="fp-juice",
        status="done",
    )
    still_open = await agent.verify(
        ticket2.id,
        {
            "summary": {"total": 1, "gapCount": 1, "productCount": 0},
            "detections": [
                {"label": "gap", "normalizedBox": {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2}}
            ],
        },
        {
            "planogramId": "pg-1",
            "missingItems": [{"slotId": "s2", "itemName": "Juice", "sku": "J-1", "itemStock": 0}],
            "matches": [],
        },
        language="en",
    )
    assert still_open.verified is False
    assert still_open.escalated is True
    assert still_open.ticket.status == "escalated"
    assert still_open.ticket.assignee_role == "manager"


def test_webhook_payloads_and_settings() -> None:
    settings = WebhookSettings(
        active_channel="generic",
        generic=WebhookProviderConfig(
            enabled=True,
            endpoints=[
                WebhookEndpoint(
                    id="ep-ops",
                    name="ops",
                    url="https://example.test/hook",
                    enabled=True,
                )
            ],
        ),
    )
    saved = save_webhook_settings(settings)
    assert saved.active_channel == "generic"
    loaded = load_webhook_settings()
    assert loaded.generic.endpoints[0].url == "https://example.test/hook"

    ticket = get_ticket_store().create(
        issue_type="camera_issue",
        priority="high",
        assignee_role="manager",
        title="Camera issue",
        description="no detections",
        shelf_label="Bay A",
    )
    slack_body = build_webhook_body("slack", "hello", ticket)
    assert "blocks" in slack_body
    assert any("Bay A" in str(block) for block in slack_body["blocks"])
    wecom_body = build_webhook_body("wecom", "hello", ticket)
    assert wecom_body["msgtype"] == "markdown"
    assert "Bay A" in wecom_body["markdown"]["content"]
    generic_body = build_webhook_body("generic", "hello", ticket)
    assert generic_body["ticket"]["id"] == ticket.id
    assert generic_body["shelfLabel"] == "Bay A"

    # Multi-endpoint routing by role
    multi = WebhookSettings(
        active_channel="slack",
        slack=WebhookProviderConfig(
            enabled=True,
            endpoints=[
                WebhookEndpoint(id="ep-floor", name="floor", url="https://hooks.example/floor", enabled=True),
                WebhookEndpoint(id="ep-mgr", name="manager", url="https://hooks.example/mgr", enabled=True),
            ],
        ),
        role_routes={"manager": "slack:ep-mgr"},
    )
    resolved = resolve_endpoint_for_ticket(multi, ticket)
    assert resolved is not None
    channel, endpoint = resolved
    assert channel == "slack"
    assert endpoint.id == "ep-mgr"
    assert "Sent to role(s)" in str(slack_body) or "Manager" in str(slack_body)


def test_low_stock_severity_bands() -> None:
    def match_with_stock(stock: float) -> dict[str, Any]:
        return {
            "status": "product",
            "slot": {
                "id": f"slot-{stock}",
                "itemName": f"Item {stock}",
                "sku": f"SKU-{stock}",
                "itemStock": stock,
            },
        }

    vision = {
        "summary": {"total": 4, "gapCount": 0, "productCount": 4},
        "detections": [
            {"label": "product", "normalizedBox": {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2}}
        ],
        "annotatedImage": "data:image/jpeg;base64,abc",
    }
    planogram = {
        "planogramId": "pg-1",
        "planogramName": "Aisle 3",
        "missingItems": [],
        "matches": [
            match_with_stock(350),  # ignore
            match_with_stock(250),  # warning only
            match_with_stock(150),  # low ticket
            match_with_stock(80),   # medium ticket
            match_with_stock(20),   # high ticket
        ],
    }
    findings = extract_findings(vision, planogram, language="en")
    by_stock = {
        f.evidence.get("planogramStock"): f
        for f in findings
        if f.evidence.get("planogramStock") is not None
    }
    assert 350 not in by_stock
    assert by_stock[250].notify_only is True
    assert by_stock[250].issue_type == "low_stock_warning"
    assert by_stock[150].notify_only is False and by_stock[150].priority == "low"
    assert by_stock[80].priority == "medium"
    assert by_stock[20].priority == "high"
    assert all(f.shelf_label == "Aisle 3" for f in findings)


def test_ticket_and_closed_loop_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dispatch(ticket, settings=None, **kwargs):  # type: ignore[no-untyped-def]
        return {
            "ok": True,
            "channel": "generic",
            "ticketId": ticket.id,
            "skipped": False,
            "endpointName": "ops",
        }

    monkeypatch.setattr("app.services.closed_loop.dispatch_ticket", fake_dispatch)
    monkeypatch.setattr("app.services.webhooks.dispatch_ticket", fake_dispatch)

    client = TestClient(app)
    run = client.post(
        "/api/v1/agent/closed-loop/run",
        json={
            "visionModelResponse": _vision(total=0, gaps=0, products=0),
            "language": "en",
            "dispatch": True,
            "dedupe": True,
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["ticketsCreated"]
    ticket_id = body["ticketsCreated"][0]["id"]

    listed = client.get("/api/v1/tickets")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    filtered = client.get("/api/v1/tickets", params={"issueType": "camera_issue"})
    assert filtered.status_code == 200
    assert all(t["issueType"] == "camera_issue" for t in filtered.json()["tickets"])

    patched = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "done", "note": "staff fixed camera"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "done"

    verify = client.post(
        f"/api/v1/agent/closed-loop/verify/{ticket_id}",
        json={
            "visionModelResponse": _vision(
                total=2,
                gaps=0,
                products=2,
                detections=[
                    {"label": "product", "normalizedBox": {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2}},
                    {"label": "product", "normalizedBox": {"x1": 0.3, "y1": 0.3, "x2": 0.4, "y2": 0.4}},
                ],
            ),
            "language": "en",
        },
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["verified"] is True

    # Webhook admin endpoints (auth disabled ⇒ anonymous admin)
    settings = client.get("/api/v1/admin/webhooks")
    assert settings.status_code == 200
    payload = settings.json()
    payload["activeChannel"] = "slack"
    payload["slack"] = {
        "enabled": True,
        "endpoints": [
            {
                "id": "ep-ops",
                "name": "ops",
                "url": "https://hooks.example/test",
                "enabled": True,
            }
        ],
    }
    saved = client.put("/api/v1/admin/webhooks", json=payload)
    assert saved.status_code == 200
    assert saved.json()["slack"]["endpoints"][0]["url"] == "https://hooks.example/test"


def test_audit_analyze_detections_returns_ticket_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dispatch(ticket, settings=None, **kwargs):  # type: ignore[no-untyped-def]
        return {"ok": False, "skipped": True, "channel": "slack", "error": "disabled"}

    monkeypatch.setattr("app.services.closed_loop.dispatch_ticket", fake_dispatch)
    monkeypatch.setattr(
        "app.services.closed_loop.dispatch_notification",
        AsyncMock(return_value={"ok": False, "skipped": True}),
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/audit/analyze-detections",
        json={
            "visionModelResponse": _vision(total=0, gaps=0, products=0),
            "language": "en",
            "sourceLabel": "unit-test",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "ticketIds" in body
    assert isinstance(body["ticketIds"], list)
    assert body["ticketIds"]
    assert body.get("closedLoopNarrative")

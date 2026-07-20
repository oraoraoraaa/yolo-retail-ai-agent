"""Closed-loop agent: tickets, webhooks, detect/decide/dispatch/verify."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import dispose_engine, init_db
from app.main import app
from app.schemas.tickets import WebhookEndpoint, WebhookProviderConfig, WebhookSettings
from app.services.closed_loop import extract_findings, get_closed_loop_agent, reset_closed_loop_agent
from app.services.observation_store import get_observation_store, reset_observation_store
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
    # Disable temporal debounce by default so existing finding→ticket tests see
    # a ticket on the first audit. Debounce-specific tests opt back in.
    monkeypatch.setenv("DEBOUNCE_MIN_OBSERVATIONS", "1")
    # Disable the wall-clock persistence gate by default so rapid-fire test
    # audits (milliseconds apart) still confirm. Span-specific tests opt back in.
    monkeypatch.setenv("DEBOUNCE_MIN_SPAN_SECONDS", "0")
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
    reset_observation_store()
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
    reset_observation_store()
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

    # gap facings matched to planogram with stock 0 → ONLY the backroom
    # out_of_stock ticket (no floor_staff shelf_empty), plus a broadcast
    # announcement companion. One ticket per SKU-1.
    assert len(by_type.get("shelf_empty", [])) == 0
    assert len(by_type.get("out_of_stock", [])) == 1
    oos = by_type["out_of_stock"][0]
    assert oos.assignee_role == "backroom"
    assert oos.sku == "SKU-1"
    # The single backroom ticket also broadcasts a store-wide announcement.
    assert oos.announce is True
    assert oos.announce_roles == ["announcement"]
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


@pytest.mark.asyncio
async def test_empty_facing_backroom_only_and_announce_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty stock + planogram match → single backroom ticket + one announcement.

    - Exactly one ticket (out_of_stock, backroom); no floor_staff shelf_empty.
    - A store-wide announcement is broadcast once when the ticket opens.
    - A second identical audit must NOT open a duplicate ticket, and must NOT
      re-announce (announcement fires only on new-ticket creation).
    """
    dispatched_tickets: list[Any] = []
    announcements: list[dict[str, Any]] = []

    async def fake_dispatch(ticket, settings=None, **kwargs):  # type: ignore[no-untyped-def]
        dispatched_tickets.append(ticket)
        return {"ok": True, "channel": "slack", "ticketId": ticket.id, "skipped": False}

    async def fake_notify(**kwargs):  # type: ignore[no-untyped-def]
        announcements.append(kwargs)
        return {"ok": True, "skipped": False, "issueType": kwargs.get("issue_type")}

    monkeypatch.setattr("app.services.closed_loop.dispatch_ticket", fake_dispatch)
    monkeypatch.setattr("app.services.closed_loop.dispatch_notification", fake_notify)

    vision = _vision(total=1, gaps=1, products=0)
    planogram = {
        "planogramId": "pg-9",
        "planogramName": "Bay Z",
        "missingItems": [
            {"slotId": "s1", "itemName": "Cola", "sku": "C-1", "itemStock": 0},
        ],
        "matches": [],
    }

    agent = get_closed_loop_agent()
    first = await agent.run(vision, planogram, language="en", dispatch=True, dedupe=True)

    # Exactly one ticket, backroom, out_of_stock. No floor_staff shelf_empty.
    assert len(first.tickets_created) == 1
    ticket = first.tickets_created[0]
    assert ticket.issue_type == "out_of_stock"
    assert ticket.assignee_role == "backroom"
    assert not any(t.issue_type == "shelf_empty" for t in first.tickets_created)

    # One store-wide announcement broadcast to the announcement channel.
    announce_calls = [
        a for a in announcements if a.get("issue_type") == "shelf_empty_announcement"
    ]
    assert len(announce_calls) == 1
    assert "announcement" in (announce_calls[0].get("assignee_roles") or [])

    # Second identical audit: no duplicate ticket, no second announcement.
    announcements.clear()
    second = await agent.run(vision, planogram, language="en", dispatch=True, dedupe=True)
    assert not second.tickets_created
    assert not any(
        a.get("issue_type") == "shelf_empty_announcement" for a in announcements
    )


def test_extract_findings_out_of_stock_without_gap() -> None:
    """A planogram slot with stock 0 opens a backroom OOS finding even when NO
    gap was detected on the shelf (out-of-stock is planogram ground truth)."""
    # Vision sees only a product (no gap at all).
    vision = _vision(total=1, gaps=0, products=1)
    planogram = {
        "planogramId": "pg-oos",
        "planogramName": "Bay OOS",
        "missingItems": [],  # no gap matched
        "matches": [],
        "outOfStockSlots": [
            {"slotId": "s1", "itemName": "Cola", "sku": "C-1", "itemStock": 0},
        ],
    }
    findings = extract_findings(vision, planogram, language="en")
    oos = [f for f in findings if f.issue_type == "out_of_stock"]
    assert len(oos) == 1
    assert oos[0].assignee_role == "backroom"
    assert oos[0].evidence.get("gapDetected") is False
    assert oos[0].announce is True


def test_out_of_stock_no_gap_dedupes_across_audits() -> None:
    """The same out-of-stock SKU must not open a second ticket on re-audit."""
    vision = _vision(total=1, gaps=0, products=1)
    planogram = {
        "planogramId": "pg-oos2",
        "planogramName": "Bay OOS2",
        "missingItems": [],
        "matches": [],
        "outOfStockSlots": [
            {"slotId": "s1", "itemName": "Juice", "sku": "J-9", "itemStock": 0},
        ],
    }
    first = extract_findings(vision, planogram, language="en")
    second = extract_findings(vision, planogram, language="en")
    # Both audits produce a finding with the SAME fingerprint → ticket dedupe.
    fp_first = next(f.fingerprint for f in first if f.issue_type == "out_of_stock")
    fp_second = next(f.fingerprint for f in second if f.issue_type == "out_of_stock")
    assert fp_first == fp_second


@pytest.mark.asyncio
async def test_out_of_stock_no_gap_single_ticket_and_immediate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OOS without a gap opens exactly one backroom ticket, immediately (bypasses
    debounce), and re-audit does not open a duplicate."""
    # Turn debounce ON to prove OOS bypasses it.
    monkeypatch.setenv("DEBOUNCE_MIN_OBSERVATIONS", "2")
    monkeypatch.setenv("DEBOUNCE_MIN_SPAN_SECONDS", "90")
    from app.config import reset_settings

    reset_settings()
    reset_closed_loop_agent()

    async def fake_dispatch(ticket, settings=None, **kwargs):  # type: ignore[no-untyped-def]
        return {"ok": True, "channel": "slack", "ticketId": ticket.id, "skipped": False}

    async def fake_notify(**kwargs):  # type: ignore[no-untyped-def]
        return {"ok": True, "skipped": False, "issueType": kwargs.get("issue_type")}

    monkeypatch.setattr("app.services.closed_loop.dispatch_ticket", fake_dispatch)
    monkeypatch.setattr("app.services.closed_loop.dispatch_notification", fake_notify)

    vision = _vision(total=2, gaps=0, products=2)
    planogram = {
        "planogramId": "pg-oos3",
        "planogramName": "Bay OOS3",
        "missingItems": [],
        "matches": [],
        "outOfStockSlots": [
            {"slotId": "s1", "itemName": "Milk", "sku": "M-1", "itemStock": 0},
        ],
    }
    agent = get_closed_loop_agent()

    # First audit: OOS opens immediately despite min observations = 2.
    first = await agent.run(
        vision, planogram, language="en", source_label="camera:oos", dispatch=True, dedupe=True
    )
    oos_created = [t for t in first.tickets_created if t.issue_type == "out_of_stock"]
    assert len(oos_created) == 1
    assert oos_created[0].assignee_role == "backroom"

    # Second audit: same SKU still out of stock → no duplicate ticket.
    second = await agent.run(
        vision, planogram, language="en", source_label="camera:oos", dispatch=True, dedupe=True
    )
    assert not any(t.issue_type == "out_of_stock" for t in second.tickets_created)


def test_gap_with_stock_still_floor_staff() -> None:
    """A matched gap whose planogram stock is > 0 stays a floor_staff task."""
    vision = _vision(total=1, gaps=1, products=0)
    planogram = {
        "planogramId": "pg-3",
        "planogramName": "Bay B",
        "missingItems": [
            {"slotId": "s1", "itemName": "Chips", "sku": "CH-1", "itemStock": 12},
        ],
        "matches": [],
    }
    findings = extract_findings(vision, planogram, language="en")
    by_type = {f.issue_type for f in findings}
    assert "shelf_empty" in by_type
    assert "out_of_stock" not in by_type
    shelf = next(f for f in findings if f.issue_type == "shelf_empty")
    assert shelf.assignee_role == "floor_staff"
    assert shelf.announce is False


# ---------------------------------------------------------------------------
# Plan B — occlusion-aware gating
# ---------------------------------------------------------------------------


def test_camera_issue_suppressed_when_view_obstructed() -> None:
    """A customer standing in front of the lens (view obstructed) is not a
    broken camera — no camera_issue finding should fire."""
    vision = _vision(total=0, gaps=0, products=0)
    vision["occlusion"] = {"viewObstructed": True, "coverage": 0.6, "regions": []}
    findings = extract_findings(vision, None, language="en")
    assert not any(f.issue_type == "camera_issue" for f in findings)


def test_camera_issue_still_fires_when_view_clear() -> None:
    """No detections AND a clear view is a genuine camera problem."""
    vision = _vision(total=0, gaps=0, products=0)
    vision["occlusion"] = {"viewObstructed": False, "coverage": 0.0, "regions": []}
    findings = extract_findings(vision, None, language="en")
    assert any(f.issue_type == "camera_issue" for f in findings)


def test_obscured_gap_not_reported_missing() -> None:
    """A gap detection flagged obscured must not become a missing item."""
    from app.schemas.planogram import Planogram, PlanogramSlot
    from app.services.planogram_match import match_planogram

    planogram = Planogram(
        id="pg-occ",
        name="Bay Occ",
        slots=[
            PlanogramSlot(
                id="s1", x=0.05, y=0.05, width=0.2, height=0.3,
                item_name="Water", sku="W-1", item_stock=5,
            ),
        ],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    vision = {
        "image": {"width": 100, "height": 100},
        "detections": [
            {
                "label": "gap",
                "confidence": 0.9,
                "obscured": True,
                "box": {"x1": 5, "y1": 5, "x2": 25, "y2": 35},
                "normalizedBox": {"x1": 0.05, "y1": 0.05, "x2": 0.25, "y2": 0.35},
            }
        ],
    }
    result = match_planogram(planogram, vision)
    assert result.missing_items == []
    assert result.obscured_matches
    assert result.obscured_matches[0]["slotId"] == "s1"


def test_slot_center_in_occlusion_region_marked_obscured() -> None:
    """A slot whose center lies inside a reported occlusion region is obscured
    even when the model produced no detection there (fully covered facing)."""
    from app.schemas.planogram import Planogram, PlanogramSlot
    from app.services.planogram_match import match_planogram

    planogram = Planogram(
        id="pg-cov",
        name="Bay Cover",
        slots=[
            PlanogramSlot(
                id="s1", x=0.4, y=0.4, width=0.2, height=0.2,
                item_name="Juice", sku="J-1", item_stock=3,
            ),
        ],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    vision = {
        "image": {"width": 100, "height": 100},
        "detections": [],
        "occlusion": {
            "viewObstructed": False,
            "coverage": 0.1,
            "regions": [{"x1": 0.35, "y1": 0.35, "x2": 0.65, "y2": 0.65}],
        },
    }
    result = match_planogram(planogram, vision)
    assert result.missing_items == []
    assert any(m["slotId"] == "s1" for m in result.obscured_matches)


# ---------------------------------------------------------------------------
# Plan C — temporal debounce (M-of-K persistence)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debounce_holds_ticket_until_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """With min observations = 2, a single-audit gap is held back; a second
    audit confirms it and opens the ticket."""
    monkeypatch.setenv("DEBOUNCE_MIN_OBSERVATIONS", "2")
    monkeypatch.setenv("DEBOUNCE_WINDOW_SECONDS", "180")
    from app.config import reset_settings

    reset_settings()
    reset_closed_loop_agent()

    async def fake_dispatch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "channel": "slack", "endpointName": "test"}

    monkeypatch.setattr("app.services.closed_loop.dispatch_ticket", fake_dispatch)

    vision = _vision(total=1, gaps=1, products=0)
    planogram = {
        "planogramId": "pg-deb",
        "planogramName": "Bay D",
        "missingItems": [
            {"slotId": "s1", "itemName": "Chips", "sku": "CH-1", "itemStock": 8},
        ],
        "matches": [],
    }

    agent = get_closed_loop_agent()

    # First audit: finding seen once → held back, no ticket.
    first = await agent.run(
        vision, planogram, language="en", source_label="camera:1", dispatch=True, dedupe=True
    )
    assert not first.tickets_created
    assert first.debounced
    assert first.debounced[0]["observations"] == 1
    assert first.debounced[0]["required"] == 2

    # Second audit: confirmed → ticket opens.
    second = await agent.run(
        vision, planogram, language="en", source_label="camera:1", dispatch=True, dedupe=True
    )
    assert len(second.tickets_created) == 1
    assert second.tickets_created[0].issue_type == "shelf_empty"


@pytest.mark.asyncio
async def test_debounce_transient_gap_never_ticketed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gap that appears once then disappears (customer walking past) never
    accumulates enough observations, so no ticket is ever opened."""
    monkeypatch.setenv("DEBOUNCE_MIN_OBSERVATIONS", "2")
    monkeypatch.setenv("DEBOUNCE_WINDOW_SECONDS", "180")
    from app.config import reset_settings

    reset_settings()
    reset_closed_loop_agent()

    gap_vision = _vision(total=1, gaps=1, products=0)
    clear_vision = _vision(total=2, gaps=0, products=2)
    planogram = {
        "planogramId": "pg-trans",
        "planogramName": "Bay T",
        "missingItems": [
            {"slotId": "s1", "itemName": "Soda", "sku": "S-1", "itemStock": 8},
        ],
        "matches": [],
    }
    clear_planogram = {
        "planogramId": "pg-trans",
        "planogramName": "Bay T",
        "missingItems": [],
        "matches": [],
    }

    agent = get_closed_loop_agent()

    first = await agent.run(
        gap_vision, planogram, language="en", source_label="camera:2", dispatch=False, dedupe=True
    )
    assert not first.tickets_created

    # Next audit the gap is gone (person moved on) → no shelf_empty finding.
    second = await agent.run(
        clear_vision, clear_planogram, language="en", source_label="camera:2", dispatch=False, dedupe=True
    )
    assert not second.tickets_created
    assert not any(t.issue_type == "shelf_empty" for t in second.tickets_created)


@pytest.mark.asyncio
async def test_debounce_disabled_opens_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """min observations = 1 (the fixture default) opens on the first audit."""
    from app.config import reset_settings

    reset_settings()
    reset_closed_loop_agent()

    vision = _vision(total=1, gaps=1, products=0)
    planogram = {
        "planogramId": "pg-now",
        "planogramName": "Bay N",
        "missingItems": [
            {"slotId": "s1", "itemName": "Milk", "sku": "M-1", "itemStock": 4},
        ],
        "matches": [],
    }
    agent = get_closed_loop_agent()
    result = await agent.run(
        vision, planogram, language="en", source_label="camera:3", dispatch=False, dedupe=True
    )
    assert len(result.tickets_created) == 1
    assert not result.debounced


def test_observation_store_scopes_by_source() -> None:
    """count_recent scoped by source_key must not sum across cameras."""
    store = get_observation_store()
    store.record("fp-x", "camera_issue", source_key="camera:A")
    store.record("fp-x", "camera_issue", source_key="camera:B")
    assert store.count_recent("fp-x", window_seconds=180, source_key="camera:A") == 1
    assert store.count_recent("fp-x", window_seconds=180, source_key="camera:B") == 1
    # Unscoped spans all sources.
    assert store.count_recent("fp-x", window_seconds=180) == 2


def _backdate_observations(fingerprint: str, seconds_ago: float) -> None:
    """Shift every observation of ``fingerprint`` back in time so a test can
    simulate wall-clock persistence without sleeping."""
    from datetime import timedelta

    from app.db.models import FindingObservationRow
    from app.db.session import get_session
    from app.services.observation_store import _utcnow

    cutoff = _utcnow() - timedelta(seconds=seconds_ago)
    with get_session() as session:
        rows = session.scalars(
            select(FindingObservationRow).where(
                FindingObservationRow.fingerprint == fingerprint
            )
        ).all()
        for row in rows:
            row.observed_at = cutoff


def test_observation_store_span_seconds() -> None:
    """span_seconds reports the wall-clock gap between oldest and newest obs."""
    store = get_observation_store()
    # A single observation has no span.
    store.record("fp-span", "shelf_empty", source_key="camera:S")
    assert store.span_seconds("fp-span", window_seconds=180, source_key="camera:S") == 0.0
    # Backdate the first observation, then record a second → span opens up.
    _backdate_observations("fp-span", 120)
    store.record("fp-span", "shelf_empty", source_key="camera:S")
    span = store.span_seconds("fp-span", window_seconds=180, source_key="camera:S")
    assert span >= 100  # ~120s minus test jitter


@pytest.mark.asyncio
async def test_debounce_span_gate_holds_rapid_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two rapid-fire audits satisfy the observation count but NOT the wall-clock
    span, so the finding is still held (busy-store slow-walker defense)."""
    monkeypatch.setenv("DEBOUNCE_MIN_OBSERVATIONS", "2")
    monkeypatch.setenv("DEBOUNCE_WINDOW_SECONDS", "180")
    monkeypatch.setenv("DEBOUNCE_MIN_SPAN_SECONDS", "90")
    from app.config import reset_settings

    reset_settings()
    reset_closed_loop_agent()

    vision = _vision(total=1, gaps=1, products=0)
    planogram = {
        "planogramId": "pg-span",
        "planogramName": "Bay S",
        "missingItems": [
            {"slotId": "s1", "itemName": "Chips", "sku": "CH-1", "itemStock": 8},
        ],
        "matches": [],
    }
    agent = get_closed_loop_agent()

    first = await agent.run(
        vision, planogram, language="en", source_label="camera:span", dispatch=False, dedupe=True
    )
    assert not first.tickets_created  # count 1/2

    second = await agent.run(
        vision, planogram, language="en", source_label="camera:span", dispatch=False, dedupe=True
    )
    # Count is now satisfied (2/2) but the two audits are milliseconds apart, so
    # the span gate (90s) still holds the ticket back.
    assert not second.tickets_created
    assert second.debounced
    assert second.debounced[0]["observations"] >= 2
    assert second.debounced[0]["requiredSpanSeconds"] == 90


@pytest.mark.asyncio
async def test_debounce_span_gate_confirms_after_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the finding has persisted across the required wall-clock span (and
    met the observation count), the ticket finally opens."""
    monkeypatch.setenv("DEBOUNCE_MIN_OBSERVATIONS", "2")
    monkeypatch.setenv("DEBOUNCE_WINDOW_SECONDS", "600")
    monkeypatch.setenv("DEBOUNCE_MIN_SPAN_SECONDS", "90")
    from app.config import reset_settings

    reset_settings()
    reset_closed_loop_agent()

    vision = _vision(total=1, gaps=1, products=0)
    planogram = {
        "planogramId": "pg-persist",
        "planogramName": "Bay P",
        "missingItems": [
            {"slotId": "s1", "itemName": "Soda", "sku": "S-1", "itemStock": 8},
        ],
        "matches": [],
    }
    agent = get_closed_loop_agent()

    first = await agent.run(
        vision, planogram, language="en", source_label="camera:persist", dispatch=False, dedupe=True
    )
    assert not first.tickets_created

    # Simulate real elapsed time: backdate the recorded observation ~2 minutes.
    fingerprint = first.debounced[0]["fingerprint"]
    _backdate_observations(fingerprint, 120)

    # A later audit still sees the gap → count 2, span ~120s ≥ 90s → ticket opens.
    second = await agent.run(
        vision, planogram, language="en", source_label="camera:persist", dispatch=False, dedupe=True
    )
    assert len(second.tickets_created) == 1
    assert second.tickets_created[0].issue_type == "shelf_empty"

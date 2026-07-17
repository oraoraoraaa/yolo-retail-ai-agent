"""Tests for media cleanup and system backup/restore."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import reset_settings
from app.db.session import dispose_engine, init_db
from app.main import app
from app.schemas.planogram import PlanogramCreate, PlanogramSlot
from app.services.media import media_root, resolve_media_path, save_image_bytes
from app.services.planogram_store import get_planogram_store, reset_planogram_store
from app.services.store import get_store, reset_store
from app.services.ticket_store import reset_ticket_store
from app.services.closed_loop import reset_closed_loop_agent


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    media_dir = data_dir / "media"
    data_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "test.db"

    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-at-least-32-bytes-long!!")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LOCAL_VISION_BASE_URL", "http://vision.test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEDIA_DIR", str(media_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    reset_settings()
    dispose_engine()
    reset_store()
    reset_planogram_store()
    reset_ticket_store()
    reset_closed_loop_agent()
    init_db()
    yield
    dispose_engine()
    reset_settings()
    reset_store()
    reset_planogram_store()
    reset_ticket_store()
    reset_closed_loop_agent()


def test_clear_records_also_clears_audit_media() -> None:
    store = get_store()
    # create an audit with image bytes
    tiny = b"\xff\xd8\xff\xd9"  # minimal jpeg markers
    record = store.add(
        "audit",
        title="Audit with image",
        summary="has media",
        image_bytes=tiny,
        image_mime="image/jpeg",
    )
    assert record.image_ref
    path = resolve_media_path(record.image_ref)
    assert path is not None and path.is_file()

    # orphan file under audits/
    orphan_ref = save_image_bytes("audits", b"orphan", mime="image/jpeg", stem="orphan")
    assert resolve_media_path(orphan_ref) is not None

    deleted, media_deleted = store.clear_all()
    assert deleted >= 1
    assert media_deleted >= 1
    assert resolve_media_path(record.image_ref) is None
    assert resolve_media_path(orphan_ref) is None
    audits_dir = media_root() / "audits"
    assert audits_dir.exists()
    assert list(audits_dir.glob("*")) == []


def test_delete_planogram_removes_image() -> None:
    store = get_planogram_store()
    # tiny png-ish base64
    import base64

    payload = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xd9").decode()
    plan = store.create(
        PlanogramCreate(
            name="Shelf A",
            description="test",
            image_base64=payload,
            image_width=10,
            image_height=10,
            slots=[
                PlanogramSlot(
                    id="slot-1",
                    x=0.1,
                    y=0.1,
                    width=0.2,
                    height=0.2,
                    item_name="Item",
                    item_price=1.0,
                    item_stock=5,
                    sku="SKU-1",
                )
            ],
        )
    )
    assert plan.image_ref
    assert resolve_media_path(plan.image_ref) is not None

    store.delete(plan.id)
    assert store.get(plan.id) is None
    assert resolve_media_path(plan.image_ref) is None


def test_backup_export_and_restore_roundtrip() -> None:
    store = get_store()
    plan_store = get_planogram_store()
    import base64

    # seed data + media
    store.add(
        "audit",
        title="Before backup",
        summary="seed",
        image_bytes=b"\xff\xd8\xff\xd9",
        image_mime="image/jpeg",
    )
    plan = plan_store.create(
        PlanogramCreate(
            name="Bay 1",
            description="",
            image_base64="data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xd9").decode(),
            image_width=8,
            image_height=8,
            slots=[],
        )
    )
    assert plan.image_ref

    client = TestClient(app)
    export = client.get("/api/v1/database/backup")
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("application/zip")
    zip_bytes = export.content
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "data.json" in names
        assert any(n.startswith("media/") for n in names)

    # mutate state
    store.clear_all()
    plan_store.delete(plan.id)
    assert store.query() == [] or all(r.title != "Before backup" for r in store.query())
    assert plan_store.get(plan.id) is None

    # restore
    restore = client.post(
        "/api/v1/database/backup/restore",
        files={"file": ("backup.zip", zip_bytes, "application/zip")},
    )
    assert restore.status_code == 200, restore.text
    body = restore.json()
    assert body["ok"] is True
    assert body["restored"]["records"] >= 1
    assert body["restored"]["planograms"] >= 1

    # stores reinitialized after restore
    reset_store()
    reset_planogram_store()
    restored_store = get_store()
    restored_plans = get_planogram_store()
    titles = {r.title for r in restored_store.query()}
    assert "Before backup" in titles
    assert restored_plans.get(plan.id) is not None
    assert resolve_media_path(plan.image_ref) is not None


def test_restore_rejects_invalid_zip() -> None:
    client = TestClient(app)
    bad = client.post(
        "/api/v1/database/backup/restore",
        files={"file": ("bad.zip", b"not-a-zip", "application/zip")},
    )
    assert bad.status_code == 400


def test_backup_redacts_secrets() -> None:
    """Backup zip must not contain password hashes or webhook URLs."""
    import json

    from app.db.models import AppSettingRow, UserRow
    from app.db.session import get_session
    from app.services.webhooks import save_webhook_settings
    from app.schemas.tickets import WebhookEndpoint, WebhookProviderConfig, WebhookSettings

    # Seed a webhook with a real URL and ensure a user hash exists.
    save_webhook_settings(
        WebhookSettings(
            active_channel="slack",
            slack=WebhookProviderConfig(
                enabled=True,
                endpoints=[
                    WebhookEndpoint(
                        id="ep-ops",
                        name="ops",
                        url="https://hooks.slack.com/services/T000/B000/SECRETTOKEN",
                        enabled=True,
                    )
                ],
            ),
        )
    )
    with get_session() as session:
        user = session.query(UserRow).first()
        assert user is not None
        assert user.password_hash

    client = TestClient(app)
    export = client.get("/api/v1/database/backup")
    assert export.status_code == 200, export.text
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        data = json.loads(zf.read("data.json"))
    assert manifest.get("secretsRedacted") is True
    raw = export.content
    assert b"hooks.slack.com/services/T000/B000/SECRETTOKEN" not in raw
    assert b"SECRETTOKEN" not in raw

    # Users exported without password hashes
    assert data["users"]
    for user in data["users"]:
        assert user.get("password_hash") in (None, "",)
        assert user.get("credentials_redacted") is True

    # Webhook settings structure kept, URLs blanked
    settings_rows = [row for row in data["app_settings"] if row.get("key") == "webhook_settings"]
    assert settings_rows
    webhook = json.loads(settings_rows[0]["value"])
    for endpoint in webhook.get("slack", {}).get("endpoints", []):
        assert not endpoint.get("url")

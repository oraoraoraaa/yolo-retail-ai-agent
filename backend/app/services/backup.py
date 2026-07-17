"""System backup / restore (JSON data + media files as zip).

Backups intentionally **exclude credentials and secrets**:
- user password hashes
- webhook URLs (Slack / WeCom / generic endpoint URLs)
- any app_settings values that look like secrets (api keys, tokens, …)

Non-secret config (roles, issue→role map, enabled flags, endpoint names/ids)
is still exported so restore can rebuild structure; operators re-enter secrets.
"""

from __future__ import annotations

import copy
import io
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models import AppSettingRow, PlanogramRow, RecordRow, TicketRow, UserRow
from app.db.session import get_engine, get_session
from app.services.media import ensure_media_dirs, media_root

BACKUP_VERSION = 1
MANIFEST_NAME = "manifest.json"
DATA_NAME = "data.json"
MEDIA_PREFIX = "media/"
WEBHOOK_SETTINGS_KEY = "webhook_settings"

# App-setting keys that are never restored from backup (secrets / credentials).
_SECRET_SETTING_KEYS = {
    WEBHOOK_SETTINGS_KEY,
    "openai_api_key",
    "auth_secret",
    "api_key",
    "jwt_secret",
}

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"webhook.*url|authorization|credential|auth_secret)",
    re.IGNORECASE,
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: object) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for column in row.__table__.columns:  # type: ignore[attr-defined]
        value = getattr(row, column.name)
        if isinstance(value, datetime):
            data[column.name] = value.isoformat()
        else:
            data[column.name] = value
    return data


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _redact_webhook_settings_value(raw: str) -> str:
    """Keep webhook structure but strip all endpoint URLs."""
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return "{}"
    if not isinstance(data, dict):
        return "{}"
    cleaned = copy.deepcopy(data)
    for provider in ("slack", "wecom", "generic"):
        config = cleaned.get(provider)
        if not isinstance(config, dict):
            continue
        if "url" in config:
            config["url"] = ""
        endpoints = config.get("endpoints")
        if isinstance(endpoints, list):
            for endpoint in endpoints:
                if isinstance(endpoint, dict) and "url" in endpoint:
                    endpoint["url"] = ""
                    endpoint["urlRedacted"] = True
    cleaned["secretsRedacted"] = True
    return json.dumps(cleaned, ensure_ascii=False)


def _sanitize_app_settings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop or redact secret app_settings rows for export."""
    sanitized: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        lowered = key.lower()
        if lowered in _SECRET_SETTING_KEYS or _SECRET_KEY_RE.search(key):
            if lowered == WEBHOOK_SETTINGS_KEY:
                value = _redact_webhook_settings_value(str(item.get("value") or ""))
                sanitized.append({**item, "value": value, "secrets_redacted": True})
            continue
        value = str(item.get("value") or "")
        if "hooks.slack.com" in value or "qyapi.weixin.qq.com" in value:
            continue
        sanitized.append(item)
    return sanitized


def _sanitize_users(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Export user accounts without password hashes / credentials."""
    sanitized: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        username = str(item.get("username") or "").strip()
        if not username:
            continue
        sanitized.append(
            {
                "id": item.get("id"),
                "username": username,
                "role": item.get("role") or "staff",
                "is_active": bool(item.get("is_active", True)),
                "created_at": item.get("created_at"),
                "password_hash": None,
                "credentials_redacted": True,
            }
        )
    return sanitized


def _sanitize_ticket_evidence(evidence: Any) -> Any:
    """Strip accidental secrets from ticket evidence blobs."""
    if not isinstance(evidence, dict):
        return evidence
    cleaned = copy.deepcopy(evidence)
    for key in list(cleaned.keys()):
        if _SECRET_KEY_RE.search(str(key)):
            cleaned.pop(key, None)
            continue
        value = cleaned.get(key)
        if isinstance(value, str) and (
            "hooks.slack.com" in value
            or "qyapi.weixin.qq.com" in value
            or value.startswith("xoxb-")
            or value.startswith("sk-")
        ):
            cleaned[key] = "[redacted]"
        elif isinstance(value, dict):
            cleaned[key] = _sanitize_ticket_evidence(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _sanitize_ticket_evidence(item) if isinstance(item, dict) else item for item in value
            ]
    return cleaned


def _sanitize_tickets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if "evidence_json" in row:
            row["evidence_json"] = _sanitize_ticket_evidence(row.get("evidence_json"))
        sanitized.append(row)
    return sanitized


def export_backup_zip() -> bytes:
    """Build an in-memory zip of DB tables + media files (secrets redacted)."""
    ensure_media_dirs()
    settings = get_settings()
    get_engine()

    with get_session() as session:
        users = [_row_to_dict(row) for row in session.scalars(select(UserRow)).all()]
        records = [_row_to_dict(row) for row in session.scalars(select(RecordRow)).all()]
        planograms = [_row_to_dict(row) for row in session.scalars(select(PlanogramRow)).all()]
        tickets = [_row_to_dict(row) for row in session.scalars(select(TicketRow)).all()]
        app_settings = [_row_to_dict(row) for row in session.scalars(select(AppSettingRow)).all()]

    payload = {
        "users": _sanitize_users(users),
        "records": records,
        "planograms": planograms,
        "tickets": _sanitize_tickets(tickets),
        "app_settings": _sanitize_app_settings(app_settings),
    }

    manifest = {
        "version": BACKUP_VERSION,
        "createdAt": _utcnow_iso(),
        "app": "yolo-retail-ai-agent",
        "databaseScheme": settings.database_url.split(":", 1)[0],
        "counts": {key: len(value) for key, value in payload.items()},
        "secretsRedacted": True,
        "redacted": [
            "user password hashes",
            "webhook endpoint URLs (Slack / WeCom / generic)",
            "API keys / tokens / auth secrets in app_settings",
            "environment secrets (OPENAI_API_KEY, AUTH_SECRET, DATABASE passwords, …) — never stored in this zip",
        ],
        "includes": [
            "audit / inventory / chat records",
            "planograms + drawn slots",
            "action tickets (non-secret fields)",
            "staff usernames + roles (no passwords)",
            "non-secret app settings (active planogram, role maps without webhook URLs)",
            "media images under media/",
        ],
        "restoreNotes": [
            "Re-enter webhook URLs in Ticket Board → Webhook settings after restore.",
            "Staff passwords are not restored; existing local passwords are preserved when usernames match.",
            "Environment API keys (.env) are not part of the backup — keep those separately.",
        ],
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr(DATA_NAME, json.dumps(payload, ensure_ascii=False))

        root = media_root().resolve()
        if root.exists():
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    relative = path.resolve().relative_to(root)
                except ValueError:
                    continue
                if ".." in relative.parts:
                    continue
                arcname = f"{MEDIA_PREFIX}{relative.as_posix()}"
                zf.write(path, arcname=arcname)

    return buffer.getvalue()


def validate_backup_zip(raw: bytes) -> dict[str, Any]:
    """Validate backup structure and return parsed manifest + data."""
    if not raw:
        raise ValueError("Backup file is empty.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw), mode="r") as zf:
            names = set(zf.namelist())
            if MANIFEST_NAME not in names:
                raise ValueError("Backup is missing manifest.json.")
            if DATA_NAME not in names:
                raise ValueError("Backup is missing data.json.")
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("manifest.json is not valid JSON.") from exc
            try:
                data = json.loads(zf.read(DATA_NAME).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("data.json is not valid JSON.") from exc

            version = int(manifest.get("version") or 0)
            if version != BACKUP_VERSION:
                raise ValueError(f"Unsupported backup version {version}; expected {BACKUP_VERSION}.")
            if not isinstance(data, dict):
                raise ValueError("data.json root must be an object.")
            for key in ("users", "records", "planograms", "tickets", "app_settings"):
                if key not in data or not isinstance(data[key], list):
                    raise ValueError(f"data.json missing list field '{key}'.")

            media_files = [
                name
                for name in names
                if name.startswith(MEDIA_PREFIX) and not name.endswith("/")
            ]
            return {
                "manifest": manifest,
                "data": data,
                "media_files": media_files,
            }
    except zipfile.BadZipFile as exc:
        raise ValueError("File is not a valid zip archive.") from exc


def _merge_webhook_settings(backup_value: str, live_value: str | None) -> str:
    """Restore webhook structure from backup but keep live URLs when backup redacted them."""
    try:
        backup = json.loads(backup_value) if backup_value else {}
    except json.JSONDecodeError:
        backup = {}
    try:
        live = json.loads(live_value) if live_value else {}
    except json.JSONDecodeError:
        live = {}
    if not isinstance(backup, dict):
        backup = {}
    if not isinstance(live, dict):
        live = {}

    merged = copy.deepcopy(backup)

    def _live_url_map(provider_cfg: Any) -> dict[str, str]:
        mapping: dict[str, str] = {}
        if not isinstance(provider_cfg, dict):
            return mapping
        if provider_cfg.get("url"):
            mapping["__legacy__"] = str(provider_cfg.get("url") or "")
        for endpoint in provider_cfg.get("endpoints") or []:
            if isinstance(endpoint, dict) and endpoint.get("id") and endpoint.get("url"):
                mapping[str(endpoint["id"])] = str(endpoint["url"])
        return mapping

    for provider in ("slack", "wecom", "generic"):
        live_urls = _live_url_map(live.get(provider))
        cfg = merged.get(provider)
        if not isinstance(cfg, dict):
            continue
        if not str(cfg.get("url") or "").strip() and live_urls.get("__legacy__"):
            cfg["url"] = live_urls["__legacy__"]
        endpoints = cfg.get("endpoints")
        if isinstance(endpoints, list):
            for endpoint in endpoints:
                if not isinstance(endpoint, dict):
                    continue
                endpoint_id = str(endpoint.get("id") or "")
                if not str(endpoint.get("url") or "").strip() and endpoint_id in live_urls:
                    endpoint["url"] = live_urls[endpoint_id]
                endpoint.pop("urlRedacted", None)
        cfg.pop("secretsRedacted", None)
    merged.pop("secretsRedacted", None)
    return json.dumps(merged, ensure_ascii=False)


def restore_backup_zip(raw: bytes) -> dict[str, int]:
    """Replace current DB tables + media from a validated backup zip.

    Secrets are never taken from the backup when redacted:
    - password hashes: keep current hash when username already exists
    - webhook URLs: keep current live URLs when backup values are empty
    - secret app_settings keys: keep live values
    """
    validated = validate_backup_zip(raw)
    data: dict[str, Any] = validated["data"]

    get_engine()
    live_password_by_user: dict[str, str] = {}
    live_settings: dict[str, str] = {}
    with get_session() as session:
        for row in session.scalars(select(UserRow)).all():
            if row.username and row.password_hash:
                live_password_by_user[row.username] = row.password_hash
        for row in session.scalars(select(AppSettingRow)).all():
            live_settings[str(row.key)] = str(row.value or "")

    with zipfile.ZipFile(io.BytesIO(raw), mode="r") as zf:
        ensure_media_dirs()
        media_target = media_root().resolve()
        with tempfile.TemporaryDirectory(prefix="retail-restore-media-") as tmp:
            tmp_media = Path(tmp) / "media"
            tmp_media.mkdir(parents=True, exist_ok=True)
            for name in zf.namelist():
                if not name.startswith(MEDIA_PREFIX) or name.endswith("/"):
                    continue
                relative = name[len(MEDIA_PREFIX) :]
                if not relative or ".." in Path(relative).parts:
                    continue
                dest = tmp_media / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))

            if media_target.exists():
                shutil.rmtree(media_target)
            shutil.copytree(tmp_media, media_target)
        ensure_media_dirs()

        get_engine()
        with get_session() as session:
            session.execute(delete(TicketRow))
            session.execute(delete(RecordRow))
            session.execute(delete(PlanogramRow))
            session.execute(delete(AppSettingRow))
            session.execute(delete(UserRow))
            session.flush()

            for item in data.get("users") or []:
                if not isinstance(item, dict):
                    continue
                username = str(item.get("username") or "").strip()
                if not username:
                    continue
                password_hash = str(item.get("password_hash") or "").strip()
                if not password_hash or item.get("credentials_redacted"):
                    password_hash = live_password_by_user.get(username, "")
                if not password_hash:
                    continue
                row = UserRow(
                    username=username,
                    password_hash=password_hash,
                    role=str(item.get("role") or "staff"),
                    is_active=bool(item.get("is_active", True)),
                    created_at=_parse_dt(item.get("created_at")) or datetime.now(timezone.utc),
                )
                if item.get("id") is not None:
                    try:
                        row.id = int(item["id"])
                    except (TypeError, ValueError):
                        pass
                session.add(row)

            for item in data.get("records") or []:
                if not isinstance(item, dict):
                    continue
                session.add(
                    RecordRow(
                        id=str(item.get("id") or ""),
                        type=str(item.get("type") or "audit"),
                        title=str(item.get("title") or ""),
                        summary=str(item.get("summary") or ""),
                        image_ref=item.get("image_ref"),
                        detection_json=item.get("detection_json"),
                        planogram_json=item.get("planogram_json"),
                        extra_json=item.get("extra_json"),
                        created_at=_parse_dt(item.get("created_at")) or datetime.now(timezone.utc),
                        updated_at=_parse_dt(item.get("updated_at")) or datetime.now(timezone.utc),
                    )
                )

            for item in data.get("planograms") or []:
                if not isinstance(item, dict):
                    continue
                session.add(
                    PlanogramRow(
                        id=str(item.get("id") or ""),
                        name=str(item.get("name") or ""),
                        description=str(item.get("description") or ""),
                        image_ref=item.get("image_ref"),
                        image_base64=str(item.get("image_base64") or ""),
                        image_width=int(item.get("image_width") or 0),
                        image_height=int(item.get("image_height") or 0),
                        slots_json=item.get("slots_json") or [],
                        created_at=_parse_dt(item.get("created_at")) or datetime.now(timezone.utc),
                        updated_at=_parse_dt(item.get("updated_at")) or datetime.now(timezone.utc),
                    )
                )

            for item in data.get("tickets") or []:
                if not isinstance(item, dict):
                    continue
                session.add(
                    TicketRow(
                        id=str(item.get("id") or ""),
                        issue_type=str(item.get("issue_type") or "out_of_stock"),
                        priority=str(item.get("priority") or "medium"),
                        status=str(item.get("status") or "open"),
                        assignee_role=str(item.get("assignee_role") or "floor_staff"),
                        title=str(item.get("title") or ""),
                        description=str(item.get("description") or ""),
                        sku=item.get("sku"),
                        item_name=item.get("item_name"),
                        shelf_label=item.get("shelf_label"),
                        planogram_id=item.get("planogram_id"),
                        slot_id=item.get("slot_id"),
                        audit_record_id=item.get("audit_record_id"),
                        evidence_json=_sanitize_ticket_evidence(item.get("evidence_json")),
                        history_json=item.get("history_json") or [],
                        fingerprint=item.get("fingerprint"),
                        escalate_count=int(item.get("escalate_count") or 0),
                        dispatched_at=_parse_dt(item.get("dispatched_at")),
                        done_at=_parse_dt(item.get("done_at")),
                        verified_at=_parse_dt(item.get("verified_at")),
                        created_at=_parse_dt(item.get("created_at")) or datetime.now(timezone.utc),
                        updated_at=_parse_dt(item.get("updated_at")) or datetime.now(timezone.utc),
                    )
                )

            restored_setting_keys: set[str] = set()
            for item in data.get("app_settings") or []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if not key:
                    continue
                lowered = key.lower()
                value = str(item.get("value") or "")
                if lowered == WEBHOOK_SETTINGS_KEY:
                    value = _merge_webhook_settings(value, live_settings.get(key))
                elif lowered in _SECRET_SETTING_KEYS or _SECRET_KEY_RE.search(key):
                    if key in live_settings:
                        value = live_settings[key]
                    else:
                        continue
                session.add(AppSettingRow(key=key, value=value))
                restored_setting_keys.add(key)

            for key, value in live_settings.items():
                if key in restored_setting_keys:
                    continue
                lowered = key.lower()
                if lowered in _SECRET_SETTING_KEYS or _SECRET_KEY_RE.search(key):
                    session.add(AppSettingRow(key=key, value=value))

            session.flush()

    from app.services.planogram_store import reset_planogram_store
    from app.services.store import reset_store
    from app.services.ticket_store import reset_ticket_store
    from app.services.closed_loop import reset_closed_loop_agent

    reset_store()
    reset_planogram_store()
    reset_ticket_store()
    reset_closed_loop_agent()

    from app.services.planogram_store import get_planogram_store
    from app.services.store import get_store
    from app.services.ticket_store import get_ticket_store

    get_store()
    get_planogram_store()
    get_ticket_store()

    return {
        "users": len(data.get("users") or []),
        "records": len(data.get("records") or []),
        "planograms": len(data.get("planograms") or []),
        "tickets": len(data.get("tickets") or []),
        "appSettings": len(data.get("app_settings") or []),
        "mediaFiles": len(validated["media_files"]),
        "secretsRedacted": True,
    }

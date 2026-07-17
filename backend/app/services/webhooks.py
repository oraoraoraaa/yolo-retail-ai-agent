"""Admin-configurable multi-endpoint webhook dispatch (Slack / WeCom / generic).

Settings live in the ``app_settings`` table so the frontend admin panel can
change them without restarting the process.

Each provider can have many named endpoints (bots / channels). Routing maps
issue type, assignee role, or priority to a specific endpoint.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

import httpx
from sqlalchemy import select

from app.db.models import AppSettingRow
from app.db.session import get_engine, get_session
from app.schemas.tickets import (
    Ticket,
    WebhookChannel,
    WebhookEndpoint,
    WebhookProviderConfig,
    WebhookSettings,
)

SETTINGS_KEY = "webhook_settings"


def _default_settings() -> WebhookSettings:
    return WebhookSettings()


def _provider(settings: WebhookSettings, channel: WebhookChannel) -> WebhookProviderConfig:
    if channel == "slack":
        return settings.slack
    if channel == "wecom":
        return settings.wecom
    return settings.generic


def load_webhook_settings() -> WebhookSettings:
    get_engine()
    with get_session() as session:
        row = session.scalars(
            select(AppSettingRow).where(AppSettingRow.key == SETTINGS_KEY)
        ).first()
        if row is None or not row.value:
            return _default_settings()
        try:
            data = json.loads(row.value)
        except json.JSONDecodeError:
            return _default_settings()
        return WebhookSettings.model_validate(data)


def save_webhook_settings(settings: WebhookSettings) -> WebhookSettings:
    payload = settings.model_dump(by_alias=True)
    raw = json.dumps(payload, ensure_ascii=False)
    get_engine()
    with get_session() as session:
        row = session.scalars(
            select(AppSettingRow).where(AppSettingRow.key == SETTINGS_KEY)
        ).first()
        if row is None:
            session.add(AppSettingRow(key=SETTINGS_KEY, value=raw))
        else:
            row.value = raw
    return settings


def _parse_selector(selector: str | None) -> tuple[WebhookChannel | None, str | None]:
    """Parse 'slack:ep-123' | 'ep-123' | 'wecom' into (provider, endpoint_id)."""
    if not selector:
        return None, None
    raw = selector.strip()
    if not raw:
        return None, None
    if ":" in raw:
        provider, _, endpoint_id = raw.partition(":")
        provider = provider.strip().lower()
        endpoint_id = endpoint_id.strip() or None
        if provider in ("slack", "wecom", "generic"):
            return provider, endpoint_id  # type: ignore[return-value]
        return None, raw
    if raw in ("slack", "wecom", "generic"):
        return raw, None  # type: ignore[return-value]
    return None, raw


def _find_endpoint(
    settings: WebhookSettings,
    *,
    channel: WebhookChannel | None = None,
    endpoint_id: str | None = None,
) -> tuple[WebhookChannel, WebhookEndpoint] | None:
    providers: list[tuple[WebhookChannel, WebhookProviderConfig]] = [
        ("slack", settings.slack),
        ("wecom", settings.wecom),
        ("generic", settings.generic),
    ]
    if channel:
        providers = [(channel, _provider(settings, channel))]

    if endpoint_id:
        for prov, config in providers:
            if not config.enabled:
                continue
            for ep in config.endpoints:
                if ep.id == endpoint_id and ep.enabled and ep.url.strip():
                    return prov, ep
        # Fall through: ignore disabled match
        for prov, config in providers:
            for ep in config.endpoints:
                if ep.id == endpoint_id and ep.url.strip():
                    return prov, ep
        return None

    # First enabled endpoint of the chosen/default provider.
    for prov, config in providers:
        if not config.enabled:
            continue
        for ep in config.endpoints:
            if ep.enabled and ep.url.strip():
                return prov, ep
    return None


def resolve_endpoint_for_ticket(
    settings: WebhookSettings,
    ticket: Ticket,
) -> tuple[WebhookChannel, WebhookEndpoint] | None:
    """Pick provider+endpoint using role route only, then default.

    When a ticket targets multiple roles, try each role route in order.
    """
    roles: list[str] = []
    for role in list(getattr(ticket, "assignee_roles", None) or []):
        if role and role not in roles:
            roles.append(role)
    if ticket.assignee_role and ticket.assignee_role not in roles:
        roles.insert(0, ticket.assignee_role)
    if not roles:
        roles = [ticket.assignee_role] if ticket.assignee_role else []

    selectors: list[str | None] = [settings.role_routes.get(role) for role in roles]
    if settings.default_endpoint_id:
        selectors.append(settings.default_endpoint_id)
    selectors.append(settings.active_channel)

    for selector in selectors:
        if not selector:
            continue
        channel, endpoint_id = _parse_selector(selector)
        found = _find_endpoint(settings, channel=channel, endpoint_id=endpoint_id)
        if found:
            return found
    return None


def resolve_endpoint_for_notification(
    settings: WebhookSettings,
    *,
    issue_type: str | None = None,
    assignee_role: str | None = None,
    priority: str | None = None,
    assignee_roles: list[str] | None = None,
) -> tuple[WebhookChannel, WebhookEndpoint] | None:
    # Role is the only routing key; issue_type/priority kept for call-site compat.
    _ = issue_type, priority
    roles: list[str] = []
    for role in list(assignee_roles or []):
        if role and role not in roles:
            roles.append(role)
    if assignee_role and assignee_role not in roles:
        roles.insert(0, assignee_role)
    selectors: list[str | None] = [settings.role_routes.get(role) for role in roles]
    selectors.extend([settings.default_endpoint_id, settings.active_channel])
    for selector in selectors:
        if not selector:
            continue
        channel, endpoint_id = _parse_selector(selector)
        found = _find_endpoint(settings, channel=channel, endpoint_id=endpoint_id)
        if found:
            return found
    return None


def _strip_data_url(image: str | None) -> tuple[str | None, str | None]:
    """Return (raw_base64, mime) from a data URL or bare base64 string."""
    if not image:
        return None, None
    value = image.strip()
    if not value:
        return None, None
    match = re.match(r"^data:([^;]+);base64,(.+)$", value, flags=re.DOTALL)
    if match:
        return match.group(2).replace("\n", ""), match.group(1)
    # bare base64
    return value.replace("\n", ""), "image/jpeg"


def _role_label(
    role: str | None,
    settings: WebhookSettings | None = None,
    *,
    language: str = "en",
) -> str:
    if not role:
        return "—"
    if settings is not None:
        for item in settings.roles or []:
            if item.id == role:
                # Prefer admin-configured label; fall back to localized builtin.
                if item.label and item.label.strip() and item.label.strip() != role:
                    return item.label
                break
    zh = language == "zh"
    labels_en = {
        "floor_staff": "Floor staff",
        "backroom": "Backroom",
        "manager": "Manager",
    }
    labels_zh = {
        "floor_staff": "一线员工",
        "backroom": "后仓",
        "manager": "店长",
    }
    labels = labels_zh if zh else labels_en
    if role in labels:
        return labels[role]
    return role.replace("_", " ").title() if not zh else role


def _roles_for_ticket(ticket: Ticket | None, assignee_role: str | None = None) -> list[str]:
    roles: list[str] = []
    if ticket is not None:
        for role in list(getattr(ticket, "assignee_roles", None) or []):
            if role and role not in roles:
                roles.append(role)
        if ticket.assignee_role and ticket.assignee_role not in roles:
            roles.insert(0, ticket.assignee_role)
        if ticket.evidence and isinstance(ticket.evidence, dict):
            extra = ticket.evidence.get("assigneeRoles") or ticket.evidence.get("assignee_roles")
            if isinstance(extra, list):
                for role in extra:
                    text = str(role or "").strip()
                    if text and text not in roles:
                        roles.append(text)
    if assignee_role and assignee_role not in roles:
        roles.append(assignee_role)
    return roles


def _format_roles(
    roles: list[str],
    settings: WebhookSettings | None = None,
    *,
    language: str = "en",
) -> str:
    if not roles:
        return "—"
    return ", ".join(_role_label(role, settings, language=language) for role in roles)


def _issue_label(issue_type: str | None, *, language: str = "en") -> str:
    zh = language == "zh"
    labels = {
        "out_of_stock": ("Out of stock", "缺货"),
        "shelf_empty": ("Shelf empty", "货架空位"),
        "misplaced": ("Misplaced", "错位"),
        "low_stock": ("Low stock", "低库存"),
        "camera_issue": ("Camera issue", "摄像头异常"),
        "low_stock_warning": ("Low stock warning", "低库存预警"),
    }
    if not issue_type:
        return "—"
    pair = labels.get(issue_type)
    if not pair:
        return issue_type
    return pair[1] if zh else pair[0]


def _priority_label(priority: str | None, *, language: str = "en") -> str:
    zh = language == "zh"
    labels = {
        "critical": ("Critical", "紧急"),
        "high": ("High", "高"),
        "medium": ("Medium", "中"),
        "low": ("Low", "低"),
    }
    if not priority:
        return "—"
    pair = labels.get(priority)
    if not pair:
        return priority
    return pair[1] if zh else pair[0]


def _status_label(status: str | None, *, language: str = "en") -> str:
    zh = language == "zh"
    labels = {
        "open": ("Open", "待处理"),
        "dispatched": ("Dispatched", "已派发"),
        "in_progress": ("In progress", "处理中"),
        "done": ("Done", "已完成"),
        "verified": ("Verified", "已核验"),
        "escalated": ("Escalated", "已升级"),
        "cancelled": ("Cancelled", "已取消"),
    }
    if not status:
        return "—"
    pair = labels.get(status)
    if not pair:
        return status
    return pair[1] if zh else pair[0]


def _ui(language: str = "en") -> dict[str, str]:
    if language == "zh":
        return {
            "shelf": "货架 / 计划图",
            "sent_to": "发送角色",
            "priority": "优先级",
            "issue": "问题",
            "assignee_role": "指派角色",
            "status": "状态",
            "sku": "SKU",
            "item": "商品",
            "slot": "货位",
            "ticket": "工单",
            "roles": "角色",
            "image_note": "带检测框的可视化图片可在工单看板中查看（Slack 入站 Webhook 无法附加私有 base64 图片）。",
            "sent_to_short": "发送给",
        }
    return {
        "shelf": "Shelf / planogram",
        "sent_to": "Sent to role(s)",
        "priority": "Priority",
        "issue": "Issue",
        "assignee_role": "Assignee role",
        "status": "Status",
        "sku": "SKU",
        "item": "Item",
        "slot": "Slot",
        "ticket": "Ticket",
        "roles": "Roles",
        "image_note": (
            "Annotated detection image is available in the Ticket Board "
            "(Slack incoming webhooks cannot attach private base64 images)."
        ),
        "sent_to_short": "sent to",
    }


def _ticket_language(ticket: Ticket | None = None, language: str | None = None) -> str:
    if language in ("zh", "en"):
        return language
    if ticket and isinstance(ticket.evidence, dict):
        raw = ticket.evidence.get("language") or ticket.evidence.get("lang")
        if str(raw or "").lower().startswith("zh"):
            return "zh"
    return "en"


def _ticket_context_lines(
    ticket: Ticket,
    settings: WebhookSettings | None = None,
    *,
    language: str = "en",
) -> list[str]:
    ui = _ui(language)
    shelf = ticket.shelf_label or "—"
    roles = _roles_for_ticket(ticket)
    role_text = _format_roles(roles, settings, language=language)
    lines = [
        f"{ui['shelf']}: {shelf}",
        f"{ui['sent_to']}: {role_text}",
        f"{ui['priority']}: {_priority_label(ticket.priority, language=language)}",
        f"{ui['issue']}: {_issue_label(ticket.issue_type, language=language)}",
        f"{ui['assignee_role']}: {role_text}",
        f"{ui['status']}: {_status_label(ticket.status, language=language)}",
        f"{ui['sku']}: {ticket.sku or '—'} · {ui['item']}: {ticket.item_name or '—'}",
    ]
    if ticket.slot_id:
        lines.append(f"{ui['slot']}: {ticket.slot_id}")
    if ticket.description:
        lines.append(ticket.description)
    return lines


def _slack_payload(
    text: str,
    ticket: Ticket | None = None,
    *,
    annotated_image: str | None = None,
    shelf_label: str | None = None,
    assignee_role: str | None = None,
    assignee_roles: list[str] | None = None,
    settings: WebhookSettings | None = None,
    language: str = "en",
) -> dict[str, Any]:
    ui = _ui(language)
    roles = list(assignee_roles or [])
    if ticket is not None:
        roles = _roles_for_ticket(ticket, assignee_role)
    elif assignee_role and assignee_role not in roles:
        roles.append(assignee_role)
    role_text = _format_roles(roles, settings, language=language)

    if ticket is None:
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text[:2800]}},
        ]
        context_bits = []
        if shelf_label:
            context_bits.append(f"{ui['shelf']}: *{shelf_label}*")
        if role_text != "—":
            context_bits.append(f"{ui['sent_to']}: *{role_text}*")
        if context_bits:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": " · ".join(context_bits)}],
                }
            )
        return {"text": text, "blocks": blocks}

    shelf = ticket.shelf_label or shelf_label or "—"
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🛒 {ticket.title}"[:150]},
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*{ui['priority']}*\n{_priority_label(ticket.priority, language=language)}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*{ui['issue']}*\n{_issue_label(ticket.issue_type, language=language)}",
                },
                {"type": "mrkdwn", "text": f"*{ui['sent_to']}*\n{role_text}"},
                {"type": "mrkdwn", "text": f"*{ui['shelf']}*\n{shelf}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (ticket.description or text)[:2800],
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"{ui['sku']}: `{ticket.sku or '—'}` · {ui['item']}: {ticket.item_name or '—'} · "
                        f"{ui['ticket']}: `{ticket.id}` · {ui['roles']}: `{', '.join(roles) or ticket.assignee_role}`"
                    ),
                }
            ],
        },
    ]
    if annotated_image:
        if annotated_image.startswith("http://") or annotated_image.startswith("https://"):
            blocks.append(
                {
                    "type": "image",
                    "image_url": annotated_image,
                    "alt_text": "Shelf detection with bounding boxes" if language != "zh" else "带检测框的货架检测图",
                }
            )
        else:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ui["image_note"],
                        }
                    ],
                }
            )
    return {"text": text, "blocks": blocks}


def _wecom_payload(
    text: str,
    ticket: Ticket | None = None,
    *,
    shelf_label: str | None = None,
    assignee_role: str | None = None,
    assignee_roles: list[str] | None = None,
    settings: WebhookSettings | None = None,
    language: str = "en",
) -> dict[str, Any]:
    ui = _ui(language)
    roles = list(assignee_roles or [])
    if ticket is not None:
        roles = _roles_for_ticket(ticket, assignee_role)
    elif assignee_role and assignee_role not in roles:
        roles.append(assignee_role)
    role_text = _format_roles(roles, settings, language=language)

    if ticket is None:
        content = text
        prefix = []
        if shelf_label:
            prefix.append(f"{ui['shelf']}: **{shelf_label}**")
        if role_text != "—":
            prefix.append(f"{ui['sent_to']}: **{role_text}**")
        if prefix:
            content = "\n".join(prefix) + f"\n{content}"
    else:
        shelf = ticket.shelf_label or shelf_label or "—"
        content = (
            f"**{ticket.title}**\n"
            f"> {ui['shelf']}: <font color=\"info\">{shelf}</font>\n"
            f"> {ui['sent_to']}: <font color=\"warning\">{role_text}</font>\n"
            f"> {ui['priority']}: <font color=\"warning\">{_priority_label(ticket.priority, language=language)}</font>\n"
            f"> {ui['issue']}: {_issue_label(ticket.issue_type, language=language)}\n"
            f"> {ui['assignee_role']}: {role_text}\n"
            f"> {ui['status']}: {_status_label(ticket.status, language=language)}\n"
            f"> {ui['sku']}: {ticket.sku or '—'} · {ui['item']}: {ticket.item_name or '—'}\n"
            f"> {ui['ticket']}: {ticket.id}\n\n"
            f"{ticket.description or text}"
        )
    return {"msgtype": "markdown", "markdown": {"content": content[:4000]}}


def _wecom_image_payload(annotated_image: str) -> dict[str, Any] | None:
    raw_b64, _mime = _strip_data_url(annotated_image)
    if not raw_b64:
        return None
    try:
        raw_bytes = base64.b64decode(raw_b64, validate=False)
    except Exception:
        return None
    md5 = hashlib.md5(raw_bytes).hexdigest()
    # WeCom expects pure base64 without data-url prefix.
    return {"msgtype": "image", "image": {"base64": raw_b64, "md5": md5}}


def _generic_payload(
    text: str,
    ticket: Ticket | None = None,
    *,
    annotated_image: str | None = None,
    shelf_label: str | None = None,
    assignee_role: str | None = None,
    assignee_roles: list[str] | None = None,
    settings: WebhookSettings | None = None,
    language: str = "en",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    roles = list(assignee_roles or [])
    if ticket is not None:
        roles = _roles_for_ticket(ticket, assignee_role)
    elif assignee_role and assignee_role not in roles:
        roles.append(assignee_role)
    body: dict[str, Any] = {
        "source": "yolo-retail-ai-agent",
        "text": text,
        "language": language,
        "shelfLabel": shelf_label or (ticket.shelf_label if ticket else None),
        "sentToRoles": roles,
        "assigneeRole": roles[0] if roles else assignee_role,
    }
    if ticket is not None:
        body["ticket"] = ticket.model_dump(by_alias=True, mode="json")
        body["context"] = _ticket_context_lines(ticket, settings, language=language)
    if annotated_image:
        body["annotatedImage"] = annotated_image
    if extra:
        body.update(extra)
    return body


def build_webhook_body(
    channel: WebhookChannel,
    text: str,
    ticket: Ticket | None = None,
    *,
    annotated_image: str | None = None,
    shelf_label: str | None = None,
    assignee_role: str | None = None,
    assignee_roles: list[str] | None = None,
    settings: WebhookSettings | None = None,
    language: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lang = _ticket_language(ticket, language)
    if channel == "slack":
        return _slack_payload(
            text,
            ticket,
            annotated_image=annotated_image,
            shelf_label=shelf_label,
            assignee_role=assignee_role,
            assignee_roles=assignee_roles,
            settings=settings,
            language=lang,
        )
    if channel == "wecom":
        return _wecom_payload(
            text,
            ticket,
            shelf_label=shelf_label,
            assignee_role=assignee_role,
            assignee_roles=assignee_roles,
            settings=settings,
            language=lang,
        )
    return _generic_payload(
        text,
        ticket,
        annotated_image=annotated_image,
        shelf_label=shelf_label,
        assignee_role=assignee_role,
        assignee_roles=assignee_roles,
        settings=settings,
        language=lang,
        extra=extra,
    )


async def post_webhook(
    *,
    channel: WebhookChannel,
    url: str,
    body: dict[str, Any],
    timeout: float = 15.0,
) -> dict[str, Any]:
    """POST a payload to the configured webhook URL."""
    if not url.strip():
        return {"ok": False, "error": "Webhook URL is empty", "channel": channel}

    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(url.strip(), json=body)
            ok = 200 <= response.status_code < 300
            return {
                "ok": ok,
                "channel": channel,
                "statusCode": response.status_code,
                "responseText": response.text[:500],
                "error": None if ok else f"HTTP {response.status_code}",
            }
    except Exception as exc:  # pragma: no cover - network dependent
        return {
            "ok": False,
            "channel": channel,
            "statusCode": None,
            "responseText": "",
            "error": str(exc),
        }


async def dispatch_ticket(
    ticket: Ticket,
    settings: WebhookSettings | None = None,
    *,
    annotated_image: str | None = None,
    shelf_label: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Send a ticket notification on the resolved named endpoint."""
    settings = settings or load_webhook_settings()
    lang = _ticket_language(ticket, language)
    resolved = resolve_endpoint_for_ticket(settings, ticket)
    if resolved is None:
        return {
            "ok": False,
            "skipped": True,
            "channel": settings.active_channel,
            "error": "No enabled webhook endpoint matched routing rules",
        }
    channel, endpoint = resolved
    provider = _provider(settings, channel)
    if not provider.enabled:
        return {
            "ok": False,
            "skipped": True,
            "channel": channel,
            "endpointId": endpoint.id,
            "endpointName": endpoint.name,
            "error": f"Provider '{channel}' is disabled",
        }
    if not endpoint.enabled or not endpoint.url.strip():
        return {
            "ok": False,
            "skipped": True,
            "channel": channel,
            "endpointId": endpoint.id,
            "endpointName": endpoint.name,
            "error": f"Endpoint '{endpoint.name}' is disabled or has no URL",
        }

    shelf = shelf_label or ticket.shelf_label or "—"
    roles = _roles_for_ticket(ticket)
    role_text = _format_roles(roles, settings, language=lang)
    ui = _ui(lang)
    text = (
        f"[{_priority_label(ticket.priority, language=lang)}] {ticket.title} "
        f"({ui['sent_to_short']}: {role_text}) · {ui['shelf']}: {shelf}"
    )
    body = build_webhook_body(
        channel,
        text,
        ticket,
        annotated_image=annotated_image,
        shelf_label=shelf,
        assignee_role=ticket.assignee_role,
        assignee_roles=roles,
        settings=settings,
        language=lang,
    )
    result = await post_webhook(channel=channel, url=endpoint.url, body=body)
    result["skipped"] = False
    result["ticketId"] = ticket.id
    result["endpointId"] = endpoint.id
    result["endpointName"] = endpoint.name
    result["language"] = lang

    # WeCom can follow with a native image message when we have annotated bytes.
    if (
        result.get("ok")
        and channel == "wecom"
        and annotated_image
        and not annotated_image.startswith("http")
    ):
        image_body = _wecom_image_payload(annotated_image)
        if image_body:
            image_result = await post_webhook(
                channel=channel, url=endpoint.url, body=image_body
            )
            result["imageOk"] = image_result.get("ok")
            result["imageError"] = image_result.get("error")
    return result


async def dispatch_notification(
    *,
    title: str,
    description: str,
    issue_type: str = "low_stock_warning",
    priority: str = "low",
    assignee_role: str = "backroom",
    assignee_roles: list[str] | None = None,
    sku: str | None = None,
    item_name: str | None = None,
    shelf_label: str | None = None,
    annotated_image: str | None = None,
    settings: WebhookSettings | None = None,
    evidence: dict[str, Any] | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Push a non-ticket notification (e.g. low-stock warning)."""
    settings = settings or load_webhook_settings()
    roles = list(assignee_roles or [])
    if assignee_role and assignee_role not in roles:
        roles.insert(0, assignee_role)
    if not roles:
        roles = [assignee_role]
    lang = "zh" if str(language or "").lower().startswith("zh") else "en"
    if evidence and isinstance(evidence, dict):
        raw = evidence.get("language") or evidence.get("lang")
        if str(raw or "").lower().startswith("zh"):
            lang = "zh"
    resolved = resolve_endpoint_for_notification(
        settings,
        issue_type=issue_type,
        assignee_role=roles[0] if roles else assignee_role,
        priority=priority,
        assignee_roles=roles,
    )
    if resolved is None:
        return {
            "ok": False,
            "skipped": True,
            "error": "No enabled webhook endpoint for notification",
            "issueType": issue_type,
        }
    channel, endpoint = resolved
    shelf = shelf_label or "—"
    role_text = _format_roles(roles, settings, language=lang)
    ui = _ui(lang)
    text = (
        f"[{_priority_label(priority, language=lang)}] {title} · "
        f"{ui['sent_to_short']}: {role_text} · {ui['shelf']}: {shelf}"
    )
    if description:
        text = f"{text}\n{description}"
    if sku or item_name:
        text = f"{text}\n{ui['sku']}: {sku or '—'} · {ui['item']}: {item_name or '—'}"

    # Build a lightweight pseudo-ticket for rich formatting.
    pseudo = Ticket(
        id="notify",
        issue_type=issue_type if issue_type in (
            "out_of_stock",
            "shelf_empty",
            "misplaced",
            "low_stock",
            "camera_issue",
            "low_stock_warning",
        ) else "low_stock",  # type: ignore[arg-type]
        priority=priority if priority in ("critical", "high", "medium", "low") else "low",  # type: ignore[arg-type]
        status="open",
        assignee_role=roles[0] if roles else "backroom",
        assignee_roles=roles,
        title=title,
        description=description,
        sku=sku,
        item_name=item_name,
        shelf_label=shelf_label,
        history=[],
        escalate_count=0,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        evidence={"assigneeRoles": roles, "language": lang, **(evidence or {})},
    )
    body = build_webhook_body(
        channel,
        text,
        pseudo,
        annotated_image=annotated_image,
        shelf_label=shelf,
        assignee_role=roles[0] if roles else assignee_role,
        assignee_roles=roles,
        settings=settings,
        language=lang,
        extra={"notification": True, "evidence": evidence or {}, "sentToRoles": roles, "language": lang},
    )
    result = await post_webhook(channel=channel, url=endpoint.url, body=body)
    result["skipped"] = False
    result["endpointId"] = endpoint.id
    result["endpointName"] = endpoint.name
    result["issueType"] = issue_type
    result["notification"] = True
    result["language"] = lang

    if (
        result.get("ok")
        and channel == "wecom"
        and annotated_image
        and not annotated_image.startswith("http")
    ):
        image_body = _wecom_image_payload(annotated_image)
        if image_body:
            image_result = await post_webhook(
                channel=channel, url=endpoint.url, body=image_body
            )
            result["imageOk"] = image_result.get("ok")
    return result


async def send_test_message(
    settings: WebhookSettings | None = None,
    *,
    channel: WebhookChannel | None = None,
    endpoint_id: str | None = None,
    message: str = "YOLO Retail Agent webhook test",
    language: str | None = None,
) -> dict[str, Any]:
    """Send a test webhook using draft or persisted settings."""
    settings = settings or load_webhook_settings()
    lang = "zh" if str(language or "").lower().startswith("zh") else "en"
    target_channel = channel or settings.active_channel
    found = _find_endpoint(
        settings, channel=target_channel, endpoint_id=endpoint_id
    )
    if found is None:
        # Try any enabled endpoint on the provider, then any provider.
        found = _find_endpoint(settings, channel=target_channel)
    if found is None:
        found = _find_endpoint(settings)
    if found is None:
        return {
            "ok": False,
            "channel": target_channel,
            "error": (
                f"No enabled endpoint for '{target_channel}'. "
                "Add a named webhook URL, enable it, then try again."
            ),
        }
    channel, endpoint = found
    if not endpoint.url.strip():
        return {
            "ok": False,
            "channel": channel,
            "endpointId": endpoint.id,
            "error": f"Endpoint '{endpoint.name}' has no webhook URL.",
        }
    ui = _ui(lang)
    suffix = f" · endpoint: {endpoint.name}" if lang != "zh" else f" · 端点：{endpoint.name}"
    body = build_webhook_body(
        channel,
        f"{message}{suffix}",
        shelf_label="(test)" if lang != "zh" else "（测试）",
        language=lang,
        extra={"language": lang, "test": True},
    )
    # Ensure generic payload language is present even without ticket.
    if "language" not in body:
        body["language"] = lang
    result = await post_webhook(channel=channel, url=endpoint.url, body=body)
    result["channel"] = channel
    result["endpointId"] = endpoint.id
    result["endpointName"] = endpoint.name
    result["language"] = lang
    return result

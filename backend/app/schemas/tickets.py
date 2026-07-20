"""Action-ticket and closed-loop agent schemas (camelCase ↔ frontend)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from app.schemas.common import CamelModel

IssueType = Literal[
    "out_of_stock",
    "shelf_empty",
    "misplaced",
    "low_stock",
    "camera_issue",
    "low_stock_warning",
]
TicketPriority = Literal["critical", "high", "medium", "low"]
TicketStatus = Literal[
    "open",
    "dispatched",
    "in_progress",
    "done",
    "verified",
    "escalated",
    "cancelled",
]
# Built-in defaults; custom roles may also be stored as free-form strings.
AssigneeRole = str
WebhookChannel = Literal["slack", "wecom", "generic"]

DEFAULT_ROLES: list[dict[str, str]] = [
    {"id": "floor_staff", "label": "Floor staff"},
    {"id": "backroom", "label": "Backroom"},
    {"id": "manager", "label": "Manager"},
    # Store-wide broadcast channel. Not a ticket assignee — used only to notify
    # everyone (e.g. an empty facing awaiting backroom replenishment).
    {"id": "announcement", "label": "Announcement"},
]

# Fixed issue types (not user-editable). Values are default assignee role ids.
DEFAULT_ISSUE_ROLE_MAP: dict[str, list[str]] = {
    "low_stock": ["backroom"],
    "low_stock_warning": ["backroom"],
    "out_of_stock": ["backroom"],
    "shelf_empty": ["floor_staff"],
    "camera_issue": ["floor_staff", "manager"],
    "misplaced": ["floor_staff"],
    # Store-wide broadcast target for empty-facing-awaiting-replenishment.
    "shelf_empty_announcement": ["announcement"],
}

FIXED_ISSUE_TYPES: list[str] = [
    "low_stock",
    "low_stock_warning",
    "out_of_stock",
    "shelf_empty",
    "camera_issue",
]


class Ticket(CamelModel):
    """Board-visible action ticket."""

    id: str
    issue_type: IssueType | str
    priority: TicketPriority
    status: TicketStatus
    assignee_role: str
    # All roles this ticket/announcement is sent to (primary is assignee_role).
    assignee_roles: list[str] = Field(default_factory=list)
    title: str
    description: str = ""
    sku: str | None = None
    item_name: str | None = None
    shelf_label: str | None = None
    planogram_id: str | None = None
    slot_id: str | None = None
    audit_record_id: str | None = None
    evidence: dict[str, Any] | None = None
    history: list[dict[str, Any]] = []
    fingerprint: str | None = None
    escalate_count: int = 0
    dispatched_at: datetime | None = None
    done_at: datetime | None = None
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _ensure_assignee_roles(self) -> Ticket:
        roles = list(self.assignee_roles or [])
        if self.assignee_role and self.assignee_role not in roles:
            roles.insert(0, self.assignee_role)
        if not roles and self.assignee_role:
            roles = [self.assignee_role]
        # Prefer evidence.assigneeRoles when present (restored / older rows).
        if self.evidence and isinstance(self.evidence, dict):
            extra = self.evidence.get("assigneeRoles") or self.evidence.get("assignee_roles")
            if isinstance(extra, list):
                for role in extra:
                    text = str(role or "").strip()
                    if text and text not in roles:
                        roles.append(text)
        object.__setattr__(self, "assignee_roles", roles)
        return self


class TicketListResult(CamelModel):
    tickets: list[Ticket]
    total: int


class TicketClearResult(CamelModel):
    """Result of wiping the action-ticket board."""

    deleted: int
    message: str = "Tickets cleared."


class TicketStatusUpdate(CamelModel):
    status: TicketStatus
    note: str | None = None


class TicketCreateManual(CamelModel):
    """Admin/manual ticket creation (rare; usually closed-loop creates them)."""

    issue_type: IssueType | str
    priority: TicketPriority = "medium"
    assignee_role: str = "floor_staff"
    assignee_roles: list[str] = Field(default_factory=list)
    title: str
    description: str = ""
    sku: str | None = None
    item_name: str | None = None
    shelf_label: str | None = None
    planogram_id: str | None = None
    slot_id: str | None = None


class ClosedLoopRunRequest(CamelModel):
    """Input for Detect → Decide → Dispatch (optionally skip dispatch)."""

    vision_model_response: dict[str, Any]
    planogram_response: dict[str, Any] | None = None
    language: str = "en"
    source_label: str | None = None
    audit_record_id: str | None = None
    # When false, tickets are created as open without webhook dispatch.
    dispatch: bool = True
    # When true, reuse open tickets with the same fingerprint instead of creating duplicates.
    dedupe: bool = True


class ClosedLoopRunResult(CamelModel):
    """Result of one closed-loop pass over a shelf snapshot."""

    stage: str
    narrative: str
    findings: list[dict[str, Any]]
    tickets_created: list[Ticket]
    tickets_updated: list[Ticket]
    dispatched: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    # Non-ticket notifications (e.g. low-stock warnings).
    notifications: list[dict[str, Any]] = []


class VerifyTicketRequest(CamelModel):
    """Re-scan evidence used to verify a done ticket."""

    vision_model_response: dict[str, Any]
    planogram_response: dict[str, Any] | None = None
    language: str = "en"
    source_label: str | None = None


class VerifyTicketResult(CamelModel):
    ticket: Ticket
    verified: bool
    escalated: bool
    narrative: str
    remaining_issues: list[dict[str, Any]]


class WebhookEndpoint(CamelModel):
    """A named bot/channel webhook URL within a provider."""

    id: str = Field(default_factory=lambda: f"ep-{uuid4().hex[:10]}")
    name: str = "Default"
    url: str = ""
    enabled: bool = True


class WebhookProviderConfig(CamelModel):
    """Provider (Slack / WeCom / generic) with multiple named endpoints."""

    enabled: bool = False
    endpoints: list[WebhookEndpoint] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_single_url(cls, data: Any) -> Any:
        """Accept legacy {enabled, url, label} shape and promote to endpoints[]."""
        if not isinstance(data, dict):
            return data
        if data.get("endpoints") is not None:
            return data
        url = str(data.get("url") or "").strip()
        label = str(data.get("label") or "").strip() or "Default"
        if url or data.get("enabled"):
            data = dict(data)
            data["endpoints"] = [
                {
                    "id": f"ep-legacy-{label.lower().replace(' ', '-')[:16] or 'default'}",
                    "name": label,
                    "url": url,
                    "enabled": bool(data.get("enabled", False)) and bool(url),
                }
            ]
        return data


class StaffRole(CamelModel):
    """User-manageable staff role used for assignment + webhook routing."""

    id: str
    label: str = ""


class WebhookSettings(CamelModel):
    """Admin-configurable multi-endpoint dispatch settings."""

    # Default provider used when no role route matches.
    active_channel: WebhookChannel = "slack"
    slack: WebhookProviderConfig = Field(default_factory=WebhookProviderConfig)
    wecom: WebhookProviderConfig = Field(default_factory=WebhookProviderConfig)
    generic: WebhookProviderConfig = Field(default_factory=WebhookProviderConfig)
    # Preferred endpoint id for the active provider when no role route hits.
    default_endpoint_id: str | None = None
    # Manageable roles (add/delete/rename). Issue types stay fixed.
    roles: list[StaffRole] = Field(
        default_factory=lambda: [StaffRole.model_validate(item) for item in DEFAULT_ROLES]
    )
    # Fixed issue types → one or more role ids (editable targets, not issue keys).
    issue_role_map: dict[str, list[str]] = Field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_ISSUE_ROLE_MAP.items()}
    )
    # Map assignee roles → "provider:endpointId" or bare endpointId.
    # e.g. {"manager": "slack:ep-manager-alerts", "floor_staff": "wecom:ep-floor"}
    role_routes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_role_channels(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # Old field roleChannels: {"manager": "wecom"} → roleRoutes provider-only selectors.
        if "roleRoutes" not in data and "role_routes" not in data:
            legacy = data.get("roleChannels") or data.get("role_channels") or {}
            if isinstance(legacy, dict) and legacy:
                data["roleRoutes"] = {str(k): str(v) for k, v in legacy.items() if v}
        # Drop obsolete issue/priority routes if present in stored JSON.
        data.pop("issueRoutes", None)
        data.pop("issue_routes", None)
        data.pop("priorityRoutes", None)
        data.pop("priority_routes", None)
        # Ensure roles default.
        if not data.get("roles") and not data.get("roles".upper() if False else None):
            if "roles" not in data:
                data["roles"] = list(DEFAULT_ROLES)
        # Ensure issue role map has fixed keys only.
        raw_map = data.get("issueRoleMap") or data.get("issue_role_map") or {}
        if not isinstance(raw_map, dict):
            raw_map = {}
        cleaned: dict[str, list[str]] = {}
        for key in FIXED_ISSUE_TYPES + ["misplaced"]:
            values = raw_map.get(key)
            if values is None:
                values = DEFAULT_ISSUE_ROLE_MAP.get(key, ["floor_staff"])
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list):
                values = list(DEFAULT_ISSUE_ROLE_MAP.get(key, ["floor_staff"]))
            cleaned[key] = [str(v).strip() for v in values if str(v).strip()]
            if not cleaned[key]:
                cleaned[key] = list(DEFAULT_ISSUE_ROLE_MAP.get(key, ["floor_staff"]))
        data["issueRoleMap"] = cleaned
        return data

    @model_validator(mode="after")
    def _normalize_roles(self) -> WebhookSettings:
        roles: list[StaffRole] = []
        seen: set[str] = set()
        for role in self.roles or []:
            role_id = str(role.id or "").strip().lower().replace(" ", "_")
            if not role_id or role_id in seen:
                continue
            seen.add(role_id)
            label = (role.label or role_id).strip()
            roles.append(StaffRole(id=role_id, label=label))
        if not roles:
            roles = [StaffRole.model_validate(item) for item in DEFAULT_ROLES]
        object.__setattr__(self, "roles", roles)

        cleaned_map: dict[str, list[str]] = {}
        for key in FIXED_ISSUE_TYPES + ["misplaced"]:
            values = self.issue_role_map.get(key) if self.issue_role_map else None
            if not values:
                values = DEFAULT_ISSUE_ROLE_MAP.get(key, ["floor_staff"])
            role_ids = [str(v).strip() for v in values if str(v).strip()]
            cleaned_map[key] = role_ids or list(DEFAULT_ISSUE_ROLE_MAP.get(key, ["floor_staff"]))
        object.__setattr__(self, "issue_role_map", cleaned_map)
        return self


class WebhookTestRequest(CamelModel):
    channel: WebhookChannel | None = None
    # Optional specific endpoint id within the provider.
    endpoint_id: str | None = None
    message: str = "YOLO Retail Agent webhook test"
    # Optional draft settings from the admin form. When present, the test uses
    # these values instead of only whatever is already persisted in the DB.
    settings: WebhookSettings | None = None
    language: str | None = None

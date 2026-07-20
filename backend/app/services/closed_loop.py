"""Closed-loop retail agent: Detect → Decide → Dispatch → Verify.

Implemented as a small explicit state graph (LangGraph-style) without requiring
the heavy langchain/langgraph dependency stack. Offline/deterministic paths
always work; an optional LLM can refine narratives when OPENAI_API_KEY is set.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from app.config import Settings, get_settings
from app.schemas.tickets import (
    AssigneeRole,
    ClosedLoopRunResult,
    DEFAULT_ISSUE_ROLE_MAP,
    IssueType,
    Ticket,
    TicketPriority,
    VerifyTicketResult,
)
from app.services.observation_store import ObservationStore, get_observation_store
from app.services.ticket_store import TicketStore, get_ticket_store
from app.services.webhooks import (
    dispatch_notification,
    dispatch_ticket,
    load_webhook_settings,
)

# ---------------------------------------------------------------------------
# Finding extraction (Detect + Decide)
# ---------------------------------------------------------------------------

IssueKind = IssueType

# Low-stock severity bands (planogram remaining stock units).
# > 300: ignore
# <= 300: warning notification only (no ticket)
# <= 200: low priority ticket
# <= 100: medium priority ticket
# <= 50:  high priority ticket
LOW_STOCK_WARN_THRESHOLD = 300
LOW_STOCK_LOW_THRESHOLD = 200
LOW_STOCK_MEDIUM_THRESHOLD = 100
LOW_STOCK_HIGH_THRESHOLD = 50


@dataclass
class Finding:
    issue_type: IssueKind | str
    priority: TicketPriority
    assignee_role: str
    title: str
    description: str
    sku: str | None = None
    item_name: str | None = None
    shelf_label: str | None = None
    planogram_id: str | None = None
    slot_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    # When True, push a notification without opening a board ticket.
    notify_only: bool = False
    # All roles this finding should notify (primary is assignee_role).
    assignee_roles: list[str] = field(default_factory=list)
    # Broadcast companion: when True, a store-wide announcement is pushed the
    # first time this finding's ticket is created (not on later re-detections),
    # so everyone knows about an empty facing awaiting replenishment.
    announce: bool = False
    announce_title: str = ""
    announce_description: str = ""
    announce_roles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        roles = list(self.assignee_roles or [])
        if self.assignee_role and self.assignee_role not in roles:
            roles.insert(0, self.assignee_role)
        return {
            "issueType": self.issue_type,
            "priority": self.priority,
            "assigneeRole": self.assignee_role,
            "assigneeRoles": roles,
            "title": self.title,
            "description": self.description,
            "sku": self.sku,
            "itemName": self.item_name,
            "shelfLabel": self.shelf_label,
            "planogramId": self.planogram_id,
            "slotId": self.slot_id,
            "evidence": self.evidence,
            "fingerprint": self.fingerprint,
            "notifyOnly": self.notify_only,
        }


def _is_gap(label: str) -> bool:
    lowered = label.strip().lower()
    return "gap" in lowered or "empty" in lowered or "缺" in lowered or "空" in lowered


def _fingerprint(*parts: str | None) -> str:
    raw = "|".join((p or "").strip().lower() for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _slot_stock(slot: dict[str, Any] | None) -> float | None:
    if not slot:
        return None
    raw = slot.get("itemStock")
    if raw is None:
        raw = slot.get("item_stock")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _roles_for_issue(issue_type: str, settings=None) -> list[str]:
    mapping = None
    if settings is not None:
        mapping = getattr(settings, "issue_role_map", None)
    if not mapping:
        mapping = DEFAULT_ISSUE_ROLE_MAP
    roles = list(mapping.get(issue_type) or DEFAULT_ISSUE_ROLE_MAP.get(issue_type) or ["floor_staff"])
    cleaned = [str(r).strip() for r in roles if str(r).strip()]
    return cleaned or ["floor_staff"]


def _sku_key(sku: str | None, item_name: str | None = None, slot_id: str | None = None) -> str:
    """Stable identity for SKU-level aggregation. Prefer SKU, then item name, then slot."""
    if sku and sku.strip():
        return f"sku:{sku.strip().lower()}"
    if item_name and item_name.strip():
        return f"item:{item_name.strip().lower()}"
    if slot_id and slot_id.strip():
        return f"slot:{slot_id.strip().lower()}"
    return "unknown"


def _make_oos_finding(
    *,
    settings: Any,
    zh: bool,
    label: str,
    sku: str | None,
    item_name: str | None,
    shelf: str | None,
    planogram_id_str: str | None,
    slot_id: str | None,
    slot_ids: list[str],
    key: str,
    facing_count: int,
    stock: float | None,
    evidence_items: list[dict[str, Any]],
    gap_detected: bool,
) -> Finding:
    """Build the single backroom out_of_stock finding for one SKU.

    Used by BOTH the gap-matched empty-facing path and the planogram-driven path
    (stock <= 0 with no gap detected). The fingerprint is identical in both —
    ``(out_of_stock, planogram_id, sku_key)`` — so whichever path fires first
    opens the ticket and the other dedupes against it: the same out-of-stock SKU
    never produces two tickets. Announcement wording differs slightly depending
    on whether a gap was actually seen on the shelf.
    """
    oos_roles = _roles_for_issue("out_of_stock", settings)
    oos_title = f"缺货：{label}" if zh else f"Out of stock: {label}"
    if gap_detected:
        oos_desc = (
            f"商品「{label}」计划库存为 0（{facing_count} 个 facing 为空）。请后仓补货或订货。"
            if zh
            else f"Item '{label}' planogram stock is 0 "
            f"({facing_count} empty facing(s)). Restock from backroom or reorder."
        )
        announce_desc = (
            f"「{label}」的空位已匹配到计划图，库存为 0，已派单给后仓补货。"
            f"（货架：{shelf or '—'}，{facing_count} 个 facing）"
            if zh
            else f"The empty facing for '{label}' matches the planogram and stock is 0. "
            f"A backroom replenishment ticket has been dispatched. "
            f"(Shelf: {shelf or '—'}, {facing_count} facing(s).)"
        )
    else:
        # Stock exhausted per the planogram even though no gap was detected
        # (last unit still on the shelf, or facing occluded this frame).
        oos_desc = (
            f"商品「{label}」计划库存为 0，需后仓补货或订货（本次未检测到货架空位）。"
            if zh
            else f"Item '{label}' planogram stock is 0 and needs backroom "
            f"replenishment or reorder (no shelf gap was detected this audit)."
        )
        announce_desc = (
            f"「{label}」计划库存为 0，已派单给后仓补货。（货架：{shelf or '—'}）"
            if zh
            else f"'{label}' is out of stock per the planogram; a backroom "
            f"replenishment ticket has been dispatched. (Shelf: {shelf or '—'}.)"
        )
    announce_roles = _roles_for_issue("shelf_empty_announcement", settings)
    announce_title = (
        f"货架空位待补货：{label}" if zh else f"Empty facing awaiting replenishment: {label}"
    )
    return Finding(
        issue_type="out_of_stock",
        priority="critical",
        assignee_role=oos_roles[0],
        assignee_roles=oos_roles,
        title=oos_title,
        description=oos_desc,
        sku=sku,
        item_name=item_name,
        shelf_label=shelf,
        planogram_id=planogram_id_str,
        slot_id=slot_id,
        evidence={
            "outOfStockSlots" if not gap_detected else "missingItems": evidence_items,
            "facingCount": facing_count,
            "planogramStock": stock,
            "slotIds": slot_ids,
            "assigneeRoles": oos_roles,
            "gapDetected": gap_detected,
        },
        fingerprint=_fingerprint("out_of_stock", planogram_id_str, key),
        announce=True,
        announce_title=announce_title,
        announce_description=announce_desc,
        announce_roles=announce_roles,
    )


def extract_findings(
    vision_model_response: dict[str, Any],
    planogram_response: dict[str, Any] | None,
    *,
    language: str = "en",
    source_label: str | None = None,
) -> list[Finding]:
    """Detect shelf issues and decide priority + assignee for each.

    Rules (one circumstance can emit multiple tickets):
    - low_stock → backroom (severity bands on planogram stock)
    - out_of_stock → backroom (planogram stock is 0)
    - shelf_empty → floor_staff (gap facing matches planogram item)
    - camera_issue → floor_staff + manager

    For the same SKU, at most one ticket is opened per issue type.
    """
    settings = load_webhook_settings()
    detections = vision_model_response.get("detections") or []
    if not isinstance(detections, list):
        detections = []
    summary = vision_model_response.get("summary") or {}

    raw_total = summary.get("total")
    if raw_total is None:
        total = len(detections)
    else:
        try:
            total = int(raw_total)
        except (TypeError, ValueError):
            total = len(detections)

    raw_gap = summary.get("gapCount")
    if raw_gap is None and summary.get("gap_count") is not None:
        raw_gap = summary.get("gap_count")
    if raw_gap is None:
        gap_count = sum(
            1
            for item in detections
            if isinstance(item, dict) and _is_gap(str(item.get("label") or ""))
        )
    else:
        try:
            gap_count = int(raw_gap)
        except (TypeError, ValueError):
            gap_count = 0

    raw_product = summary.get("productCount")
    if raw_product is None and summary.get("product_count") is not None:
        raw_product = summary.get("product_count")
    if raw_product is None:
        product_count = max(0, total - gap_count)
    else:
        try:
            product_count = int(raw_product)
        except (TypeError, ValueError):
            product_count = max(0, total - gap_count)

    # Occlusion signal from the vision layer (Plan B). When a customer stands
    # in front of the camera the whole view is "obstructed"; that is NOT a
    # broken camera, so we must not fire camera_issue for it.
    occlusion = vision_model_response.get("occlusion") or {}
    view_obstructed = False
    obscured_count = 0
    if isinstance(occlusion, dict):
        view_obstructed = bool(occlusion.get("viewObstructed"))
    raw_obscured = summary.get("obscuredCount")
    if raw_obscured is not None:
        try:
            obscured_count = int(raw_obscured)
        except (TypeError, ValueError):
            obscured_count = 0

    planogram_id = None
    planogram_name = source_label or ""
    missing_items: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    if planogram_response:
        planogram_id = planogram_response.get("planogramId") or planogram_response.get(
            "planogram_id"
        )
        planogram_name = (
            planogram_response.get("planogramName")
            or planogram_response.get("planogram_name")
            or planogram_name
        )
        missing_items = list(
            planogram_response.get("missingItems")
            or planogram_response.get("missing_items")
            or []
        )
        matches = list(planogram_response.get("matches") or [])
        out_of_stock_slots = list(
            planogram_response.get("outOfStockSlots")
            or planogram_response.get("out_of_stock_slots")
            or []
        )
    else:
        out_of_stock_slots = []

    findings: list[Finding] = []
    zh = language == "zh"
    shelf = str(planogram_name or source_label or "").strip() or None
    planogram_id_str = str(planogram_id) if planogram_id else None

    def _append_planogram_out_of_stock() -> None:
        """Emit backroom OOS findings from planogram ground truth (stock <= 0),
        independent of any gap detection. SKUs already emitted as out_of_stock
        (by the gap-matched path) share the same fingerprint and are skipped, so
        the same SKU never produces two tickets. Safe to call once per run."""
        already_oos_keys = {
            _sku_key(f.sku, f.item_name, f.slot_id)
            for f in findings
            if f.issue_type == "out_of_stock"
        }
        oos_by_sku: dict[str, dict[str, Any]] = {}
        for slot in out_of_stock_slots:
            if not isinstance(slot, dict):
                continue
            oos_name = str(slot.get("itemName") or slot.get("item_name") or "").strip() or None
            oos_sku = str(slot.get("sku") or "").strip() or None
            oos_slot_id = str(slot.get("slotId") or slot.get("slot_id") or "").strip() or None
            if not (oos_name or oos_sku):
                continue
            oos_key = _sku_key(oos_sku, oos_name, oos_slot_id)
            existing = oos_by_sku.get(oos_key)
            if existing is None:
                oos_by_sku[oos_key] = {
                    "sku": oos_sku,
                    "item_name": oos_name,
                    "slot_ids": [oos_slot_id] if oos_slot_id else [],
                    "slots": [slot],
                }
            else:
                if oos_slot_id and oos_slot_id not in existing["slot_ids"]:
                    existing["slot_ids"].append(oos_slot_id)
                existing["slots"].append(slot)
                if not existing["sku"] and oos_sku:
                    existing["sku"] = oos_sku
                if not existing["item_name"] and oos_name:
                    existing["item_name"] = oos_name

        for oos_key, group in oos_by_sku.items():
            if oos_key in already_oos_keys:
                continue  # gap path already emitted OOS for this SKU (same fingerprint)
            g_sku = group["sku"]
            g_item = group["item_name"]
            g_slot_ids = group["slot_ids"]
            g_slot_id = g_slot_ids[0] if g_slot_ids else None
            g_label = g_item or g_sku or g_slot_id or "SKU"
            findings.append(
                _make_oos_finding(
                    settings=settings,
                    zh=zh,
                    label=g_label,
                    sku=g_sku,
                    item_name=g_item,
                    shelf=shelf,
                    planogram_id_str=planogram_id_str,
                    slot_id=g_slot_id,
                    slot_ids=g_slot_ids,
                    key=oos_key,
                    facing_count=len(group["slots"]),
                    stock=0,
                    evidence_items=group["slots"],
                    gap_detected=False,
                )
            )

    # 1) Camera issue — few/no detections.
    # BUT: if the vision layer reports the view is obstructed by motion (a
    # customer standing right in front of the lens), that is transient
    # occlusion, not a broken/misaimed camera. Suppress the finding so a busy
    # store does not spam camera_issue tickets every time someone blocks the view.
    if (total == 0 or (product_count == 0 and gap_count == 0)) and not view_obstructed:
        roles = _roles_for_issue("camera_issue", settings)
        title = "摄像头未检测到商品" if zh else "Camera sees no products"
        desc = (
            "本地视觉模型未检测到商品或空位，请检查摄像头角度、遮挡与光照。"
            if zh
            else "Local vision model detected neither products nor gaps. "
            "Check camera angle, occlusion, and lighting."
        )
        findings.append(
            Finding(
                issue_type="camera_issue",
                priority="high",
                assignee_role=roles[0],
                assignee_roles=roles,
                title=title,
                description=desc,
                shelf_label=shelf,
                planogram_id=planogram_id_str,
                evidence={
                    "total": total,
                    "productCount": product_count,
                    "gapCount": gap_count,
                    "assigneeRoles": roles,
                },
                fingerprint=_fingerprint("camera_issue", planogram_id_str, shelf),
            )
        )
        # Out-of-stock is planogram ground truth and does not depend on the
        # camera: still emit backroom OOS tickets even when vision saw nothing.
        _append_planogram_out_of_stock()
        return findings

    # Aggregate missing facings by SKU so one SKU → one shelf_empty (+ optional OOS).
    missing_by_sku: dict[str, dict[str, Any]] = {}
    for item in missing_items:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("itemName") or item.get("item_name") or "").strip() or None
        sku = str(item.get("sku") or "").strip() or None
        slot_id = str(item.get("slotId") or item.get("slot_id") or "").strip() or None
        stock = _slot_stock(item)
        key = _sku_key(sku, item_name, slot_id)
        existing = missing_by_sku.get(key)
        if existing is None:
            missing_by_sku[key] = {
                "sku": sku,
                "item_name": item_name,
                "slot_ids": [slot_id] if slot_id else [],
                "stocks": [stock] if stock is not None else [],
                "items": [item],
            }
        else:
            if slot_id and slot_id not in existing["slot_ids"]:
                existing["slot_ids"].append(slot_id)
            if stock is not None:
                existing["stocks"].append(stock)
            existing["items"].append(item)
            if not existing["sku"] and sku:
                existing["sku"] = sku
            if not existing["item_name"] and item_name:
                existing["item_name"] = item_name

    for key, group in missing_by_sku.items():
        sku = group["sku"]
        item_name = group["item_name"]
        slot_ids: list[str] = group["slot_ids"]
        stocks: list[float] = group["stocks"]
        stock = min(stocks) if stocks else None
        slot_id = slot_ids[0] if slot_ids else None
        label = item_name or sku or slot_id or "SKU"
        facing_count = len(group["items"])

        # Rule: a gap facing that matches a planogram item with EMPTY stock
        # (planogram stock <= 0) is a backroom replenishment case only.
        #   → open exactly ONE ticket, assigned to backroom (out_of_stock)
        #   → broadcast a store-wide announcement so everyone knows the facing
        #     is empty and awaiting replenishment
        #   → do NOT open a floor_staff shelf_empty ticket
        empty_stock = stock is not None and stock <= 0

        if empty_stock:
            findings.append(
                _make_oos_finding(
                    settings=settings,
                    zh=zh,
                    label=label,
                    sku=sku,
                    item_name=item_name,
                    shelf=shelf,
                    planogram_id_str=planogram_id_str,
                    slot_id=slot_id,
                    slot_ids=slot_ids,
                    key=key,
                    facing_count=facing_count,
                    stock=stock,
                    evidence_items=group["items"],
                    gap_detected=True,
                )
            )
            # Empty-stock facing: only the backroom ticket, no floor_staff ticket.
            continue

        # Otherwise the gap matches a planogram item that still has stock on
        # hand → this is a floor-facing / restock-from-shelf task (floor staff).
        shelf_roles = _roles_for_issue("shelf_empty", settings)
        shelf_title = f"货架空位：{label}" if zh else f"Shelf empty: {label}"
        shelf_desc = (
            f"空位匹配到计划图商品「{label}」（{facing_count} 个 facing）。请现场补货/整理。"
            if zh
            else f"Gap facing(s) match planogram item '{label}' "
            f"({facing_count} facing(s)). Restock / face on the floor."
        )
        if stock is not None:
            shelf_desc += f" 计划库存={stock}." if zh else f" Planogram stock={stock}."
        findings.append(
            Finding(
                issue_type="shelf_empty",
                priority="high",
                assignee_role=shelf_roles[0],
                assignee_roles=shelf_roles,
                title=shelf_title,
                description=shelf_desc,
                sku=sku,
                item_name=item_name,
                shelf_label=shelf,
                planogram_id=planogram_id_str,
                slot_id=slot_id,
                evidence={
                    "missingItems": group["items"],
                    "facingCount": facing_count,
                    "planogramStock": stock,
                    "slotIds": slot_ids,
                    "assigneeRoles": shelf_roles,
                },
                fingerprint=_fingerprint("shelf_empty", planogram_id_str, key),
            )
        )

    # 2b) Out-of-stock from planogram ground truth — independent of any gap.
    # Stock <= 0 is a staff-entered planogram fact, so the backroom
    # replenishment ticket must fire even when the camera detected no gap on the
    # shelf this audit (the last unit may still be sitting there, or the facing
    # may be occluded). SKUs already handled by the gap-matched empty-facing path
    # above share the SAME fingerprint, so they are skipped and deduped at ticket
    # level — the same out-of-stock SKU never opens two tickets.
    _append_planogram_out_of_stock()

    # 3) Low stock — severity bands, one ticket per SKU (min stock across facings).
    low_stock_by_sku: dict[str, dict[str, Any]] = {}
    for match in matches:
        if not isinstance(match, dict):
            continue
        if str(match.get("status") or "").lower() == "gap":
            continue
        slot = match.get("slot") if isinstance(match.get("slot"), dict) else None
        stock = _slot_stock(slot)
        if stock is None or stock <= 0 or stock > LOW_STOCK_WARN_THRESHOLD:
            continue
        item_name = None
        sku = None
        slot_id = None
        if slot:
            item_name = str(slot.get("itemName") or slot.get("item_name") or "").strip() or None
            sku = str(slot.get("sku") or "").strip() or None
            slot_id = str(slot.get("id") or match.get("slotId") or "").strip() or None
        key = _sku_key(sku, item_name, slot_id)
        existing = low_stock_by_sku.get(key)
        if existing is None:
            low_stock_by_sku[key] = {
                "sku": sku,
                "item_name": item_name,
                "slot_id": slot_id,
                "stock": stock,
                "matches": [match],
            }
        else:
            existing["matches"].append(match)
            if stock < existing["stock"]:
                existing["stock"] = stock
                existing["slot_id"] = slot_id or existing["slot_id"]
            if not existing["sku"] and sku:
                existing["sku"] = sku
            if not existing["item_name"] and item_name:
                existing["item_name"] = item_name

    for key, group in low_stock_by_sku.items():
        stock = float(group["stock"])
        sku = group["sku"]
        item_name = group["item_name"]
        slot_id = group["slot_id"]
        label = item_name or sku or slot_id or "SKU"
        # Skip pure low-stock if we already have OOS for this SKU (stock 0 handled above).
        if any(
            f.issue_type == "out_of_stock" and _sku_key(f.sku, f.item_name, f.slot_id) == key
            for f in findings
        ):
            continue

        if stock <= LOW_STOCK_HIGH_THRESHOLD:
            priority: TicketPriority = "high"
            notify_only = False
            issue: IssueKind | str = "low_stock"
            band = "high"
        elif stock <= LOW_STOCK_MEDIUM_THRESHOLD:
            priority = "medium"
            notify_only = False
            issue = "low_stock"
            band = "medium"
        elif stock <= LOW_STOCK_LOW_THRESHOLD:
            priority = "low"
            notify_only = False
            issue = "low_stock"
            band = "low"
        else:
            priority = "low"
            notify_only = True
            issue = "low_stock_warning"
            band = "warning"

        roles = _roles_for_issue("low_stock_warning" if notify_only else "low_stock", settings)
        if notify_only:
            title = f"低库存预警：{label}" if zh else f"Low stock warning: {label}"
            desc = (
                f"商品「{label}」计划库存为 {stock}（≤{LOW_STOCK_WARN_THRESHOLD}），仅推送预警，不创建工单。"
                if zh
                else f"Item '{label}' planogram stock is {stock} (≤{LOW_STOCK_WARN_THRESHOLD}). "
                "Warning notification only — no ticket opened."
            )
        else:
            title = f"低库存：{label}" if zh else f"Low stock: {label}"
            desc = (
                f"商品「{label}」在架，计划库存仅 {stock}（{band} 级别），请安排补货。"
                if zh
                else f"Item '{label}' is on shelf but planogram stock is only {stock} "
                f"({band} severity). Top up soon."
            )

        findings.append(
            Finding(
                issue_type=issue,
                priority=priority,
                assignee_role=roles[0],
                assignee_roles=roles,
                title=title,
                description=desc,
                sku=sku,
                item_name=item_name,
                shelf_label=shelf,
                planogram_id=planogram_id_str,
                slot_id=slot_id,
                evidence={
                    "matches": group["matches"],
                    "facingCount": len(group["matches"]),
                    "planogramStock": stock,
                    "severityBand": band,
                    "assigneeRoles": roles,
                    "thresholds": {
                        "warn": LOW_STOCK_WARN_THRESHOLD,
                        "low": LOW_STOCK_LOW_THRESHOLD,
                        "medium": LOW_STOCK_MEDIUM_THRESHOLD,
                        "high": LOW_STOCK_HIGH_THRESHOLD,
                    },
                },
                fingerprint=_fingerprint(
                    "low_stock_warning" if notify_only else "low_stock",
                    planogram_id_str,
                    key,
                ),
                notify_only=notify_only,
            )
        )

    # 4) Gaps without planogram metadata still become a single generic shelf_empty ticket
    if gap_count > 0 and not missing_items:
        if not any(f.issue_type in ("shelf_empty", "out_of_stock") for f in findings):
            roles = _roles_for_issue("shelf_empty", settings)
            title = f"发现 {gap_count} 个货架空位" if zh else f"{gap_count} shelf gap(s) detected"
            desc = (
                "检测到空位但未匹配到计划图 SKU，请人工核对后补货。"
                if zh
                else "Gaps detected without planogram SKU match. Verify locations and restock."
            )
            findings.append(
                Finding(
                    issue_type="shelf_empty",
                    priority="high",
                    assignee_role=roles[0],
                    assignee_roles=roles,
                    title=title,
                    description=desc,
                    shelf_label=shelf,
                    planogram_id=planogram_id_str,
                    evidence={
                        "gapCount": gap_count,
                        "productCount": product_count,
                        "assigneeRoles": roles,
                    },
                    fingerprint=_fingerprint("shelf_empty", planogram_id_str, "generic-gaps"),
                )
            )

    return findings


def _finding_still_present(
    finding_or_ticket: dict[str, Any] | Ticket,
    vision_model_response: dict[str, Any],
    planogram_response: dict[str, Any] | None,
    *,
    language: str = "en",
) -> tuple[bool, list[Finding]]:
    """Re-run extract_findings and see if the original issue fingerprint reappears."""
    current = extract_findings(
        vision_model_response,
        planogram_response,
        language=language,
        source_label=None,
    )
    if isinstance(finding_or_ticket, Ticket):
        fp = finding_or_ticket.fingerprint
        issue_type = finding_or_ticket.issue_type
        slot_id = finding_or_ticket.slot_id
        sku = finding_or_ticket.sku
    else:
        fp = finding_or_ticket.get("fingerprint")
        issue_type = finding_or_ticket.get("issueType") or finding_or_ticket.get("issue_type")
        slot_id = finding_or_ticket.get("slotId") or finding_or_ticket.get("slot_id")
        sku = finding_or_ticket.get("sku")

    remaining: list[Finding] = []
    for f in current:
        if fp and f.fingerprint == fp:
            remaining.append(f)
            continue
        if issue_type and f.issue_type == issue_type:
            if slot_id and f.slot_id == slot_id:
                remaining.append(f)
                continue
            if sku and f.sku == sku:
                remaining.append(f)
                continue
            if issue_type == "camera_issue" and f.issue_type == "camera_issue":
                remaining.append(f)
                continue
        # Related facing issues: an open OOS ticket still counts as unresolved
        # when the same SKU still has a shelf_empty finding (and vice versa).
        if (
            sku
            and f.sku == sku
            and issue_type in {"out_of_stock", "shelf_empty"}
            and f.issue_type in {"out_of_stock", "shelf_empty"}
        ):
            remaining.append(f)
            continue
    return (len(remaining) > 0, remaining if remaining else current)


# ---------------------------------------------------------------------------
# Closed-loop graph runner
# ---------------------------------------------------------------------------

Stage = Literal["detect", "decide", "dispatch", "verify", "done"]


@dataclass
class LoopState:
    vision: dict[str, Any]
    planogram: dict[str, Any] | None
    language: str = "en"
    source_label: str | None = None
    audit_record_id: str | None = None
    do_dispatch: bool = True
    dedupe: bool = True
    findings: list[Finding] = field(default_factory=list)
    tickets_created: list[Ticket] = field(default_factory=list)
    tickets_updated: list[Ticket] = field(default_factory=list)
    dispatched: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    # Findings held back this pass because they have not yet been observed in
    # enough recent audits (temporal debounce). Not an error — awaiting confirmation.
    debounced: list[dict[str, Any]] = field(default_factory=list)
    # Announcements queued from findings that opened a NEW ticket this pass.
    pending_announcements: list[Finding] = field(default_factory=list)
    narrative: str = ""
    stage: Stage = "detect"


class ClosedLoopAgent:
    """LangGraph-style sequential graph for shelf action tickets."""

    def __init__(
        self,
        settings: Settings | None = None,
        ticket_store: TicketStore | None = None,
        observation_store: ObservationStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._tickets = ticket_store or get_ticket_store()
        self._observations = observation_store or get_observation_store()

    async def run(
        self,
        vision_model_response: dict[str, Any],
        planogram_response: dict[str, Any] | None = None,
        *,
        language: str = "en",
        source_label: str | None = None,
        audit_record_id: str | None = None,
        dispatch: bool = True,
        dedupe: bool = True,
    ) -> ClosedLoopRunResult:
        state = LoopState(
            vision=vision_model_response,
            planogram=planogram_response,
            language=language,
            source_label=source_label,
            audit_record_id=audit_record_id,
            do_dispatch=dispatch,
            dedupe=dedupe,
        )
        # Explicit graph edges: detect → decide → dispatch → done
        state = self._node_detect(state)
        state = self._node_decide(state)
        state = await self._node_dispatch(state)
        state.stage = "done"
        state.narrative = self._build_narrative(state)
        return ClosedLoopRunResult(
            stage=state.stage,
            narrative=state.narrative,
            findings=[f.to_dict() for f in state.findings],
            tickets_created=state.tickets_created,
            tickets_updated=state.tickets_updated,
            dispatched=state.dispatched,
            skipped=state.skipped,
            notifications=state.notifications,
            debounced=state.debounced,
        )

    def _node_detect(self, state: LoopState) -> LoopState:
        state.stage = "detect"
        state.findings = extract_findings(
            state.vision,
            state.planogram,
            language=state.language,
            source_label=state.source_label,
        )
        return state

    def _annotated_image(self, state: LoopState) -> str | None:
        vision = state.vision or {}
        for key in ("annotatedImage", "annotated_image", "imageBase64", "image_base64"):
            value = vision.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _debounce_source_key(self, state: LoopState) -> str:
        """Group observations by shelf/camera so unrelated views don't merge."""
        return str(state.source_label or "").strip()

    def _passes_debounce(self, finding: Finding, state: LoopState) -> bool:
        """Record this observation and decide if the finding is confirmed.

        Returns True when the finding has now been seen in at least
        ``debounce_min_observations`` audits within the trailing window (so it
        may open a ticket), or when debounce is disabled. When it returns False
        the finding is held back and logged to ``state.debounced``.
        """
        min_obs = getattr(self._settings, "debounce_min_observations", 1) or 1
        # No fingerprint or debounce disabled → open immediately (legacy behavior).
        if min_obs <= 1 or not finding.fingerprint:
            return True
        # Out-of-stock is planogram ground truth (staff-entered stock), not a
        # flaky vision reading subject to occlusion / transient false positives.
        # It must fire immediately on confirmation — debounce/persistence gating
        # only applies to vision-derived findings (gaps, camera issues).
        if str(finding.issue_type) == "out_of_stock":
            return True

        window = getattr(self._settings, "debounce_window_seconds", 180)
        retention = getattr(self._settings, "debounce_retention_seconds", 1800)
        min_span = getattr(self._settings, "debounce_min_span_seconds", 0) or 0
        source_key = self._debounce_source_key(state)

        # Record this observation first, then count (so the current pass counts).
        try:
            self._observations.record(
                finding.fingerprint,
                str(finding.issue_type),
                source_key=source_key,
                retention_seconds=retention,
            )
            seen = self._observations.count_recent(
                finding.fingerprint,
                window_seconds=window,
                source_key=source_key,
            )
            # Wall-clock persistence: how long has this finding actually spanned?
            span = (
                self._observations.span_seconds(
                    finding.fingerprint,
                    window_seconds=window,
                    source_key=source_key,
                )
                if min_span > 0
                else 0.0
            )
        except Exception:  # pragma: no cover - never break the audit on debounce
            return True

        # Confirmed only when the finding has been seen enough times AND (when a
        # minimum span is configured) has persisted across enough wall-clock
        # time. A slow walker / lingerer can satisfy the count with a couple of
        # quick audits but will not persist at the same facing long enough to
        # clear the span gate.
        if seen >= min_obs and (min_span <= 0 or span >= min_span):
            return True

        pending: dict[str, Any] = {
            "issueType": finding.issue_type,
            "title": finding.title,
            "fingerprint": finding.fingerprint,
            "observations": seen,
            "required": min_obs,
            "windowSeconds": window,
        }
        if min_span > 0:
            pending["spanSeconds"] = round(span, 1)
            pending["requiredSpanSeconds"] = min_span
        state.debounced.append(pending)
        return False

    def _node_decide(self, state: LoopState) -> LoopState:
        """Create or refresh tickets from findings (priority already decided)."""
        state.stage = "decide"
        for finding in state.findings:
            if finding.notify_only:
                # Warning-only findings are handled at dispatch time.
                continue
            existing: Ticket | None = None
            if state.dedupe and finding.fingerprint:
                existing = self._tickets.find_open_by_fingerprint(finding.fingerprint)
            if existing is not None:
                updated = self._tickets.merge_evidence(
                    existing.id,
                    {
                        "lastFinding": finding.to_dict(),
                        "lastVisionSummary": state.vision.get("summary"),
                        "auditRecordId": state.audit_record_id,
                        "annotatedImage": self._annotated_image(state),
                    },
                )
                if updated:
                    note = "Finding re-detected; evidence refreshed."
                    if state.language == "zh":
                        note = "问题再次被检测到，已更新证据。"
                    refreshed = self._tickets.append_history(
                        existing.id,
                        "re_detected",
                        note=note,
                        priority=finding.priority,
                    )
                    if refreshed:
                        state.tickets_updated.append(refreshed)
                    else:
                        state.tickets_updated.append(updated)
                continue

            # Temporal debounce (Plan C): before opening a NEW ticket, require
            # the finding to have been observed in at least
            # ``debounce_min_observations`` audits inside the trailing window.
            # A customer walking past produces a gap for one snapshot that
            # vanishes next audit → never reaches the threshold → filtered.
            if not self._passes_debounce(finding, state):
                continue

            ticket = self._tickets.create(
                issue_type=finding.issue_type,  # type: ignore[arg-type]
                priority=finding.priority,
                assignee_role=finding.assignee_role,
                title=finding.title,
                description=finding.description,
                sku=finding.sku,
                item_name=finding.item_name,
                shelf_label=finding.shelf_label,
                planogram_id=finding.planogram_id,
                slot_id=finding.slot_id,
                audit_record_id=state.audit_record_id,
                evidence={
                    "finding": finding.to_dict(),
                    "visionSummary": state.vision.get("summary"),
                    "annotatedImage": self._annotated_image(state),
                    "assigneeRoles": list(finding.assignee_roles or [finding.assignee_role]),
                    "language": state.language,
                },
                fingerprint=finding.fingerprint,
                status="open",
                note="Created by closed-loop agent",
            )
            state.tickets_created.append(ticket)
            # Only broadcast an announcement the first time a ticket is opened
            # for this problem (new ticket, not a dedupe re-detection), so the
            # same empty facing is never announced more than once while the
            # backroom ticket stays open.
            if finding.announce:
                state.pending_announcements.append(finding)
        return state

    async def _node_dispatch(self, state: LoopState) -> LoopState:
        state.stage = "dispatch"
        settings = load_webhook_settings()
        annotated = self._annotated_image(state)

        # Warning-only notifications (no ticket).
        for finding in state.findings:
            if not finding.notify_only:
                continue
            if not state.do_dispatch:
                state.skipped.append(
                    {
                        "reason": "dispatch_disabled",
                        "issueType": finding.issue_type,
                        "title": finding.title,
                    }
                )
                continue
            result = await dispatch_notification(
                title=finding.title,
                description=finding.description,
                issue_type=finding.issue_type,
                priority=finding.priority,
                assignee_role=finding.assignee_role,
                assignee_roles=list(finding.assignee_roles or [finding.assignee_role]),
                sku=finding.sku,
                item_name=finding.item_name,
                shelf_label=finding.shelf_label,
                annotated_image=annotated,
                settings=settings,
                evidence={**(finding.evidence or {}), "language": state.language},
                language=state.language,
            )
            state.notifications.append(result)

        # Store-wide announcements for newly-opened empty-facing tickets.
        # These are broadcast to the announcement channel (not a ticket) so the
        # whole store knows an empty facing is awaiting backroom replenishment.
        for finding in state.pending_announcements:
            if not state.do_dispatch:
                state.skipped.append(
                    {
                        "reason": "dispatch_disabled",
                        "issueType": "shelf_empty_announcement",
                        "title": finding.announce_title or finding.title,
                    }
                )
                continue
            roles = list(finding.announce_roles or ["announcement"])
            result = await dispatch_notification(
                title=finding.announce_title or finding.title,
                description=finding.announce_description or finding.description,
                issue_type="shelf_empty_announcement",
                priority=finding.priority,
                assignee_role=roles[0],
                assignee_roles=roles,
                sku=finding.sku,
                item_name=finding.item_name,
                shelf_label=finding.shelf_label,
                annotated_image=annotated,
                settings=settings,
                evidence={
                    "announcement": True,
                    "backroomTicketFingerprint": finding.fingerprint,
                    "language": state.language,
                },
                language=state.language,
            )
            state.notifications.append(result)

        if not state.do_dispatch:
            for ticket in state.tickets_created:
                state.skipped.append(
                    {"ticketId": ticket.id, "reason": "dispatch_disabled"}
                )
            return state

        to_dispatch = list(state.tickets_created)
        # Also re-dispatch escalated tickets that were refreshed.
        for ticket in state.tickets_updated:
            if ticket.status in ("open", "escalated"):
                to_dispatch.append(ticket)

        seen: set[str] = set()
        for ticket in to_dispatch:
            if ticket.id in seen:
                continue
            seen.add(ticket.id)
            # Prefer shelf label from ticket; fall back to planogram name / source.
            shelf = ticket.shelf_label or state.source_label
            image = None
            if isinstance(ticket.evidence, dict):
                image = ticket.evidence.get("annotatedImage") or ticket.evidence.get(
                    "annotated_image"
                )
            image = image or annotated
            result = await dispatch_ticket(
                ticket,
                settings,
                annotated_image=image if isinstance(image, str) else None,
                shelf_label=shelf,
                language=state.language,
            )
            if result.get("ok"):
                endpoint_name = result.get("endpointName") or result.get("channel")
                updated = self._tickets.update_status(
                    ticket.id,
                    "dispatched",
                    note=f"Dispatched via {result.get('channel')}/{endpoint_name}",
                    extra_evidence={"lastDispatch": result},
                )
                state.dispatched.append(result)
                if updated:
                    for i, created in enumerate(state.tickets_created):
                        if created.id == ticket.id:
                            state.tickets_created[i] = updated
            else:
                state.skipped.append(result)
                self._tickets.append_history(
                    ticket.id,
                    "dispatch_failed",
                    note=result.get("error") or "dispatch failed",
                    channel=result.get("channel"),
                    endpoint=result.get("endpointName"),
                )
        return state

    def _build_narrative(self, state: LoopState) -> str:
        zh = state.language == "zh"
        if not state.findings:
            return (
                "未发现需要派工的问题，货架状态正常。"
                if zh
                else "No actionable shelf issues found. Shelf looks healthy."
            )
        created = len(state.tickets_created)
        updated = len(state.tickets_updated)
        dispatched = len(state.dispatched)
        warnings = sum(1 for f in state.findings if f.notify_only)
        pending = len(state.debounced)
        parts = [
            (
                f"检测到 {len(state.findings)} 个问题；新建工单 {created}，更新 {updated}，"
                f"已派发 {dispatched}，预警通知 {warnings}，待确认 {pending}。"
                if zh
                else f"Detected {len(state.findings)} issue(s); created {created} ticket(s), "
                f"updated {updated}, dispatched {dispatched}, warnings {warnings}, "
                f"awaiting confirmation {pending}."
            )
        ]
        for pending_item in state.debounced[:3]:
            seen = pending_item.get("observations")
            need = pending_item.get("required")
            title = pending_item.get("title") or pending_item.get("issueType")
            span = pending_item.get("spanSeconds")
            need_span = pending_item.get("requiredSpanSeconds")
            if span is not None and need_span:
                span_note = (
                    f"，持续 {span}/{need_span}s" if zh else f", spanning {span}/{need_span}s"
                )
            else:
                span_note = ""
            if zh:
                parts.append(f"- [待确认 {seen}/{need}{span_note}] {title}")
            else:
                parts.append(f"- [pending {seen}/{need}{span_note}] {title}")
        for finding in state.findings[:5]:
            suffix = " (warn)" if finding.notify_only else f" → {finding.assignee_role}"
            parts.append(f"- [{finding.priority}] {finding.title}{suffix}")
        if len(state.findings) > 5:
            extra = len(state.findings) - 5
            parts.append(
                f"- …另有 {extra} 项" if zh else f"- …and {extra} more"
            )
        return "\n".join(parts)

    async def verify(
        self,
        ticket_id: str,
        vision_model_response: dict[str, Any],
        planogram_response: dict[str, Any] | None = None,
        *,
        language: str = "en",
        source_label: str | None = None,
    ) -> VerifyTicketResult:
        """After ticket is marked done, re-scan and confirm gap closed or escalate."""
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            raise KeyError(ticket_id)

        still_present, remaining = _finding_still_present(
            ticket,
            vision_model_response,
            planogram_response,
            language=language,
        )
        zh = language == "zh"

        if not still_present:
            updated = self._tickets.update_status(
                ticket_id,
                "verified",
                note="Re-scan confirms issue resolved."
                if not zh
                else "复检确认问题已解决。",
                extra_evidence={
                    "verifyVisionSummary": vision_model_response.get("summary"),
                    "verifySource": source_label,
                    "remainingIssues": [],
                },
            )
            assert updated is not None
            # Optional success ping is intentional no-op when webhooks disabled.
            narrative = (
                f"工单 {ticket_id} 已验证关闭。"
                if zh
                else f"Ticket {ticket_id} verified closed."
            )
            return VerifyTicketResult(
                ticket=updated,
                verified=True,
                escalated=False,
                narrative=narrative,
                remaining_issues=[],
            )

        # Still present → escalate to manager and re-dispatch
        note = (
            "复检后问题仍在，已升级至店长。"
            if zh
            else "Issue still present after re-scan; escalated to manager."
        )
        escalated = self._tickets.escalate(
            ticket_id,
            note=note,
            assignee_role="manager",
            priority="critical",
        )
        assert escalated is not None
        escalated = self._tickets.merge_evidence(
            ticket_id,
            {
                "verifyVisionSummary": vision_model_response.get("summary"),
                "verifySource": source_label,
                "remainingIssues": [f.to_dict() for f in remaining],
            },
        ) or escalated

        settings = load_webhook_settings()
        dispatch_result = await dispatch_ticket(escalated, settings, language=language)
        self._tickets.append_history(
            ticket_id,
            "re_dispatched_after_verify",
            note=json.dumps(dispatch_result, ensure_ascii=False)[:500],
        )
        refreshed = self._tickets.get(ticket_id) or escalated
        narrative = (
            f"工单 {ticket_id} 复检未通过，已升级并重新派发。"
            if zh
            else f"Ticket {ticket_id} failed verification; escalated and re-dispatched."
        )
        return VerifyTicketResult(
            ticket=refreshed,
            verified=False,
            escalated=True,
            narrative=narrative,
            remaining_issues=[f.to_dict() for f in remaining],
        )


_loop_agent: ClosedLoopAgent | None = None


def get_closed_loop_agent() -> ClosedLoopAgent:
    global _loop_agent
    if _loop_agent is None:
        _loop_agent = ClosedLoopAgent()
    return _loop_agent


def reset_closed_loop_agent() -> None:
    global _loop_agent
    _loop_agent = None

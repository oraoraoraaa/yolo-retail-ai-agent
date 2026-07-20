"""Match vision detections to user-drawn planogram rectangles."""

from __future__ import annotations

from typing import Any

from app.schemas.planogram import Planogram, PlanogramMatchResult, PlanogramSlot


def _slot_to_dict(slot: PlanogramSlot | None) -> dict[str, Any] | None:
    if slot is None:
        return None
    return {
        "id": slot.id,
        "x": slot.x,
        "y": slot.y,
        "width": slot.width,
        "height": slot.height,
        "itemName": slot.item_name,
        "itemPrice": slot.item_price,
        "itemStock": slot.item_stock,
        "sku": slot.sku,
        "notes": slot.notes,
    }


def _detection_center(detection: dict[str, Any]) -> tuple[float, float] | None:
    """Return normalized (cx, cy) in [0, 1] when available."""
    normalized = detection.get("normalizedBox") or detection.get("normalized_box")
    if isinstance(normalized, dict):
        try:
            x1 = float(normalized.get("x1", 0.0))
            y1 = float(normalized.get("y1", 0.0))
            x2 = float(normalized.get("x2", 1.0))
            y2 = float(normalized.get("y2", 1.0))
            return (x1 + x2) / 2.0, (y1 + y2) / 2.0
        except (TypeError, ValueError):
            return None

    box = detection.get("box")
    image = detection.get("image")
    if not isinstance(box, dict):
        return None
    try:
        x1 = float(box.get("x1", 0.0))
        y1 = float(box.get("y1", 0.0))
        x2 = float(box.get("x2", 0.0))
        y2 = float(box.get("y2", 0.0))
    except (TypeError, ValueError):
        return None

    width = float((image or {}).get("width") or detection.get("imageWidth") or 0)
    height = float((image or {}).get("height") or detection.get("imageHeight") or 0)
    if width <= 0 or height <= 0:
        return None
    return ((x1 + x2) / 2.0) / width, ((y1 + y2) / 2.0) / height


def _contains(slot: PlanogramSlot, cx: float, cy: float) -> bool:
    return (
        slot.x <= cx <= slot.x + slot.width
        and slot.y <= cy <= slot.y + slot.height
    )


def _slot_area(slot: PlanogramSlot) -> float:
    return max(0.0, slot.width) * max(0.0, slot.height)


def _find_slot(slots: list[PlanogramSlot], cx: float, cy: float) -> PlanogramSlot | None:
    """Pick the smallest drawn slot that contains the detection center."""
    candidates = [slot for slot in slots if _contains(slot, cx, cy)]
    if not candidates:
        return None
    return min(candidates, key=_slot_area)


def _is_gap_label(label: str) -> bool:
    lowered = label.strip().lower()
    return "gap" in lowered or "empty" in lowered or "缺" in lowered or "空" in lowered


def _slot_center(slot: PlanogramSlot) -> tuple[float, float]:
    return slot.x + slot.width / 2.0, slot.y + slot.height / 2.0


def _point_in_region(region: dict[str, Any], cx: float, cy: float) -> bool:
    try:
        x1 = float(region.get("x1", 0.0))
        y1 = float(region.get("y1", 0.0))
        x2 = float(region.get("x2", 0.0))
        y2 = float(region.get("y2", 0.0))
    except (TypeError, ValueError):
        return False
    lo_x, hi_x = min(x1, x2), max(x1, x2)
    lo_y, hi_y = min(y1, y2), max(y1, y2)
    return lo_x <= cx <= hi_x and lo_y <= cy <= hi_y


def match_planogram(
    planogram: Planogram,
    vision_model_response: dict[str, Any],
) -> PlanogramMatchResult:
    """Map each detection center onto a user-drawn planogram rectangle.

    Occlusion-aware: a gap detection flagged ``obscured`` by the vision layer
    (its box overlaps the motion mask — likely a customer, not an empty facing)
    is reported with ``status="obscured"`` and never enters ``missing_items``,
    so it cannot open a false replenishment ticket. Slots whose center falls
    inside a reported occlusion region are likewise treated as obscured even
    when the model produced no detection there (a fully covered facing).
    """
    detections = vision_model_response.get("detections") or []
    image = vision_model_response.get("image") or {}
    image_width = image.get("width")
    image_height = image.get("height")
    occlusion = vision_model_response.get("occlusion") or {}
    occlusion_regions = (
        occlusion.get("regions") if isinstance(occlusion, dict) else None
    ) or []
    slots = list(planogram.slots)

    matches: list[dict[str, Any]] = []
    gap_matches: list[dict[str, Any]] = []
    missing_by_id: dict[str, dict[str, Any]] = {}
    obscured_slot_ids: set[str] = set()
    obscured_matches: list[dict[str, Any]] = []

    for detection in detections:
        if not isinstance(detection, dict):
            continue
        label = str(detection.get("label") or "")
        enriched = dict(detection)
        if image_width and image_height:
            enriched.setdefault("imageWidth", image_width)
            enriched.setdefault("imageHeight", image_height)
            enriched.setdefault("image", image)

        center = _detection_center(enriched)
        if center is None:
            continue
        slot = _find_slot(slots, center[0], center[1])
        is_gap = _is_gap_label(label)
        is_obscured = bool(detection.get("obscured"))
        if is_gap and is_obscured:
            status = "obscured"
        elif is_gap:
            status = "gap"
        else:
            status = "product"
        entry = {
            "detectionLabel": label,
            "confidence": detection.get("confidence"),
            "slotId": slot.id if slot else None,
            "center": {"x": center[0], "y": center[1]},
            "slot": _slot_to_dict(slot),
            "status": status,
            "obscured": is_obscured,
        }
        matches.append(entry)
        if status == "obscured":
            obscured_matches.append(entry)
            if slot:
                obscured_slot_ids.add(slot.id)
            continue
        if is_gap:
            gap_matches.append(entry)
            if slot and (slot.item_name or slot.sku):
                missing_by_id[slot.id] = {
                    "slotId": slot.id,
                    "x": slot.x,
                    "y": slot.y,
                    "width": slot.width,
                    "height": slot.height,
                    "itemName": slot.item_name,
                    "itemPrice": slot.item_price,
                    "itemStock": slot.item_stock,
                    "sku": slot.sku,
                    "notes": slot.notes,
                    "confidence": detection.get("confidence"),
                }

    # Slots fully covered by a customer produce no detection of their own; mark
    # any slot whose center falls inside an occlusion region as obscured so a
    # blocked facing is never mistaken for an empty one.
    for slot in slots:
        if slot.id in obscured_slot_ids:
            continue
        cx, cy = _slot_center(slot)
        if any(_point_in_region(region, cx, cy) for region in occlusion_regions):
            obscured_slot_ids.add(slot.id)
            obscured_matches.append(
                {
                    "detectionLabel": "",
                    "confidence": None,
                    "slotId": slot.id,
                    "center": {"x": cx, "y": cy},
                    "slot": _slot_to_dict(slot),
                    "status": "obscured",
                    "obscured": True,
                }
            )

    # Never report a slot as missing if it is currently obscured.
    for slot_id in obscured_slot_ids:
        missing_by_id.pop(slot_id, None)

    missing_items = list(missing_by_id.values())

    # Out-of-stock is planogram ground truth (staff-entered stock), independent
    # of what the camera sees this frame: any slot with stock <= 0 needs a
    # backroom replenishment ticket even when no gap was detected (the last unit
    # may still be on the shelf, or the facing may be occluded). Surface every
    # such slot so the decision layer can open the ticket from planogram data.
    out_of_stock_slots: list[dict[str, Any]] = []
    for slot in slots:
        stock = slot.item_stock
        if stock is None or stock > 0:
            continue
        if not (slot.item_name or slot.sku):
            continue  # unlabeled facing — nothing actionable to replenish
        out_of_stock_slots.append(
            {
                "slotId": slot.id,
                "x": slot.x,
                "y": slot.y,
                "width": slot.width,
                "height": slot.height,
                "itemName": slot.item_name,
                "itemPrice": slot.item_price,
                "itemStock": slot.item_stock,
                "sku": slot.sku,
                "notes": slot.notes,
            }
        )
    obscured_suffix = (
        f" {len(obscured_slot_ids)} facing(s) obscured (skipped)."
        if obscured_slot_ids
        else ""
    )
    if missing_items:
        names = ", ".join(
            item["itemName"] or item["sku"] or item["slotId"] for item in missing_items
        )
        summary = (
            f"Matched {len(gap_matches)} gap(s) to planogram '{planogram.name}'. "
            f"Likely missing: {names}.{obscured_suffix}"
        )
    elif gap_matches:
        summary = (
            f"Matched {len(gap_matches)} gap(s) on planogram '{planogram.name}', "
            f"but those regions have no assigned SKU metadata.{obscured_suffix}"
        )
    elif obscured_slot_ids:
        summary = (
            f"No confirmed gaps on planogram '{planogram.name}'."
            f"{obscured_suffix}"
        )
    else:
        summary = f"No gaps matched against planogram '{planogram.name}'."

    return PlanogramMatchResult(
        planogram_id=planogram.id,
        planogram_name=planogram.name,
        slot_count=len(slots),
        matches=matches,
        gap_matches=gap_matches,
        missing_items=missing_items,
        obscured_matches=obscured_matches,
        out_of_stock_slots=out_of_stock_slots,
        summary=summary,
    )

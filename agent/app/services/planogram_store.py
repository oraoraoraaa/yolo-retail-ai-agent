"""In-memory planogram store.

Planograms map user-drawn shelf regions to expected SKUs. Persistence is
intentionally process-local for now; swap this for a real database later.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from itertools import count

from app.schemas.planogram import Planogram, PlanogramCreate, PlanogramSlot, PlanogramUpdate


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize_slots(slots: list[PlanogramSlot]) -> list[PlanogramSlot]:
    """Normalize drawn rectangles and drop degenerate boxes."""
    normalized: list[PlanogramSlot] = []
    seen_ids: set[str] = set()
    for index, slot in enumerate(slots):
        x = _clamp01(slot.x)
        y = _clamp01(slot.y)
        width = max(0.0, float(slot.width))
        height = max(0.0, float(slot.height))
        # Allow drawing past the right/bottom edge by clamping extent.
        if x + width > 1.0:
            width = 1.0 - x
        if y + height > 1.0:
            height = 1.0 - y
        if width < 0.005 or height < 0.005:
            continue
        slot_id = (slot.id or "").strip() or f"slot-{index + 1}"
        # Keep ids unique within one planogram.
        base = slot_id
        suffix = 2
        while slot_id in seen_ids:
            slot_id = f"{base}-{suffix}"
            suffix += 1
        seen_ids.add(slot_id)
        normalized.append(
            PlanogramSlot(
                id=slot_id,
                x=x,
                y=y,
                width=width,
                height=height,
                item_name=slot.item_name.strip(),
                item_price=slot.item_price,
                item_stock=max(0, int(slot.item_stock)),
                sku=slot.sku.strip(),
                notes=slot.notes.strip(),
            )
        )
    # Stable order: top-to-bottom, then left-to-right.
    return sorted(normalized, key=lambda item: (item.y, item.x, item.id))


class PlanogramStore:
    """Thread-safe, in-memory collection of planograms."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._planograms: dict[str, Planogram] = {}
        self._counter = count(1)
        self._active_id: str | None = None
        self._seed()

    def _seed(self) -> None:
        """Seed a demo beverage aisle planogram for offline demos."""
        # 3×4 facing layout as freehand rectangles (not auto grid generation).
        labels = [
            ("Brand Y Soda 330ml", 1.29, 24, "BY-SODA-330"),
            ("Sparkling Water 500ml", 0.99, 18, "SW-500"),
            ("Cola Classic 330ml", 1.19, 30, "CC-330"),
            ("Orange Juice 1L", 2.49, 12, "OJ-1L"),
            ("Iced Tea Lemon 500ml", 1.49, 16, "IT-LEM-500"),
            ("Energy Drink 250ml", 1.99, 20, "ED-250"),
            ("Still Water 500ml", 0.79, 40, "W-500"),
            ("Sports Drink 500ml", 1.59, 14, "SD-500"),
            ("Coffee Can 240ml", 1.69, 10, "CF-240"),
            ("Milk 1L", 1.89, 8, "MK-1L"),
            ("Yogurt Drink 200ml", 1.09, 15, "YD-200"),
            ("Vitamin Water 500ml", 1.79, 11, "VW-500"),
        ]
        slots: list[PlanogramSlot] = []
        for index, (name, price, stock, sku) in enumerate(labels):
            row = index // 4
            col = index % 4
            slots.append(
                PlanogramSlot(
                    id=f"slot-{index + 1:02d}",
                    x=col * 0.25 + 0.01,
                    y=row * (1.0 / 3.0) + 0.01,
                    width=0.23,
                    height=(1.0 / 3.0) - 0.02,
                    item_name=name,
                    item_price=price,
                    item_stock=stock,
                    sku=sku,
                )
            )
        demo = Planogram(
            id="plan-0001",
            name="Aisle 3 · Beverages",
            description="Demo planogram with freehand facing rectangles (seed).",
            image_base64="",
            image_width=0,
            image_height=0,
            slots=slots,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self._planograms[demo.id] = demo
        self._active_id = demo.id
        next(self._counter)

    def list(self) -> list[Planogram]:
        with self._lock:
            return sorted(self._planograms.values(), key=lambda item: item.updated_at, reverse=True)

    def get(self, planogram_id: str) -> Planogram | None:
        with self._lock:
            return self._planograms.get(planogram_id)

    def get_active_id(self) -> str | None:
        with self._lock:
            return self._active_id

    def set_active(self, planogram_id: str | None) -> str | None:
        with self._lock:
            if planogram_id is None:
                self._active_id = None
                return None
            if planogram_id not in self._planograms:
                raise KeyError(planogram_id)
            self._active_id = planogram_id
            return self._active_id

    def create(self, payload: PlanogramCreate) -> Planogram:
        with self._lock:
            planogram_id = f"plan-{next(self._counter):04d}"
            now = _now_iso()
            planogram = Planogram(
                id=planogram_id,
                name=payload.name.strip() or f"Planogram {planogram_id}",
                description=payload.description.strip(),
                image_base64=payload.image_base64,
                image_width=payload.image_width,
                image_height=payload.image_height,
                slots=_normalize_slots(payload.slots),
                created_at=now,
                updated_at=now,
            )
            self._planograms[planogram_id] = planogram
            if self._active_id is None:
                self._active_id = planogram_id
            return planogram

    def update(self, planogram_id: str, payload: PlanogramUpdate) -> Planogram:
        with self._lock:
            existing = self._planograms.get(planogram_id)
            if existing is None:
                raise KeyError(planogram_id)

            updated = Planogram(
                id=existing.id,
                name=(payload.name.strip() if payload.name is not None else existing.name) or existing.name,
                description=(
                    payload.description.strip()
                    if payload.description is not None
                    else existing.description
                ),
                image_base64=(
                    payload.image_base64 if payload.image_base64 is not None else existing.image_base64
                ),
                image_width=(
                    payload.image_width if payload.image_width is not None else existing.image_width
                ),
                image_height=(
                    payload.image_height if payload.image_height is not None else existing.image_height
                ),
                slots=(
                    _normalize_slots(payload.slots)
                    if payload.slots is not None
                    else _normalize_slots(existing.slots)
                ),
                created_at=existing.created_at,
                updated_at=_now_iso(),
            )
            self._planograms[planogram_id] = updated
            return updated

    def delete(self, planogram_id: str) -> None:
        with self._lock:
            if planogram_id not in self._planograms:
                raise KeyError(planogram_id)
            del self._planograms[planogram_id]
            if self._active_id == planogram_id:
                self._active_id = next(iter(self._planograms), None)


_store: PlanogramStore | None = None


def get_planogram_store() -> PlanogramStore:
    """Return the process-wide planogram store singleton."""
    global _store
    if _store is None:
        _store = PlanogramStore()
    return _store


def reset_planogram_store() -> None:
    """Clear the singleton (tests)."""
    global _store
    _store = None

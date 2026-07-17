"""Persistent planogram store (SQLAlchemy).

Planograms map user-drawn shelf regions to expected SKUs. Images are stored on
disk under the media root when provided as base64; slots live as JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import count

from sqlalchemy import func, select

from app.db.models import AppSettingRow, PlanogramRow
from app.db.session import get_engine, get_session
from app.schemas.planogram import Planogram, PlanogramCreate, PlanogramSlot, PlanogramUpdate
from app.services.media import delete_image_ref, media_url_for, save_image_base64

ACTIVE_SETTING_KEY = "active_planogram_id"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    if value is None:
        return _now().isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


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


def _slots_to_json(slots: list[PlanogramSlot]) -> list[dict]:
    return [slot.model_dump(by_alias=True) for slot in slots]


def _slots_from_json(raw: object) -> list[PlanogramSlot]:
    if not isinstance(raw, list):
        return []
    slots: list[PlanogramSlot] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            slots.append(PlanogramSlot.model_validate(item))
        except Exception:
            continue
    return _normalize_slots(slots)


def _row_to_planogram(row: PlanogramRow) -> Planogram:
    return Planogram(
        id=row.id,
        name=row.name,
        description=row.description or "",
        image_base64=row.image_base64 or "",
        image_width=row.image_width or 0,
        image_height=row.image_height or 0,
        image_ref=row.image_ref,
        image_url=media_url_for(row.image_ref),
        slots=_slots_from_json(row.slots_json),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


class PlanogramStore:
    """SQL-backed collection of planograms."""

    def __init__(self) -> None:
        get_engine()
        self._counter = count(self._next_counter_start())
        self._seed_if_empty()

    def _next_counter_start(self) -> int:
        with get_session() as session:
            ids = session.scalars(select(PlanogramRow.id)).all()
        max_n = 0
        for plan_id in ids:
            if isinstance(plan_id, str) and plan_id.startswith("plan-"):
                suffix = plan_id[5:]
                if suffix.isdigit():
                    max_n = max(max_n, int(suffix))
        return max_n + 1

    def _get_setting(self, session, key: str) -> str | None:
        row = session.get(AppSettingRow, key)
        return row.value if row else None

    def _set_setting(self, session, key: str, value: str | None) -> None:
        if value is None:
            existing = session.get(AppSettingRow, key)
            if existing is not None:
                session.delete(existing)
            return
        existing = session.get(AppSettingRow, key)
        if existing is None:
            session.add(AppSettingRow(key=key, value=value))
        else:
            existing.value = value

    def _seed_if_empty(self) -> None:
        """Seed a demo beverage aisle planogram for offline demos."""
        with get_session() as session:
            count_rows = session.scalar(select(func.count()).select_from(PlanogramRow)) or 0
            if count_rows > 0:
                return

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
            plan_id = f"plan-{next(self._counter):04d}"
            now = _now()
            session.add(
                PlanogramRow(
                    id=plan_id,
                    name="Aisle 3 · Beverages",
                    description="Demo planogram with freehand facing rectangles (seed).",
                    image_base64="",
                    image_width=0,
                    image_height=0,
                    slots_json=_slots_to_json(slots),
                    created_at=now,
                    updated_at=now,
                )
            )
            self._set_setting(session, ACTIVE_SETTING_KEY, plan_id)

    def list(self) -> list[Planogram]:
        with get_session() as session:
            rows = session.scalars(select(PlanogramRow).order_by(PlanogramRow.updated_at.desc())).all()
            return [_row_to_planogram(row) for row in rows]

    def get(self, planogram_id: str) -> Planogram | None:
        with get_session() as session:
            row = session.get(PlanogramRow, planogram_id)
            return _row_to_planogram(row) if row else None

    def get_active_id(self) -> str | None:
        with get_session() as session:
            return self._get_setting(session, ACTIVE_SETTING_KEY)

    def set_active(self, planogram_id: str | None) -> str | None:
        with get_session() as session:
            if planogram_id is None:
                self._set_setting(session, ACTIVE_SETTING_KEY, None)
                return None
            if session.get(PlanogramRow, planogram_id) is None:
                raise KeyError(planogram_id)
            self._set_setting(session, ACTIVE_SETTING_KEY, planogram_id)
            return planogram_id

    def create(self, payload: PlanogramCreate) -> Planogram:
        planogram_id = f"plan-{next(self._counter):04d}"
        now = _now()
        image_ref = None
        image_base64 = payload.image_base64 or ""
        if image_base64:
            image_ref = save_image_base64("planograms", image_base64, stem=planogram_id)
            # Prefer disk ref; keep a short placeholder so API still has a truthy image flag
            # without re-storing multi-MB base64 in the DB when we have a file.
            if image_ref and len(image_base64) > 200_000:
                image_base64 = ""

        slots = _normalize_slots(payload.slots)
        with get_session() as session:
            row = PlanogramRow(
                id=planogram_id,
                name=payload.name.strip() or f"Planogram {planogram_id}",
                description=payload.description.strip(),
                image_ref=image_ref,
                image_base64=image_base64,
                image_width=payload.image_width,
                image_height=payload.image_height,
                slots_json=_slots_to_json(slots),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            if self._get_setting(session, ACTIVE_SETTING_KEY) is None:
                self._set_setting(session, ACTIVE_SETTING_KEY, planogram_id)
            session.flush()
            return _row_to_planogram(row)

    def update(self, planogram_id: str, payload: PlanogramUpdate) -> Planogram:
        with get_session() as session:
            existing = session.get(PlanogramRow, planogram_id)
            if existing is None:
                raise KeyError(planogram_id)

            if payload.name is not None:
                existing.name = payload.name.strip() or existing.name
            if payload.description is not None:
                existing.description = payload.description.strip()
            if payload.image_width is not None:
                existing.image_width = payload.image_width
            if payload.image_height is not None:
                existing.image_height = payload.image_height
            if payload.slots is not None:
                existing.slots_json = _slots_to_json(_normalize_slots(payload.slots))
            if payload.image_base64 is not None:
                image_base64 = payload.image_base64
                previous_ref = existing.image_ref
                image_ref = save_image_base64("planograms", image_base64, stem=planogram_id) if image_base64 else None
                existing.image_ref = image_ref
                if image_ref and len(image_base64) > 200_000:
                    existing.image_base64 = ""
                else:
                    existing.image_base64 = image_base64
                # Remove previous on-disk image when replaced or cleared.
                if previous_ref and previous_ref != image_ref:
                    delete_image_ref(previous_ref)

            existing.updated_at = _now()
            session.flush()
            return _row_to_planogram(existing)

    def delete(self, planogram_id: str) -> None:
        with get_session() as session:
            existing = session.get(PlanogramRow, planogram_id)
            if existing is None:
                raise KeyError(planogram_id)
            image_ref = existing.image_ref
            session.delete(existing)
            active = self._get_setting(session, ACTIVE_SETTING_KEY)
            if active == planogram_id:
                remaining = session.scalars(select(PlanogramRow.id).limit(1)).first()
                self._set_setting(session, ACTIVE_SETTING_KEY, remaining)
        # Delete media outside the DB transaction so a missing file never rolls back.
        delete_image_ref(image_ref)


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

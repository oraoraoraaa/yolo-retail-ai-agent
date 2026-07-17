"""Persistent record store backing the database page.

Uses SQLAlchemy (SQLite by default, Postgres via ``DATABASE_URL``). Audit rows
may carry an on-disk image ref plus detection / planogram JSON payloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import count
from typing import Any

from sqlalchemy import func, or_, select

from app.db.models import RecordRow
from app.db.session import get_engine, get_session
from app.schemas.database import DatabaseRecord, DatabaseRecordType
from app.services.media import clear_media_subdir, delete_image_ref, media_url_for, save_image_bytes


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    if value is None:
        return _now().isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _row_to_record(row: RecordRow) -> DatabaseRecord:
    return DatabaseRecord(
        id=row.id,
        type=row.type,  # type: ignore[arg-type]
        title=row.title,
        summary=row.summary,
        updated_at=_iso(row.updated_at),
        image_ref=row.image_ref,
        image_url=media_url_for(row.image_ref),
        detection_json=row.detection_json,
        planogram_json=row.planogram_json,
        extra_json=row.extra_json,
    )


class RecordStore:
    """SQL-backed collection of :class:`DatabaseRecord`."""

    def __init__(self) -> None:
        get_engine()
        self._counter = count(self._next_counter_start())
        self._seed_if_empty()

    def _next_counter_start(self) -> int:
        with get_session() as session:
            ids = session.scalars(select(RecordRow.id)).all()
        max_n = 0
        for record_id in ids:
            if isinstance(record_id, str) and record_id.startswith("rec-"):
                suffix = record_id[4:]
                if suffix.isdigit():
                    max_n = max(max_n, int(suffix))
        return max_n + 1

    def _seed_if_empty(self) -> None:
        with get_session() as session:
            count_rows = session.scalar(select(func.count()).select_from(RecordRow)) or 0
            if count_rows > 0:
                return
            seed_data: list[tuple[DatabaseRecordType, str, str]] = [
                ("inventory", "Aisle 3 · Beverages", "Planogram synced · 48 facings tracked."),
                ("sku", "Brand Y Soda 330ml", "SKU mapped to shelf slot (X:12, Y:45)."),
                ("audit", "Morning shelf sweep", "2 gaps flagged near the water section."),
            ]
            now = _now()
            for record_type, title, summary in seed_data:
                record_id = f"rec-{next(self._counter):04d}"
                session.add(
                    RecordRow(
                        id=record_id,
                        type=record_type,
                        title=title,
                        summary=summary,
                        created_at=now,
                        updated_at=now,
                    )
                )

    def add(
        self,
        record_type: DatabaseRecordType,
        title: str,
        summary: str,
        *,
        image_bytes: bytes | None = None,
        image_mime: str | None = None,
        image_ref: str | None = None,
        detection_json: dict[str, Any] | None = None,
        planogram_json: dict[str, Any] | None = None,
        extra_json: dict[str, Any] | None = None,
    ) -> DatabaseRecord:
        """Append a record (optionally with image + detection payloads) and return it."""
        record_id = f"rec-{next(self._counter):04d}"
        stored_ref = image_ref
        if image_bytes and not stored_ref:
            try:
                stored_ref = save_image_bytes(
                    "audits",
                    image_bytes,
                    mime=image_mime,
                    stem=record_id,
                )
            except ValueError:
                stored_ref = None

        now = _now()
        with get_session() as session:
            row = RecordRow(
                id=record_id,
                type=record_type,
                title=title,
                summary=summary,
                image_ref=stored_ref,
                detection_json=detection_json,
                planogram_json=planogram_json,
                extra_json=extra_json,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            return _row_to_record(row)

    def get(self, record_id: str) -> DatabaseRecord | None:
        with get_session() as session:
            row = session.get(RecordRow, record_id)
            return _row_to_record(row) if row else None

    def query(
        self,
        keyword: str | None = None,
        record_type: DatabaseRecordType | None = None,
    ) -> list[DatabaseRecord]:
        """Return records filtered by an optional keyword and type (newest first)."""
        needle = (keyword or "").strip()
        with get_session() as session:
            stmt = select(RecordRow).order_by(RecordRow.updated_at.desc())
            if record_type is not None:
                stmt = stmt.where(RecordRow.type == record_type)
            if needle:
                like = f"%{needle}%"
                stmt = stmt.where(
                    or_(
                        RecordRow.title.ilike(like),
                        RecordRow.summary.ilike(like),
                        RecordRow.id.ilike(like),
                    )
                )
            rows = session.scalars(stmt).all()
            return [_row_to_record(row) for row in rows]

    def clear_all(self) -> tuple[int, int]:
        """Delete every database-page record and orphaned audit media files.

        Returns ``(records_deleted, media_files_deleted)``.
        Does not touch planograms, users, tickets, or planogram images.
        """
        with get_session() as session:
            rows = session.scalars(select(RecordRow)).all()
            count_deleted = len(rows)
            for row in rows:
                delete_image_ref(row.image_ref)
                session.delete(row)
            session.flush()
        # Catch any orphan files left under media/audits.
        media_deleted = clear_media_subdir("audits")
        # Reset id counter so new records start from rec-0001 again.
        self._counter = count(1)
        return count_deleted, media_deleted


_store: RecordStore | None = None


def get_store() -> RecordStore:
    """Return the process-wide record store singleton."""
    global _store
    if _store is None:
        _store = RecordStore()
    return _store


def reset_store() -> None:
    """Clear the singleton (tests)."""
    global _store
    _store = None

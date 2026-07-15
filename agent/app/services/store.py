"""In-memory record store backing the database page.

This is intentionally lightweight (a thread-safe list) so the app runs without
any external database. Audit and chat activity is appended here so the frontend
database view can show recent history. Swap this out for a real DB later.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from itertools import count

from app.schemas.database import DatabaseRecord, DatabaseRecordType


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecordStore:
    """Thread-safe, in-memory collection of :class:`DatabaseRecord`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[DatabaseRecord] = []
        self._counter = count(1)
        self._seed()

    def _seed(self) -> None:
        seed_data: list[tuple[DatabaseRecordType, str, str]] = [
            ("inventory", "Aisle 3 · Beverages", "Planogram synced · 48 facings tracked."),
            ("sku", "Brand Y Soda 330ml", "SKU mapped to shelf slot (X:12, Y:45)."),
            ("audit", "Morning shelf sweep", "2 gaps flagged near the water section."),
        ]
        for record_type, title, summary in seed_data:
            self._append(record_type, title, summary)

    def _append(self, record_type: DatabaseRecordType, title: str, summary: str) -> DatabaseRecord:
        record = DatabaseRecord(
            id=f"rec-{next(self._counter):04d}",
            type=record_type,
            title=title,
            summary=summary,
            updated_at=_now_iso(),
        )
        self._records.insert(0, record)  # newest first
        return record

    def add(self, record_type: DatabaseRecordType, title: str, summary: str) -> DatabaseRecord:
        """Append a record and return it."""
        with self._lock:
            return self._append(record_type, title, summary)

    def query(
        self,
        keyword: str | None = None,
        record_type: DatabaseRecordType | None = None,
    ) -> list[DatabaseRecord]:
        """Return records filtered by an optional keyword and type."""
        needle = (keyword or "").strip().lower()
        with self._lock:
            records = list(self._records)

        def matches(record: DatabaseRecord) -> bool:
            if record_type is not None and record.type != record_type:
                return False
            if needle and needle not in f"{record.title} {record.summary}".lower():
                return False
            return True

        return [record for record in records if matches(record)]


_store: RecordStore | None = None


def get_store() -> RecordStore:
    """Return the process-wide record store singleton."""
    global _store
    if _store is None:
        _store = RecordStore()
    return _store

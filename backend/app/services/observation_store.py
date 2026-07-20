"""Temporal persistence for shelf findings (Plan C debounce).

Records one observation per finding fingerprint per audit and answers the
question "has this finding been seen enough times recently to be trusted?".
A transient false positive (a customer walking past reads as a gap for a single
snapshot) never accumulates enough observations inside the window, so it is
filtered before a ticket is opened. A genuinely empty shelf persists across
audits → confirmed → ticketed.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.db.models import FindingObservationRow
from app.db.session import get_engine, get_session


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    """SQLite may return naive datetimes; treat them as UTC for comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class ObservationStore:
    """SQL-backed rolling record of finding observations for debounce."""

    def __init__(self) -> None:
        # Gate stale-row pruning so it runs at most once per retention window
        # instead of on every single write. Under many cameras auditing every
        # few seconds, a global ``DELETE`` on every observation adds needless
        # write contention on SQLite; the table only needs trimming on the
        # order of the retention period, not per row.
        self._prune_lock = threading.Lock()
        self._last_prune_at: datetime | None = None

    def _should_prune(self, now: datetime, retention_seconds: int) -> bool:
        """Return True at most once per retention window (thread-safe)."""
        if retention_seconds <= 0:
            return False
        # Prune roughly once per retention window. Bound the interval so a very
        # short retention still coalesces bursts, and a long one still trims
        # within a reasonable time.
        interval = max(30.0, min(float(retention_seconds), 300.0))
        with self._prune_lock:
            last = self._last_prune_at
            if last is not None and (now - last).total_seconds() < interval:
                return False
            self._last_prune_at = now
            return True

    def record(
        self,
        fingerprint: str,
        issue_type: str,
        *,
        source_key: str = "",
        retention_seconds: int = 1800,
    ) -> None:
        """Persist one observation of a finding, pruning stale rows periodically.

        The stale-row prune is time-gated (see ``_should_prune``) so it fires at
        most once per retention window rather than on every write — this keeps
        many-camera, high-frequency auditing from hammering SQLite with a global
        ``DELETE`` on each observation.
        """
        if not fingerprint:
            return
        get_engine()
        now = _utcnow()
        with get_session() as session:
            session.add(
                FindingObservationRow(
                    fingerprint=fingerprint,
                    issue_type=issue_type,
                    source_key=source_key or "",
                    observed_at=now,
                )
            )
            if self._should_prune(now, retention_seconds):
                cutoff = now - timedelta(seconds=retention_seconds)
                session.execute(
                    delete(FindingObservationRow).where(
                        FindingObservationRow.observed_at < cutoff
                    )
                )

    def count_recent(
        self,
        fingerprint: str,
        *,
        window_seconds: int,
        source_key: str | None = None,
    ) -> int:
        """Return how many observations of ``fingerprint`` are inside the window.

        In practice a given fingerprint is recorded at most once per audit, so
        this is the number of audits that saw the finding recently.

        ``source_key`` scopes the count to one shelf/camera. This matters for
        findings whose fingerprint is not already planogram-scoped (e.g. a
        ``camera_issue`` with no planogram): without scoping, brief obstructions
        on two unrelated cameras could sum to a false confirmation. When
        ``source_key`` is None the count spans all sources (legacy behavior).
        """
        if not fingerprint:
            return 0
        get_engine()
        cutoff = _utcnow() - timedelta(seconds=max(0, window_seconds))
        with get_session() as session:
            stmt = (
                select(func.count())
                .select_from(FindingObservationRow)
                .where(
                    FindingObservationRow.fingerprint == fingerprint,
                    FindingObservationRow.observed_at >= cutoff,
                )
            )
            if source_key is not None:
                stmt = stmt.where(FindingObservationRow.source_key == source_key)
            total = session.scalar(stmt)
            return int(total or 0)

    def span_seconds(
        self,
        fingerprint: str,
        *,
        window_seconds: int,
        source_key: str | None = None,
    ) -> float:
        """Return the wall-clock seconds between the oldest and newest recent
        observation of ``fingerprint`` inside the window.

        Powers the persistence gate (busy-store defense): a finding may be seen
        in enough audits yet only span a few seconds (two rapid-fire audits
        while a customer briefly steps aside). Requiring the observations to
        span real time filters slow walkers / lingerers that repeat across
        quick audits but do not persist at the same facing for long. Returns
        0.0 when there are fewer than two observations. ``source_key`` scopes
        the span to one shelf/camera (see ``count_recent``).
        """
        if not fingerprint:
            return 0.0
        get_engine()
        cutoff = _utcnow() - timedelta(seconds=max(0, window_seconds))
        with get_session() as session:
            stmt = (
                select(
                    func.min(FindingObservationRow.observed_at),
                    func.max(FindingObservationRow.observed_at),
                )
                .where(
                    FindingObservationRow.fingerprint == fingerprint,
                    FindingObservationRow.observed_at >= cutoff,
                )
            )
            if source_key is not None:
                stmt = stmt.where(FindingObservationRow.source_key == source_key)
            row = session.execute(stmt).first()
        if not row or row[0] is None or row[1] is None:
            return 0.0
        earliest = _as_aware(row[0])
        latest = _as_aware(row[1])
        return max(0.0, (latest - earliest).total_seconds())

    def clear_all(self) -> int:
        """Delete every observation (used by board wipe / tests)."""
        get_engine()
        with get_session() as session:
            rows = session.scalars(select(FindingObservationRow)).all()
            count = len(rows)
            session.execute(delete(FindingObservationRow))
            return count


_store: ObservationStore | None = None


def get_observation_store() -> ObservationStore:
    global _store
    if _store is None:
        _store = ObservationStore()
    return _store


def reset_observation_store() -> None:
    global _store
    _store = None

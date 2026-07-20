"""SQLAlchemy ORM models for persistent retail agent state."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class UserRow(Base):
    """Staff login account for store deployment."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="staff")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class RecordRow(Base):
    """Activity / audit record shown on the database page."""

    __tablename__ = "records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Relative path under media root, e.g. "audits/rec-0001.jpg"
    image_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detection_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    planogram_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extra_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False, index=True
    )


class PlanogramRow(Base):
    """Persisted planogram with freehand facing slots."""

    __tablename__ = "planograms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Relative path under media root, or empty when no image stored on disk
    image_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Keep small inline base64 for demos / when file storage is unavailable
    image_base64: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    slots_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False, index=True
    )


class AppSettingRow(Base):
    """Key/value settings (e.g. active planogram id)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")


class FindingObservationRow(Base):
    """A single observation of a shelf finding, keyed by its fingerprint.

    Powers temporal debounce (Plan C): a finding must be seen in at least M of
    the last K audits within a time window before it is allowed to open a
    ticket. A customer walking past makes a gap that vanishes on the next audit
    → filtered; a genuinely empty shelf persists → ticketed.
    """

    __tablename__ = "finding_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Optional grouping so unrelated cameras/shelves don't share a debounce window.
    source_key: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


class TicketRow(Base):
    """Action ticket produced by the closed-loop retail agent."""

    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # out_of_stock | misplaced | low_stock | camera_issue
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="medium")
    # open | dispatched | in_progress | done | verified | escalated | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="open")
    # floor_staff | backroom | manager
    assignee_role: Mapped[str] = mapped_column(String(32), nullable=False, default="floor_staff")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    item_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shelf_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    planogram_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    slot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audit_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Evidence + loop history (detections, verify scans, webhook deliveries)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    history_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Dedup key so repeated audits don't spam the board
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    escalate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False, index=True
    )

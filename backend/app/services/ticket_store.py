"""SQL-backed action ticket store for the closed-loop board."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, func, or_, select

from app.db.models import TicketRow
from app.db.session import get_engine, get_session
from app.schemas.tickets import (
    AssigneeRole,
    IssueType,
    Ticket,
    TicketPriority,
    TicketStatus,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_ticket(row: TicketRow) -> Ticket:
    evidence = row.evidence_json if isinstance(row.evidence_json, dict) else {}
    roles: list[str] = []
    if isinstance(evidence, dict):
        raw_roles = evidence.get("assigneeRoles") or evidence.get("assignee_roles") or []
        if isinstance(raw_roles, list):
            roles = [str(r).strip() for r in raw_roles if str(r).strip()]
    if row.assignee_role and row.assignee_role not in roles:
        roles.insert(0, row.assignee_role)
    return Ticket(
        id=row.id,
        issue_type=row.issue_type,  # type: ignore[arg-type]
        priority=row.priority,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        assignee_role=row.assignee_role,  # type: ignore[arg-type]
        assignee_roles=roles,
        title=row.title,
        description=row.description or "",
        sku=row.sku,
        item_name=row.item_name,
        shelf_label=row.shelf_label,
        planogram_id=row.planogram_id,
        slot_id=row.slot_id,
        audit_record_id=row.audit_record_id,
        evidence=row.evidence_json,
        history=list(row.history_json or []),
        fingerprint=row.fingerprint,
        escalate_count=row.escalate_count or 0,
        dispatched_at=row.dispatched_at,
        done_at=row.done_at,
        verified_at=row.verified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _history_event(event: str, **payload: Any) -> dict[str, Any]:
    return {
        "at": _utcnow().isoformat(),
        "event": event,
        **payload,
    }


class TicketStore:
    """CRUD + status transitions for action tickets."""

    def create(
        self,
        *,
        issue_type: IssueType | str,
        priority: TicketPriority,
        assignee_role: str,
        title: str,
        description: str = "",
        sku: str | None = None,
        item_name: str | None = None,
        shelf_label: str | None = None,
        planogram_id: str | None = None,
        slot_id: str | None = None,
        audit_record_id: str | None = None,
        evidence: dict[str, Any] | None = None,
        fingerprint: str | None = None,
        status: TicketStatus = "open",
        note: str | None = None,
    ) -> Ticket:
        ticket_id = f"tkt-{uuid4().hex[:12]}"
        history = [_history_event("created", note=note or "Ticket created", status=status)]
        evidence_payload = dict(evidence or {})
        roles = evidence_payload.get("assigneeRoles") or evidence_payload.get("assignee_roles")
        if not isinstance(roles, list) or not roles:
            evidence_payload["assigneeRoles"] = [assignee_role]
        get_engine()
        with get_session() as session:
            row = TicketRow(
                id=ticket_id,
                issue_type=issue_type,
                priority=priority,
                status=status,
                assignee_role=assignee_role,
                title=title,
                description=description,
                sku=sku,
                item_name=item_name,
                shelf_label=shelf_label,
                planogram_id=planogram_id,
                slot_id=slot_id,
                audit_record_id=audit_record_id,
                evidence_json=evidence_payload,
                history_json=history,
                fingerprint=fingerprint,
                escalate_count=0,
            )
            session.add(row)
            session.flush()
            return _row_to_ticket(row)

    def get(self, ticket_id: str) -> Ticket | None:
        get_engine()
        with get_session() as session:
            row = session.get(TicketRow, ticket_id)
            return _row_to_ticket(row) if row else None

    def find_open_by_fingerprint(self, fingerprint: str) -> Ticket | None:
        if not fingerprint:
            return None
        openish = ("open", "dispatched", "in_progress", "escalated", "done")
        get_engine()
        with get_session() as session:
            row = session.scalars(
                select(TicketRow)
                .where(
                    TicketRow.fingerprint == fingerprint,
                    TicketRow.status.in_(openish),
                )
                .order_by(TicketRow.updated_at.desc())
                .limit(1)
            ).first()
            return _row_to_ticket(row) if row else None

    def list(
        self,
        *,
        status: str | None = None,
        issue_type: str | None = None,
        priority: str | None = None,
        assignee_role: str | None = None,
        keyword: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Ticket], int]:
        get_engine()
        with get_session() as session:
            stmt: Select[tuple[TicketRow]] = select(TicketRow)
            count_stmt = select(func.count()).select_from(TicketRow)

            if status and status != "all":
                stmt = stmt.where(TicketRow.status == status)
                count_stmt = count_stmt.where(TicketRow.status == status)
            if issue_type and issue_type != "all":
                stmt = stmt.where(TicketRow.issue_type == issue_type)
                count_stmt = count_stmt.where(TicketRow.issue_type == issue_type)
            if priority and priority != "all":
                stmt = stmt.where(TicketRow.priority == priority)
                count_stmt = count_stmt.where(TicketRow.priority == priority)
            if assignee_role and assignee_role != "all":
                stmt = stmt.where(TicketRow.assignee_role == assignee_role)
                count_stmt = count_stmt.where(TicketRow.assignee_role == assignee_role)
            if keyword:
                like = f"%{keyword.strip()}%"
                clause = or_(
                    TicketRow.title.ilike(like),
                    TicketRow.description.ilike(like),
                    TicketRow.sku.ilike(like),
                    TicketRow.item_name.ilike(like),
                    TicketRow.shelf_label.ilike(like),
                    TicketRow.id.ilike(like),
                )
                stmt = stmt.where(clause)
                count_stmt = count_stmt.where(clause)

            total = int(session.scalar(count_stmt) or 0)
            rows = session.scalars(
                stmt.order_by(TicketRow.updated_at.desc()).offset(offset).limit(limit)
            ).all()
            return [_row_to_ticket(row) for row in rows], total

    def update_status(
        self,
        ticket_id: str,
        status: TicketStatus,
        *,
        note: str | None = None,
        extra_evidence: dict[str, Any] | None = None,
    ) -> Ticket | None:
        get_engine()
        with get_session() as session:
            row = session.get(TicketRow, ticket_id)
            if row is None:
                return None
            now = _utcnow()
            row.status = status
            history = list(row.history_json or [])
            history.append(_history_event("status_change", status=status, note=note or ""))
            row.history_json = history
            if extra_evidence:
                evidence = dict(row.evidence_json or {})
                evidence.update(extra_evidence)
                row.evidence_json = evidence
            if status == "dispatched":
                row.dispatched_at = now
            if status == "done":
                row.done_at = now
            if status == "verified":
                row.verified_at = now
            if status == "escalated":
                row.escalate_count = (row.escalate_count or 0) + 1
            session.flush()
            return _row_to_ticket(row)

    def append_history(
        self,
        ticket_id: str,
        event: str,
        **payload: Any,
    ) -> Ticket | None:
        get_engine()
        with get_session() as session:
            row = session.get(TicketRow, ticket_id)
            if row is None:
                return None
            history = list(row.history_json or [])
            history.append(_history_event(event, **payload))
            row.history_json = history
            session.flush()
            return _row_to_ticket(row)

    def merge_evidence(self, ticket_id: str, evidence: dict[str, Any]) -> Ticket | None:
        get_engine()
        with get_session() as session:
            row = session.get(TicketRow, ticket_id)
            if row is None:
                return None
            merged = dict(row.evidence_json or {})
            merged.update(evidence)
            row.evidence_json = merged
            session.flush()
            return _row_to_ticket(row)

    def clear_all(self) -> int:
        """Delete every action ticket (board wipe). Leaves planograms/users/records."""
        get_engine()
        with get_session() as session:
            rows = session.scalars(select(TicketRow)).all()
            count_deleted = len(rows)
            for row in rows:
                session.delete(row)
            session.flush()
        return count_deleted

    def escalate(
        self,
        ticket_id: str,
        *,
        note: str,
        assignee_role: AssigneeRole = "manager",
        priority: TicketPriority | None = "critical",
    ) -> Ticket | None:
        get_engine()
        with get_session() as session:
            row = session.get(TicketRow, ticket_id)
            if row is None:
                return None
            row.status = "escalated"
            row.assignee_role = assignee_role
            if priority:
                row.priority = priority
            row.escalate_count = (row.escalate_count or 0) + 1
            history = list(row.history_json or [])
            history.append(
                _history_event(
                    "escalated",
                    note=note,
                    assignee_role=assignee_role,
                    priority=row.priority,
                    escalate_count=row.escalate_count,
                )
            )
            row.history_json = history
            session.flush()
            return _row_to_ticket(row)


_store: TicketStore | None = None


def get_ticket_store() -> TicketStore:
    global _store
    if _store is None:
        _store = TicketStore()
    return _store


def reset_ticket_store() -> None:
    global _store
    _store = None

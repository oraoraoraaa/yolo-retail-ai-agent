"""Action-ticket board + closed-loop agent + webhook admin APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.tickets import (
    ClosedLoopRunRequest,
    ClosedLoopRunResult,
    Ticket,
    TicketClearResult,
    TicketCreateManual,
    TicketListResult,
    TicketStatusUpdate,
    VerifyTicketRequest,
    VerifyTicketResult,
    WebhookSettings,
    WebhookTestRequest,
)
from app.services.auth import AuthUser, get_current_user, require_write
from app.services.closed_loop import get_closed_loop_agent
from app.services.ticket_store import get_ticket_store
from app.services.webhooks import (
    load_webhook_settings,
    save_webhook_settings,
    send_test_message,
)

router = APIRouter(tags=["tickets"])


def _require_admin(user: AuthUser) -> None:
    # Webhook / admin config is available to both owner and admin (write roles).
    if not user.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or owner role required for webhook configuration.",
        )


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------


@router.delete("/api/v1/tickets", response_model=TicketClearResult)
async def clear_tickets(
    _user: Annotated[AuthUser, Depends(require_write)],
) -> TicketClearResult:
    """Wipe the action-ticket board. Leaves planograms, users, and DB records."""
    deleted = get_ticket_store().clear_all()
    return TicketClearResult(deleted=deleted)


@router.get("/api/v1/tickets", response_model=TicketListResult)
async def list_tickets(
    _user: Annotated[AuthUser, Depends(get_current_user)],
    status_filter: str | None = Query(default=None, alias="status"),
    issue_type: str | None = Query(default=None, alias="issueType"),
    priority: str | None = Query(default=None),
    assignee_role: str | None = Query(default=None, alias="assigneeRole"),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TicketListResult:
    tickets, total = get_ticket_store().list(
        status=status_filter,
        issue_type=issue_type,
        priority=priority,
        assignee_role=assignee_role,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    return TicketListResult(tickets=tickets, total=total)


@router.get("/api/v1/tickets/{ticket_id}", response_model=Ticket)
async def get_ticket(
    ticket_id: str,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> Ticket:
    ticket = get_ticket_store().get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    return ticket


@router.post("/api/v1/tickets", response_model=Ticket, status_code=status.HTTP_201_CREATED)
async def create_ticket_manual(
    payload: TicketCreateManual,
    _user: Annotated[AuthUser, Depends(require_write)],
) -> Ticket:
    return get_ticket_store().create(
        issue_type=payload.issue_type,
        priority=payload.priority,
        assignee_role=payload.assignee_role,
        title=payload.title,
        description=payload.description,
        sku=payload.sku,
        item_name=payload.item_name,
        shelf_label=payload.shelf_label,
        planogram_id=payload.planogram_id,
        slot_id=payload.slot_id,
        note="Created manually",
    )


@router.patch("/api/v1/tickets/{ticket_id}", response_model=Ticket)
async def update_ticket_status(
    ticket_id: str,
    payload: TicketStatusUpdate,
    _user: Annotated[AuthUser, Depends(require_write)],
) -> Ticket:
    ticket = get_ticket_store().update_status(
        ticket_id,
        payload.status,
        note=payload.note,
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    return ticket


@router.post("/api/v1/tickets/{ticket_id}/dispatch", response_model=dict[str, Any])
async def redispatch_ticket(
    ticket_id: str,
    _user: Annotated[AuthUser, Depends(require_write)],
    language: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.services.webhooks import dispatch_ticket

    store = get_ticket_store()
    ticket = store.get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    result = await dispatch_ticket(ticket, language=language)
    if result.get("ok"):
        store.update_status(
            ticket_id,
            "dispatched",
            note=f"Manually re-dispatched via {result.get('channel')}",
            extra_evidence={"lastDispatch": result},
        )
    else:
        store.append_history(
            ticket_id,
            "dispatch_failed",
            note=result.get("error") or "dispatch failed",
        )
    return result


# ---------------------------------------------------------------------------
# Closed loop
# ---------------------------------------------------------------------------


@router.post("/api/v1/agent/closed-loop/run", response_model=ClosedLoopRunResult)
async def run_closed_loop(
    payload: ClosedLoopRunRequest,
    _user: Annotated[AuthUser, Depends(require_write)],
) -> ClosedLoopRunResult:
    """Detect → Decide → Dispatch over a shelf snapshot."""
    agent = get_closed_loop_agent()
    return await agent.run(
        payload.vision_model_response,
        payload.planogram_response,
        language=payload.language,
        source_label=payload.source_label,
        audit_record_id=payload.audit_record_id,
        dispatch=payload.dispatch,
        dedupe=payload.dedupe,
    )


@router.post(
    "/api/v1/agent/closed-loop/verify/{ticket_id}",
    response_model=VerifyTicketResult,
)
async def verify_ticket_loop(
    ticket_id: str,
    payload: VerifyTicketRequest,
    _user: Annotated[AuthUser, Depends(require_write)],
) -> VerifyTicketResult:
    """After ticket done: re-scan shelf, verify closed or escalate."""
    agent = get_closed_loop_agent()
    try:
        return await agent.verify(
            ticket_id,
            payload.vision_model_response,
            payload.planogram_response,
            language=payload.language,
            source_label=payload.source_label,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        ) from exc


# ---------------------------------------------------------------------------
# Webhook admin (admin role)
# ---------------------------------------------------------------------------


@router.get("/api/v1/admin/webhooks", response_model=WebhookSettings)
async def get_webhook_settings(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> WebhookSettings:
    _require_admin(user)
    return load_webhook_settings()


@router.put("/api/v1/admin/webhooks", response_model=WebhookSettings)
async def put_webhook_settings(
    payload: WebhookSettings,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> WebhookSettings:
    _require_admin(user)
    return save_webhook_settings(payload)


@router.post("/api/v1/admin/webhooks/test", response_model=dict[str, Any])
async def test_webhook(
    payload: WebhookTestRequest,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> dict[str, Any]:
    _require_admin(user)
    # Prefer draft settings from the form so "Send test" works before Save.
    return await send_test_message(
        payload.settings,
        channel=payload.channel,
        endpoint_id=payload.endpoint_id,
        message=payload.message,
        language=payload.language,
    )

"""Agent chat endpoint.

``POST /api/v1/agent/chat`` accepts either:
- ``application/json``: ``{ message, history }``
- ``multipart/form-data``: fields ``message``, ``history`` (JSON string), ``images``

and returns ``{ reply }``.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from app.schemas.chat import ChatMessage, ChatRequest, ChatResponse
from app.services import get_agent, get_store

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def _parse_history(raw: object) -> list[ChatMessage]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid history JSON: {exc}",
            ) from exc
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`history` must be a list of chat messages.",
        )
    try:
        return [ChatMessage.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid history payload: {exc.errors()}",
        ) from exc


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request) -> ChatResponse:
    """Send a user message (optionally with images) to the retail agent."""
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        message = str(form.get("message", ""))
        history = _parse_history(form.get("history"))
        uploads = form.getlist("images")
        attachment_names = [
            getattr(upload, "filename", None) or "image"
            for upload in uploads
            if getattr(upload, "filename", None) is not None
        ]
    else:
        try:
            payload = ChatRequest.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid chat payload: {exc}",
            ) from exc
        message = payload.message
        history = payload.history
        attachment_names = []

    if not message.strip() and not attachment_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a message or at least one attachment.",
        )

    reply = get_agent().chat(message, history, attachment_names)

    summary = message.strip() or f"{len(attachment_names)} attachment(s)"
    get_store().add("chat", title="Agent conversation", summary=summary[:120])

    return ChatResponse(reply=reply)

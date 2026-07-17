"""Agent chat endpoint.

``POST /api/v1/agent/chat`` accepts either:
- ``application/json``: ``{ message, history }``
- ``multipart/form-data``: fields ``message``, ``history`` (JSON string), ``images``

and returns ``{ reply }``. Image attachments are forwarded as real multimodal
content to the LLM (not just filenames).
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from app.config import get_settings
from app.schemas.chat import ChatMessage, ChatRequest, ChatResponse
from app.services import get_agent, get_store
from app.services.agent import image_part_from_bytes
from app.services.auth import AuthUser, get_current_user

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

_ALLOWED_IMAGE_PREFIX = "image/"


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
async def chat(
    request: Request,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> ChatResponse:
    """Send a user message (optionally with images) to the retail agent."""
    settings = get_settings()
    content_type = request.headers.get("content-type", "")

    images: list[dict] = []
    attachment_names: list[str] = []

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        message = str(form.get("message", ""))
        history = _parse_history(form.get("history"))
        language = str(form.get("language", "en"))
        uploads = form.getlist("images")

        if len(uploads) > settings.max_chat_images:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"Too many images ({len(uploads)}). "
                    f"Maximum is {settings.max_chat_images}."
                ),
            )

        for upload in uploads:
            filename = getattr(upload, "filename", None)
            if filename is None:
                continue
            content_type_upload = getattr(upload, "content_type", None)
            if content_type_upload and not str(content_type_upload).startswith(
                _ALLOWED_IMAGE_PREFIX
            ):
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail=(
                        f"Expected an image upload, received '{content_type_upload}' "
                        f"for '{filename}'."
                    ),
                )
            image_bytes = await upload.read()
            if not image_bytes:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Uploaded image '{filename}' is empty.",
                )
            if len(image_bytes) > settings.max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=(
                        f"Image '{filename}' exceeds the "
                        f"{settings.max_upload_bytes} byte limit "
                        f"({len(image_bytes)} bytes)."
                    ),
                )
            name = str(filename) or "image"
            attachment_names.append(name)
            images.append(
                image_part_from_bytes(
                    image_bytes,
                    content_type=str(content_type_upload) if content_type_upload else None,
                    name=name,
                )
            )
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
        language = payload.language
        attachment_names = []
        images = []

    if not message.strip() and not attachment_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a message or at least one attachment.",
        )

    reply = await get_agent().chat(
        message,
        history,
        attachment_names,
        language=language,
        images=images,
    )

    summary = message.strip() or f"{len(attachment_names)} attachment(s)"
    get_store().add("chat", title="Agent conversation", summary=summary[:120])

    return ChatResponse(reply=reply)

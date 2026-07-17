"""Agent chat schemas (mirrors ``frontend/src/types/chat.ts``)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel

ChatRole = Literal["user", "assistant", "system"]


class ChatAttachment(CamelModel):
    """Metadata for an attachment carried by a chat message."""

    id: str
    name: str
    type: str
    size: int
    preview_url: str | None = None


class ChatMessage(CamelModel):
    """A single message in the conversation history."""

    id: str
    role: ChatRole
    content: str
    created_at: str
    attachments: list[ChatAttachment] | None = None


class ChatRequest(CamelModel):
    """JSON body accepted by ``POST /api/v1/agent/chat``."""

    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    language: str = "en"


class ChatResponse(CamelModel):
    """Reply returned by the agent."""

    reply: str

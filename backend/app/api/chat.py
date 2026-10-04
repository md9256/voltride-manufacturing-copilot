"""Chat endpoints: conversation history and a streaming message endpoint (SSE).

Conversations are scoped by an anonymous client id (X-Client-Id header, a
UUID the browser generates and keeps). That is not authentication, which
comes in Phase 6; it keeps one visitor's conversation list separate from
another's.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import ProviderNotConfigured, make_provider
from app.api.deps import ClientId, Db, Makers, Provider
from app.config import get_settings
from app.models.db import DatabaseNotConfigured, get_sessionmaker
from app.odoo import OdooClient, get_odoo_client
from app.security import AiAccess, require_access
from app.services import chat_store
from app.services.chat import run_chat_turn

router = APIRouter(prefix="/api/chat", tags=["chat"])
Gated = [Depends(require_access)]


# --- schemas ----------------------------------------------------------------


class ChatStatus(BaseModel):
    enabled: bool
    provider: str
    model: str
    reason: str | None = None


class ConversationSummary(BaseModel):
    id: str
    title: str
    provider: str
    model: str
    updated_at: datetime


class DisplayMessage(BaseModel):
    role: str  # user | assistant | tool
    display: dict


class ConversationDetail(ConversationSummary):
    messages: list[DisplayMessage]
    # False when the server's provider changed since this conversation began:
    # its stored history is in another provider's format and can't continue.
    can_continue: bool


class SendMessage(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _summary(conv) -> ConversationSummary:
    return ConversationSummary(
        id=conv.id, title=conv.title, provider=conv.provider, model=conv.model, updated_at=conv.updated_at
    )


# --- endpoints --------------------------------------------------------------


@router.get("/status", response_model=ChatStatus)
def status() -> ChatStatus:
    settings = get_settings()
    reason = None
    try:
        make_provider(settings)
        get_sessionmaker()
    except (ProviderNotConfigured, DatabaseNotConfigured) as exc:
        reason = str(exc)
    return ChatStatus(
        enabled=reason is None, provider=settings.llm_provider, model=settings.resolved_llm_model, reason=reason
    )


@router.get("/conversations", response_model=list[ConversationSummary], dependencies=Gated)
async def list_conversations(db: Db, client_id: ClientId) -> list[ConversationSummary]:
    return [_summary(c) for c in await chat_store.list_conversations(db, client_id)]


@router.post("/conversations", response_model=ConversationSummary, status_code=201, dependencies=Gated)
async def create_conversation(db: Db, client_id: ClientId, provider: Provider) -> ConversationSummary:
    conv = await chat_store.create_conversation(db, owner_id=client_id, provider=provider.name, model=provider.model)
    return _summary(conv)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail, dependencies=Gated)
async def get_conversation(conversation_id: str, db: Db, client_id: ClientId) -> ConversationDetail:
    conv = await _load(db, client_id, conversation_id)
    return ConversationDetail(
        **_summary(conv).model_dump(),
        messages=[DisplayMessage(role=m.role, display=m.display) for m in conv.messages],
        can_continue=conv.provider == get_settings().llm_provider,
    )


@router.delete("/conversations/{conversation_id}", status_code=204, dependencies=Gated)
async def delete_conversation(conversation_id: str, db: Db, client_id: ClientId) -> None:
    try:
        await chat_store.delete_conversation(db, client_id, conversation_id)
    except chat_store.ConversationNotFound:
        raise HTTPException(404, "Conversation not found") from None


@router.post("/conversations/{conversation_id}/messages", dependencies=AiAccess)
async def send_message(
    conversation_id: str,
    body: SendMessage,
    client_id: ClientId,
    makers: Makers,
    provider: Provider,
    odoo: Annotated[OdooClient, Depends(get_odoo_client)],
) -> StreamingResponse:
    """Stream the assistant's reply as Server-Sent Events.

    Validation (ownership, provider match) happens before the stream starts so
    it can return proper HTTP errors; the stream then uses its own session,
    because request-scoped dependencies may be closed before a streamed
    response finishes.
    """
    async with makers() as db:
        conv = await _load(db, client_id, conversation_id)
        if conv.provider != provider.name:
            raise HTTPException(
                409,
                f"This conversation used {conv.provider}; the server now uses {provider.name}. Start a new one.",
            )

    async def events() -> AsyncIterator[str]:
        async with makers() as db:
            conv = await _load(db, client_id, conversation_id)
            async for event in run_chat_turn(session=db, conv=conv, text=body.text, provider=provider, odoo=odoo):
                yield f"data: {json.dumps(event.as_dict(), ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # Disable proxy buffering so tokens reach the browser as they arrive.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _load(db: AsyncSession, client_id: str, conversation_id: str):
    try:
        return await chat_store.get_conversation(db, client_id, conversation_id)
    except chat_store.ConversationNotFound:
        raise HTTPException(404, "Conversation not found") from None

"""Persistence for conversations and their messages (async SQLAlchemy)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import Conversation, Message

TITLE_MAX = 80


class ConversationNotFound(LookupError):
    pass


async def create_conversation(session: AsyncSession, *, owner_id: str, provider: str, model: str) -> Conversation:
    conv = Conversation(id=str(uuid.uuid4()), owner_id=owner_id, provider=provider, model=model)
    session.add(conv)
    await session.commit()
    return conv


async def list_conversations(session: AsyncSession, owner_id: str, limit: int = 50) -> list[Conversation]:
    rows = await session.scalars(
        select(Conversation)
        .where(Conversation.owner_id == owner_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return list(rows)


async def get_conversation(session: AsyncSession, owner_id: str, conversation_id: str) -> Conversation:
    """The conversation with its messages; raises unless it belongs to `owner_id`."""
    conv = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.owner_id == owner_id)
        .options(selectinload(Conversation.messages))
        # Refresh an instance already in this session (and its messages)
        # rather than returning the stale cached copy.
        .execution_options(populate_existing=True)
    )
    if conv is None:
        raise ConversationNotFound(conversation_id)
    return conv


async def delete_conversation(session: AsyncSession, owner_id: str, conversation_id: str) -> None:
    result = await session.execute(
        delete(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == owner_id)
    )
    if result.rowcount == 0:
        raise ConversationNotFound(conversation_id)
    await session.commit()


async def append_message(
    session: AsyncSession, conv: Conversation, *, role: str, native: list[dict], display: dict
) -> Message:
    """Append one step and commit immediately, so a turn that fails half-way
    still leaves a consistent, replayable history up to the failure."""
    next_seq = (
        await session.scalar(select(func.coalesce(func.max(Message.seq), -1)).where(Message.conversation_id == conv.id))
    ) + 1
    msg = Message(conversation_id=conv.id, seq=next_seq, role=role, native=native, display=display)
    session.add(msg)
    conv.updated_at = datetime.now(UTC)
    if role == "user" and conv.title == "New conversation":
        text = display.get("text", "").strip().replace("\n", " ")
        conv.title = text[:TITLE_MAX] + ("…" if len(text) > TITLE_MAX else "") or conv.title
    await session.commit()
    return msg

"""Chat history tables.

Each row is one step of the conversation (user text, assistant turn, or the
results of that turn's tool calls) and stores two JSON documents:
- `native`: the provider messages for the step, exactly as the provider
  produced or expects them (a list: Gemini sends one message per tool result,
  Anthropic one message for all). Replayed verbatim on the next request,
  because both providers reject altered history (Anthropic thinking blocks,
  Gemini thought signatures).
- `display`: a provider-neutral view (text, tool calls, tool outcomes) that the
  UI renders, so the front end never parses provider formats.

A conversation is pinned to the provider that started it: native histories are
not interchangeable between providers.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base, JsonType


def _now() -> datetime:
    return datetime.now(UTC)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.seq", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | tool
    native: Mapped[list] = mapped_column(JsonType)
    display: Mapped[dict] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

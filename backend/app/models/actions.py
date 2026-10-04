"""Proposed write actions, uploaded-quote reviews and the audit log.

A ProposedAction is the only bridge from "the AI (or a parsed PDF) suggests a
write" to "the ERP is changed": it is created as `pending`, and only the
user's explicit confirmation (a separate HTTP endpoint the LLM cannot call)
moves it on. Status flow:

    pending -> executing -> executed
                         -> failed      (may be confirmed again; writes are idempotent)
    pending -> rejected | expired
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base, JsonType


def _now() -> datetime:
    return datetime.now(UTC)


class ProposedAction(Base):
    __tablename__ = "proposed_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))  # purchase_orders
    source: Mapped[str] = mapped_column(String(32))  # chat | quote_intake
    status: Mapped[str] = mapped_column(String(16), index=True)
    payload: Mapped[dict] = mapped_column(JsonType)  # what will be written, validated
    result: Mapped[dict | None] = mapped_column(JsonType, nullable=True)  # what was written
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuoteReview(Base):
    """A parsed supplier quote awaiting the user's review.

    Stores the model's extraction (not the PDF, which is never kept) so the
    proposal is rebuilt server-side from it plus the user's corrections; the
    browser never supplies the figures that get written.
    """

    __tablename__ = "quote_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    extraction: Mapped[dict] = mapped_column(JsonType)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEntry(Base):
    """Append-only record of AI activity: tool calls, proposals and their
    decisions, and document extractions. The application never updates or
    deletes rows."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # tool_call | action | extraction | summary
    name: Mapped[str] = mapped_column(String(64))  # tool name, action event, or document type
    question: Mapped[str | None] = mapped_column(Text, nullable=True)  # the user message behind it
    params: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    result: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    ok: Mapped[bool] = mapped_column(default=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ProductionSummary(Base):
    """Cached AI daily summaries.

    Keyed by day, language and a hash of the facts: the same facts never cost
    a second LLM call (important on a free-tier quota), while any change in
    the underlying data produces a new summary.
    """

    __tablename__ = "production_summaries"
    __table_args__ = (UniqueConstraint("day", "language", "facts_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD, company time zone
    language: Mapped[str] = mapped_column(String(8))
    facts_hash: Mapped[str] = mapped_column(String(64))
    facts: Mapped[dict] = mapped_column(JsonType)
    text: Mapped[str] = mapped_column(Text)
    unverified: Mapped[list] = mapped_column(JsonType)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

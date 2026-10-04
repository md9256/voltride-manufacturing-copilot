"""Append-only audit log of AI activity."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actions import AuditEntry

MAX_RESULT_CHARS = 4000


def truncate(value: Any) -> dict | None:
    """Store results up to a size limit; larger ones keep a readable preview."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = {"text": value}
    if not isinstance(value, dict):
        value = {"value": value}
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return value
    return {"truncated": True, "size": len(text), "preview": text[:MAX_RESULT_CHARS]}


async def record(session: AsyncSession, *, kind: str, name: str, commit: bool = True, **fields: Any) -> AuditEntry:
    entry = AuditEntry(kind=kind, name=name, **fields)
    if "result" in fields:
        entry.result = truncate(fields["result"])
    session.add(entry)
    if commit:
        await session.commit()
    return entry


async def list_entries(
    session: AsyncSession,
    *,
    owner_id: str,
    kind: str | None = None,
    conversation_id: str | None = None,
    limit: int = 100,
    before_id: int | None = None,
) -> list[AuditEntry]:
    query = select(AuditEntry).where(AuditEntry.owner_id == owner_id).order_by(AuditEntry.id.desc()).limit(limit)
    if kind:
        query = query.where(AuditEntry.kind == kind)
    if conversation_id:
        query = query.where(AuditEntry.conversation_id == conversation_id)
    if before_id:
        query = query.where(AuditEntry.id < before_id)
    return list(await session.scalars(query))

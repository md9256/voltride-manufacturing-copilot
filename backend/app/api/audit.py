"""Read-only view of the audit log.

Scoped to the caller's client id until Phase 6 adds real authentication; an
organisation-wide view then becomes an admin-only endpoint.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import ClientId, Db
from app.services import audit

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditEntryView(BaseModel):
    id: int
    created_at: datetime
    conversation_id: str | None
    kind: str
    name: str
    question: str | None
    params: dict | None
    result: dict | None
    ok: bool
    duration_ms: float | None
    provider: str | None
    model: str | None


@router.get("", response_model=list[AuditEntryView])
async def list_audit(
    db: Db,
    client_id: ClientId,
    kind: Literal["tool_call", "action", "extraction"] | None = None,
    conversation_id: str | None = None,
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditEntryView]:
    rows = await audit.list_entries(
        db, owner_id=client_id, kind=kind, conversation_id=conversation_id, before_id=before_id, limit=limit
    )
    return [
        AuditEntryView(
            **{c: getattr(r, c) for c in AuditEntryView.model_fields if c != "created_at"},
            created_at=r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC),
        )
        for r in rows
    ]

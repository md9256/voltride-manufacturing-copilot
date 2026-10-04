"""Proposed-action lifecycle: propose -> (user confirms) -> execute.

This module holds the only code path that writes to the ERP. It runs when the
user clicks Confirm (POST /api/actions/{id}/confirm); no AI tool can reach it.

Safety properties, each covered by tests:
- Only the owner (the browser that started the conversation or uploaded the
  quote) can confirm or reject, and only within PROPOSAL_TTL.
- Claiming is atomic: a conditional UPDATE moves pending -> executing, so a
  double click or a retried request cannot run the writes twice.
- The stored payload is re-validated against current ERP data before writing.
- Writes are idempotent: each order carries a deterministic origin
  ("Copilot <id> #n"); an order that already exists in Odoo with that origin
  is reused, so confirming again after a partial failure never duplicates.
- Orders are created as drafts (RFQs) only; nothing is confirmed or sent.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actions import ProposedAction
from app.odoo import OdooClient, OdooError
from app.schemas.actions import ActionView, CreatedPurchaseOrder, PurchaseProposal
from app.schemas.erp import PurchaseLineDraft
from app.services import audit
from app.services.bom import ManufacturingData
from app.services.purchasing import revalidate

PROPOSAL_TTL = timedelta(minutes=30)
CONFIRMABLE = ("pending", "failed")


class ActionNotFound(LookupError):
    pass


class ActionConflict(Exception):
    """The action cannot be confirmed or rejected in its current state."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes; Postgres returns aware ones.
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def origin_for(action_id: str, index: int) -> str:
    return f"Copilot {action_id[:8]} #{index + 1}"


async def create_proposal(
    session: AsyncSession,
    *,
    owner_id: str,
    proposal: PurchaseProposal,
    source: str,
    conversation_id: str | None = None,
    question: str | None = None,
) -> ProposedAction:
    action = ProposedAction(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        conversation_id=conversation_id,
        kind=proposal.kind,
        source=source,
        status="pending",
        payload=proposal.model_dump(mode="json"),
        expires_at=_now() + PROPOSAL_TTL,
    )
    session.add(action)
    await audit.record(
        session,
        kind="action",
        name="proposed",
        owner_id=owner_id,
        conversation_id=conversation_id,
        question=question,
        params={"action_id": action.id, "source": source},
        result=action.payload,
    )
    return action


async def get_action(session: AsyncSession, owner_id: str, action_id: str) -> ProposedAction:
    action = await session.get(ProposedAction, action_id, populate_existing=True)
    if action is None or action.owner_id != owner_id:
        raise ActionNotFound(action_id)
    return action


async def reject(session: AsyncSession, owner_id: str, action_id: str) -> ProposedAction:
    action = await get_action(session, owner_id, action_id)
    claimed = await _transition(session, action_id, frm=("pending", "failed"), to="rejected")
    if not claimed:
        raise ActionConflict(f"This proposal is already {action.status}.")
    await audit.record(
        session,
        kind="action",
        name="rejected",
        owner_id=owner_id,
        conversation_id=action.conversation_id,
        params={"action_id": action_id},
    )
    return await get_action(session, owner_id, action_id)


async def confirm(session: AsyncSession, owner_id: str, action_id: str, odoo: OdooClient) -> ProposedAction:
    action = await get_action(session, owner_id, action_id)
    if action.status == "pending" and _aware(action.expires_at) < _now():
        await _transition(session, action_id, frm=("pending",), to="expired")
        raise ActionConflict("This proposal has expired. Ask again to get a fresh one.")
    if not await _transition(session, action_id, frm=CONFIRMABLE, to="executing"):
        raise ActionConflict(f"This proposal is already {action.status}.")
    await audit.record(
        session,
        kind="action",
        name="confirmed",
        owner_id=owner_id,
        conversation_id=action.conversation_id,
        params={"action_id": action_id},
    )

    proposal = PurchaseProposal.model_validate(action.payload)
    try:
        created = await asyncio.to_thread(_execute, proposal, action_id, odoo)
    except _Invalid as exc:
        return await _finish(session, action, status="failed", error=str(exc))
    except OdooError as exc:
        return await _finish(session, action, status="failed", error=f"The ERP rejected the write: {exc}")
    return await _finish(session, action, status="executed", created=created)


class _Invalid(Exception):
    pass


def _execute(proposal: PurchaseProposal, action_id: str, odoo: OdooClient) -> list[CreatedPurchaseOrder]:
    """Blocking ERP work (runs in a worker thread): re-validate, then write drafts."""
    data = ManufacturingData.build(odoo.list_products(), odoo.list_boms(), odoo.list_work_centers())
    problems = revalidate(proposal, data, {s.id for s in odoo.list_suppliers()})
    if proposal.quote and proposal.quote.quote_number:
        for order in proposal.orders:
            existing = odoo.find_purchase_orders(supplier_id=order.supplier_id, partner_ref=proposal.quote.quote_number)
            others = [po for po in existing if not (po.origin or "").startswith(f"Copilot {action_id[:8]}")]
            if others:
                problems.append(
                    f"Quote {proposal.quote.quote_number} is already entered as {others[0].name}; "
                    "not creating a duplicate."
                )
    if problems:
        raise _Invalid("Not written: " + " ".join(problems))

    created = []
    for index, order in enumerate(proposal.orders):
        origin = origin_for(action_id, index)
        existing = odoo.find_purchase_orders(supplier_id=order.supplier_id, origin=origin)
        po = (
            existing[0]
            if existing
            else odoo.create_draft_purchase_order(
                order.supplier_id,
                [
                    PurchaseLineDraft(product_id=ln.product_id, quantity=ln.quantity, unit_price=ln.unit_price)
                    for ln in order.lines
                ],
                origin=origin,
                partner_ref=order.partner_ref,
            )
        )
        created.append(
            CreatedPurchaseOrder(
                name=po.name, supplier=po.supplier, amount_total=po.amount_total, url=po.url, simulated=po.id < 0
            )
        )
    return created


async def _transition(session: AsyncSession, action_id: str, *, frm: tuple[str, ...], to: str) -> bool:
    """Atomically move an action between states; False if it was not in `frm`.

    The WHERE clause on the current status is what makes concurrent confirms
    safe: only one request's UPDATE can match.
    """
    result = await session.execute(
        update(ProposedAction)
        .where(ProposedAction.id == action_id, ProposedAction.status.in_(frm))
        .values(status=to, decided_at=_now())
    )
    await session.commit()
    return result.rowcount == 1


async def _finish(
    session: AsyncSession,
    action: ProposedAction,
    *,
    status: str,
    created: list[CreatedPurchaseOrder] | None = None,
    error: str | None = None,
) -> ProposedAction:
    result = {"purchase_orders": [c.model_dump() for c in created or []]}
    await session.execute(
        update(ProposedAction)
        .where(ProposedAction.id == action.id)
        .values(status=status, result=result, error=error, decided_at=_now())
    )
    await audit.record(
        session,
        kind="action",
        name=status,
        owner_id=action.owner_id,
        conversation_id=action.conversation_id,
        params={"action_id": action.id},
        result=result if not error else {"error": error},
        ok=error is None,
    )
    return await get_action(session, action.owner_id, action.id)


def to_view(action: ProposedAction) -> ActionView:
    status = action.status
    if status == "pending" and _aware(action.expires_at) < _now():
        status = "expired"  # shown as expired even before anyone tries to confirm
    return ActionView(
        id=action.id,
        kind=action.kind,
        source=action.source,
        status=status,
        payload=PurchaseProposal.model_validate(action.payload),
        created=[CreatedPurchaseOrder.model_validate(c) for c in (action.result or {}).get("purchase_orders", [])],
        error=action.error,
        created_at=_aware(action.created_at),
        expires_at=_aware(action.expires_at),
        decided_at=_aware(action.decided_at) if action.decided_at else None,
    )

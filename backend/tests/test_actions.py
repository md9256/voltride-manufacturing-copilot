"""The only ERP write path: propose -> confirm, with its safety properties."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models.actions import AuditEntry, ProposedAction
from app.odoo.demo import DemoOdooClient
from app.schemas.actions import QuoteSource
from app.schemas.erp import PurchaseOrderRef
from app.services import actions
from app.services.purchasing import LineRequest, build_proposal
from tests.conftest import SqliteDb
from tests.factories import BOX, CHIP, mini_voltride
from tests.fakes import FakeOdooClient
from tests.test_demo_client import make_snapshot

OWNER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def two_supplier_proposal(**kw):
    return build_proposal(
        mini_voltride(), [LineRequest(CHIP, 10), LineRequest(BOX, 5)], currency="HKD", summary="test", **kw
    )


async def propose(db, proposal=None, owner=OWNER):
    return await actions.create_proposal(
        db, owner_id=owner, proposal=proposal or two_supplier_proposal(), source="chat"
    )


async def test_proposing_writes_nothing(db):
    odoo = FakeOdooClient()
    action = await propose(db)
    assert action.status == "pending"
    assert odoo.created == []


async def test_confirm_creates_one_draft_per_supplier(db):
    odoo = FakeOdooClient()
    action = await propose(db)

    done = await actions.confirm(db, OWNER, action.id, odoo)

    assert done.status == "executed"
    assert [(sid, [ln.quantity for ln in lines]) for sid, lines, _, _ in odoo.created] == [(201, [10]), (204, [5])]
    assert all(origin.startswith(f"Copilot {action.id[:8]} #") for _, _, origin, _ in odoo.created)
    view = actions.to_view(done)
    assert [c.name for c in view.created] == ["P00101", "P00102"]
    assert not any(c.simulated for c in view.created)


async def test_double_confirm_writes_once(db):
    odoo = FakeOdooClient()
    action = await propose(db)
    await actions.confirm(db, OWNER, action.id, odoo)
    with pytest.raises(actions.ActionConflict, match="already executed"):
        await actions.confirm(db, OWNER, action.id, odoo)
    assert len(odoo.created) == 2


async def test_concurrent_confirms_execute_once():
    database = SqliteDb()
    maker = await database.sessionmaker()
    odoo = FakeOdooClient()
    async with maker() as db:
        action = await propose(db)

    async def attempt():
        async with maker() as db:
            try:
                return (await actions.confirm(db, OWNER, action.id, odoo)).status
            except actions.ActionConflict:
                return "conflict"

    results = await asyncio.gather(attempt(), attempt(), attempt())
    assert sorted(results) == ["conflict", "conflict", "executed"]
    assert len(odoo.created) == 2  # one PO per supplier, once
    await database.engine.dispose()


async def test_only_the_owner_can_see_confirm_or_reject(db):
    action = await propose(db)
    for call in (
        actions.get_action(db, OTHER, action.id),
        actions.confirm(db, OTHER, action.id, FakeOdooClient()),
        actions.reject(db, OTHER, action.id),
    ):
        with pytest.raises(actions.ActionNotFound):
            await call


async def test_expired_proposal_cannot_be_confirmed(db):
    odoo = FakeOdooClient()
    action = await propose(db)
    await db.execute(
        update(ProposedAction)
        .where(ProposedAction.id == action.id)
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db.commit()
    with pytest.raises(actions.ActionConflict, match="expired"):
        await actions.confirm(db, OWNER, action.id, odoo)
    assert (await actions.get_action(db, OWNER, action.id)).status == "expired"
    assert odoo.created == []


async def test_rejected_proposal_cannot_be_confirmed(db):
    action = await propose(db)
    assert (await actions.reject(db, OWNER, action.id)).status == "rejected"
    with pytest.raises(actions.ActionConflict):
        await actions.confirm(db, OWNER, action.id, FakeOdooClient())


async def test_revalidation_failure_writes_nothing(db):
    odoo = FakeOdooClient()
    action = await propose(db)
    odoo.products = [p for p in odoo.products if p.id != BOX]  # product disappeared meanwhile
    done = await actions.confirm(db, OWNER, action.id, odoo)
    assert done.status == "failed"
    assert "no longer exists" in done.error
    assert odoo.created == []


async def test_failed_write_can_be_retried_without_duplicates(db):
    odoo = FakeOdooClient()
    action = await propose(db)
    original_create = odoo.create_draft_purchase_order
    calls = {"n": 0}

    def flaky(*args, **kwargs):  # first order succeeds, second fails
        calls["n"] += 1
        if calls["n"] == 2:
            raise actions.OdooError("HTTP 503: unavailable", status=503)
        return original_create(*args, **kwargs)

    odoo.create_draft_purchase_order = flaky
    first = await actions.confirm(db, OWNER, action.id, odoo)
    assert first.status == "failed" and "ERP rejected" in first.error
    assert len(odoo.created) == 1

    retried = await actions.confirm(db, OWNER, action.id, odoo)
    assert retried.status == "executed"
    assert len(odoo.created) == 2  # the first order was found by its origin and reused, not recreated
    assert [c.name for c in actions.to_view(retried).created] == ["P00101", "P00102"]


async def test_quote_already_entered_elsewhere_is_not_written(db):
    odoo = FakeOdooClient()
    proposal = two_supplier_proposal()
    proposal.orders = proposal.orders[:1]
    proposal.total = proposal.orders[0].total
    proposal.orders[0].partner_ref = "Q-7"
    proposal.quote = QuoteSource(review_id="r", quote_number="Q-7", filename="q.pdf", file_sha256="x")
    odoo.purchase_orders.append(
        PurchaseOrderRef(
            id=9,
            name="P00009",
            supplier_id=201,
            supplier="ChipCo",
            partner_ref="q-7",
            origin=None,
            state="draft",
            amount_total=1,
        )
    )
    action = await propose(db, proposal)
    done = await actions.confirm(db, OWNER, action.id, odoo)
    assert done.status == "failed" and "already entered as P00009" in done.error
    assert odoo.created == []


async def test_every_step_is_audited(db):
    action = await propose(db)
    await actions.confirm(db, OWNER, action.id, FakeOdooClient())
    rows = (await db.scalars(select(AuditEntry).order_by(AuditEntry.id))).all()
    assert [(r.kind, r.name) for r in rows] == [("action", "proposed"), ("action", "confirmed"), ("action", "executed")]
    assert rows[-1].result["purchase_orders"][0]["name"] == "P00101"


async def test_demo_mode_simulates_writes(db):
    demo = DemoOdooClient(make_snapshot())
    action = await propose(db)
    done = await actions.confirm(db, OWNER, action.id, demo)
    created = actions.to_view(done).created
    assert [c.name for c in created] == ["DEMO-P0001", "DEMO-P0002"]
    assert all(c.simulated and c.url is None for c in created)

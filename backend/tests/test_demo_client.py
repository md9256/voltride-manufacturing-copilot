from datetime import timedelta

import pytest

from app.odoo.demo import DemoOdooClient
from app.odoo.snapshot import DEFAULT_SNAPSHOT_PATH, Snapshot, load_snapshot
from tests.fakes import FakeOdooClient, utc


def make_snapshot() -> Snapshot:
    fake = FakeOdooClient()
    return Snapshot(
        exported_at=utc(2026, 10, 4, 12),
        server_version="20.0+e",
        currency="HKD",
        sale_orders=fake.sale_orders,
        manufacturing_orders=fake.mos,
        stock_levels=fake.levels,
        products=fake.products,
        boms=fake.boms,
        work_centers=fake.work_centers,
        work_orders=fake.work_orders,
    )


def test_dates_shift_by_whole_weeks_since_export():
    snapshot = make_snapshot()
    client = DemoOdooClient(snapshot, now=utc(2026, 10, 4, 12) + timedelta(days=17))  # 2 weeks + 3 days
    original = snapshot.sale_orders[0].date_order
    shifted = client.list_sale_orders()[0].date_order
    assert shifted - original == timedelta(weeks=2)
    assert shifted.weekday() == original.weekday()
    assert client.list_manufacturing_orders()[0].date_start - snapshot.manufacturing_orders[0].date_start == timedelta(
        weeks=2
    )


def test_no_shift_on_export_day_and_snapshot_unchanged():
    snapshot = make_snapshot()
    before = snapshot.sale_orders[0].date_order
    client = DemoOdooClient(snapshot, now=utc(2026, 10, 4, 18))
    assert client.list_sale_orders()[0].date_order == before
    DemoOdooClient(snapshot, now=utc(2027, 1, 1)).list_sale_orders()
    assert snapshot.sale_orders[0].date_order == before  # shifting copies, never mutates


def test_since_filter_applies_after_shift():
    snapshot = make_snapshot()  # all fixture orders dated 2026-09-01
    client = DemoOdooClient(snapshot, now=utc(2026, 10, 4) + timedelta(weeks=10))
    assert client.list_sale_orders(since=utc(2026, 10, 1)) != []
    assert DemoOdooClient(snapshot, now=utc(2026, 10, 4)).list_sale_orders(since=utc(2026, 10, 1)) == []


def test_snapshot_round_trips_through_json(tmp_path):
    path = tmp_path / "snap.json"
    path.write_text(make_snapshot().model_dump_json())
    assert load_snapshot(path) == make_snapshot()


def test_wrong_snapshot_format_is_rejected(tmp_path):
    path = tmp_path / "snap.json"
    path.write_text(make_snapshot().model_copy(update={"format": 99}).model_dump_json())
    with pytest.raises(ValueError, match="re-export"):
        load_snapshot(path)


@pytest.mark.skipif(not DEFAULT_SNAPSHOT_PATH.exists(), reason="no bundled snapshot")
def test_bundled_snapshot_is_valid():
    snapshot = load_snapshot(DEFAULT_SNAPSHOT_PATH)
    assert snapshot.products and snapshot.boms

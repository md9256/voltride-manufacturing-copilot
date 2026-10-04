from datetime import UTC, date, datetime, timedelta

import pytest

from app.schemas.erp import ManufacturingOrder, MissingComponent, StockLevel, WorkOrder
from app.services import shopfloor as sf
from tests.factories import work_center

TZ = "Asia/Hong_Kong"  # UTC+8, no daylight saving
NOW = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)  # Monday 12:00 in Hong Kong
ASM, TST = 1, 2
CENTERS = [work_center(ASM, "ASM", hours_per_day=8), work_center(TST, "TST", hours_per_day=8)]


def hk(day: int, hour: int, minute: int = 0) -> datetime:
    """A Hong Kong local time in October 2026, as UTC."""
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC) - timedelta(hours=8)


def wo(id, state, start=None, end=None, planned=60.0, actual=0.0, wc=ASM, mo=1, op="Assemble"):
    return WorkOrder(
        id=id,
        operation=op,
        production_id=mo,
        production=f"WH/MO/{mo:05d}",
        product_code="KIT",
        quantity=2,
        workcenter_id=wc,
        workcenter="Assembly" if wc == ASM else "Testing",
        state=state,
        date_start=start,
        date_finished=end,
        planned_minutes=planned,
        actual_minutes=actual,
    )


def mo(id, state, start, *, status=None, missing=()):
    return ManufacturingOrder(
        id=id,
        name=f"WH/MO/{id:05d}",
        product_code="KIT",
        product_name="Kit",
        quantity=2,
        state=state,
        date_start=start,
        date_finished=None,
        origin=None,
        components_status=status,
        missing_components=[
            MissingComponent(product_code=c, product_name=c, needed=n, reserved=r) for c, n, r in missing
        ],
    )


@pytest.mark.parametrize(
    ("work_order", "expected"),
    [
        (wo(1, "done", hk(1, 8), hk(1, 9), actual=60), "done"),
        (wo(2, "progress", hk(5, 8)), "in_progress"),
        (wo(3, "ready", hk(5, 8), hk(5, 9)), "late"),  # planned to finish 09:00, it is noon
        (wo(4, "ready", hk(5, 14), hk(5, 15)), "planned"),
        (wo(5, "ready"), None),  # not scheduled
    ],
)
def test_bar_status(work_order, expected):
    assert sf.bar_status(work_order, NOW) == expected


def test_in_progress_bar_runs_until_now_or_planned_length():
    started = wo(1, "progress", hk(5, 11, 30), planned=60)  # planned to end 12:30, now is 12:00
    assert sf.bar_interval(started, "in_progress", NOW) == (hk(5, 11, 30), hk(5, 12, 30))
    overrunning = wo(2, "progress", hk(5, 8), planned=60)  # should have ended 09:00
    assert sf.bar_interval(overrunning, "in_progress", NOW)[1] == NOW


def test_timeline_groups_by_work_center_filters_window_and_lists_unscheduled():
    orders = [
        wo(1, "done", hk(1, 8), hk(1, 9, 15), planned=60, actual=75),
        wo(2, "ready", hk(5, 14), hk(5, 15), wc=TST),
        wo(3, "done", hk(1, 8) - timedelta(days=60), hk(1, 9) - timedelta(days=60)),  # outside window
        wo(4, "ready", op="Pack"),  # unscheduled
        wo(5, "cancel", hk(5, 8), hk(5, 9)),
    ]
    t = sf.timeline(orders, start=hk(1, 0), end=hk(8, 0), now=NOW, timezone=TZ)
    assert [(r.workcenter, [b.id for b in r.bars]) for r in t.rows] == [("Assembly", [1]), ("Testing", [2])]
    assert t.rows[0].bars[0].variance_pct == 25.0
    assert [u.operation for u in t.unscheduled] == ["Pack"]


def test_variance_pct():
    assert sf.variance_pct(60, 75) == 25.0
    assert sf.variance_pct(60, 54) == -10.0
    assert sf.variance_pct(0, 10) is None


def test_stats_variance_and_overruns():
    orders = [
        wo(1, "done", hk(1, 8), hk(1, 9), planned=60, actual=90),
        wo(2, "done", hk(2, 8), hk(2, 9), planned=100, actual=90, wc=TST),
        wo(3, "done", hk(3, 8), hk(3, 9), planned=40, actual=50),
    ]
    s = sf.stats(orders, CENTERS, since=hk(1, 0), now=NOW, timezone=TZ)
    assert (s.overall.finished, s.overall.planned_minutes, s.overall.actual_minutes) == (3, 200, 230)
    assert s.overall.variance_pct == 15.0
    assert [(v.workcenter, v.variance_pct) for v in s.by_workcenter] == [("Assembly", 40.0), ("Testing", -10.0)]
    assert [o.variance_pct for o in s.top_overruns] == [50.0, 25.0]  # under-plan work is not an overrun


def test_load_splits_across_days_and_weekends_have_no_capacity():
    # 16:00 Monday to 08:00 Tuesday local (16 h slot), 960 planned minutes:
    # 8 h fall on Monday, 8 h on Tuesday.
    long = wo(1, "ready", hk(5, 16), hk(6, 8), planned=960)
    load = sf.load_by_day([long], CENTERS, first_day=date(2026, 10, 5), days=7, tz=sf.ZoneInfo(TZ), now=NOW)
    asm = {ld.day: ld for ld in load if ld.workcenter_id == ASM}
    assert (asm[date(2026, 10, 5)].planned_hours, asm[date(2026, 10, 6)].planned_hours) == (8.0, 8.0)
    assert asm[date(2026, 10, 10)].capacity_hours == 0.0  # Saturday
    assert asm[date(2026, 10, 9)].capacity_hours == 8.0  # Friday


def test_daily_facts():
    work_orders = [
        wo(1, "done", hk(5, 8), hk(5, 9, 15), planned=60, actual=75, mo=1),
        wo(2, "ready", hk(5, 13), hk(5, 14), mo=2, op="Pack"),  # scheduled today, after now
        wo(3, "ready", hk(4, 10), hk(4, 11), mo=3, op="Test", wc=TST),  # late since yesterday
        wo(4, "done", hk(4, 8), hk(4, 9), mo=4),  # finished yesterday: not today's news
        wo(5, "ready", hk(5, 15), hk(5, 16), mo=1, op="Inspect"),  # second step of running MO 1
    ]
    manufacturing = [
        mo(1, "progress", hk(5, 8), status="available"),
        mo(2, "confirmed", hk(5, 13), status="unavailable", missing=[("CHP-MCU", 10, 3)]),
        mo(3, "confirmed", hk(4, 10), status="available"),
        mo(9, "confirmed", hk(30, 8), status="unavailable"),  # beyond the 7-day horizon
    ]
    levels = [StockLevel(product_id=1, product_code="LCD-35", product_name="LCD", on_hand=0, min_qty=15, max_qty=60)]

    f = sf.daily_facts(
        date(2026, 10, 5),
        timezone=TZ,
        now=NOW,
        work_orders=work_orders,
        manufacturing_orders=manufacturing,
        stock_levels=levels,
        work_centers=CENTERS,
    )

    assert f.as_of == "2026-10-05 12:00"
    assert (f.finished_count, f.finished_planned_minutes, f.finished_actual_minutes, f.finished_variance_pct) == (
        1,
        60,
        75,
        25.0,
    )
    assert f.finished[0].finished_at == "2026-10-05 09:15"  # local time, not UTC
    assert [(s.production, s.operation) for s in f.scheduled] == [("WH/MO/00002", "Pack"), ("WH/MO/00001", "Inspect")]
    assert [(s.production, s.planned_end) for s in f.late] == [("WH/MO/00003", "2026-10-04 11:00")]
    assert [(r.production, r.work_orders_done, r.work_orders_total) for r in f.running_orders] == [
        ("WH/MO/00001", 1, 2)
    ]
    assert [r.production for r in f.material_readiness] == ["WH/MO/00003", "WH/MO/00001", "WH/MO/00002"]
    assert f.material_readiness[2].missing == [{"code": "CHP-MCU", "needed": 10, "reserved": 3, "short": 7}]
    assert f.scheduled_without_materials == [
        {
            "production": "WH/MO/00002",
            "operation": "Pack",
            "planned_start": "2026-10-05 13:00",
            "components": "unavailable",
            "short": ["CHP-MCU x7"],
        }
    ]
    assert f.low_stock == [{"code": "LCD-35", "on_hand": 0, "reorder_min": 15}]
    # Work-center names come from the work-center records ("ASM center" in the fixtures).
    assert {lf.workcenter: lf.planned_hours for lf in f.workcenter_load} == {"ASM center": 2.0}

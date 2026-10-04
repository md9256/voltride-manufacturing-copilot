"""Shop-floor logic: timeline, planned-vs-actual variance, load, daily facts.

Pure functions over ERP records (no Odoo, no LLM). The daily summary's model
only narrates the DailyFacts built here; every number it is allowed to state
is computed in this module.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas.erp import ManufacturingOrder, StockLevel, WorkCenter, WorkOrder
from app.schemas.shopfloor import (
    BarStatus,
    DailyFacts,
    FinishedFact,
    LoadDay,
    LoadFact,
    Overrun,
    ReadinessFact,
    RunningOrderFact,
    ScheduledFact,
    ShopfloorStats,
    Timeline,
    TimelineBar,
    TimelineRow,
    UnscheduledItem,
    WorkcenterVariance,
)

READINESS_HORIZON = timedelta(days=7)


def variance_pct(planned: float, actual: float) -> float | None:
    """How far actual time ran over (+) or under (-) plan, in percent."""
    return round((actual - planned) / planned * 100, 1) if planned > 0 else None


def bar_status(wo: WorkOrder, now: datetime) -> BarStatus | None:
    """None for open work orders that have no planned slot yet."""
    if wo.state == "done":
        return "done"
    if wo.state == "progress":
        return "in_progress"
    if wo.date_start is None:
        return None
    end = wo.date_finished or wo.date_start + timedelta(minutes=wo.planned_minutes)
    return "late" if end < now else "planned"


def bar_interval(wo: WorkOrder, status: BarStatus, now: datetime) -> tuple[datetime, datetime]:
    start = wo.date_start
    assert start is not None
    if status == "done":
        return start, wo.date_finished or start + timedelta(minutes=wo.actual_minutes)
    if status == "in_progress":
        # Still running: draw it up to now, or to its planned length if longer.
        return start, max(now, start + timedelta(minutes=wo.planned_minutes))
    return start, wo.date_finished or start + timedelta(minutes=wo.planned_minutes)


def timeline(work_orders: list[WorkOrder], *, start: datetime, end: datetime, now: datetime, timezone: str) -> Timeline:
    rows: dict[int, TimelineRow] = {}
    unscheduled: list[UnscheduledItem] = []
    for wo in work_orders:
        if wo.state == "cancel":
            continue
        status = bar_status(wo, now)
        if status is None:
            unscheduled.append(
                UnscheduledItem(
                    production=wo.production,
                    operation=wo.operation,
                    workcenter=wo.workcenter,
                    planned_minutes=wo.planned_minutes,
                )
            )
            continue
        bar_start, bar_end = bar_interval(wo, status, now)
        if bar_end < start or bar_start > end:
            continue
        row = rows.setdefault(
            wo.workcenter_id, TimelineRow(workcenter_id=wo.workcenter_id, workcenter=wo.workcenter, bars=[])
        )
        row.bars.append(
            TimelineBar(
                id=wo.id,
                operation=wo.operation,
                production=wo.production,
                product_code=wo.product_code,
                quantity=wo.quantity,
                status=status,
                start=bar_start,
                end=bar_end,
                planned_minutes=wo.planned_minutes,
                actual_minutes=wo.actual_minutes,
                variance_pct=variance_pct(wo.planned_minutes, wo.actual_minutes) if status == "done" else None,
            )
        )
    for row in rows.values():
        row.bars.sort(key=lambda b: b.start)
    return Timeline(
        start=start,
        end=end,
        now=now,
        timezone=timezone,
        rows=sorted(rows.values(), key=lambda r: r.workcenter),
        unscheduled=unscheduled,
    )


def _variance_row(wc_id: int, name: str, done: list[WorkOrder]) -> WorkcenterVariance:
    planned = round(sum(w.planned_minutes for w in done), 1)
    actual = round(sum(w.actual_minutes for w in done), 1)
    return WorkcenterVariance(
        workcenter_id=wc_id,
        workcenter=name,
        finished=len(done),
        planned_minutes=planned,
        actual_minutes=actual,
        variance_pct=variance_pct(planned, actual),
    )


def capacity_hours(wc: WorkCenter | None, day: date) -> float:
    """Working hours on a day. The seeded calendars are 40 h/week, Monday to
    Friday; weekends have no capacity."""
    if day.weekday() >= 5:
        return 0.0
    return wc.hours_per_day if wc else 8.0


def load_by_day(
    work_orders: list[WorkOrder],
    work_centers: list[WorkCenter],
    *,
    first_day: date,
    days: int,
    tz: ZoneInfo,
    now: datetime,
) -> list[LoadDay]:
    """Planned hours per work center per local day, for work not yet done.

    A work order's planned minutes are spread over the local days its planned
    slot overlaps, in proportion to the overlap.
    """
    hours: dict[tuple[int, date], float] = defaultdict(float)
    for wo in work_orders:
        status = bar_status(wo, now)
        if status not in ("planned", "late", "in_progress"):
            continue
        start, end = bar_interval(wo, status, now)
        span = (end - start).total_seconds()
        day = start.astimezone(tz).date()
        while True:
            day_start = datetime.combine(day, time.min, tz)
            day_end = day_start + timedelta(days=1)
            overlap = (min(end, day_end) - max(start, day_start)).total_seconds()
            if overlap > 0:
                share = overlap / span if span > 0 else 1.0
                hours[(wo.workcenter_id, day)] += wo.planned_minutes / 60 * share
            if day_end >= end:
                break
            day += timedelta(days=1)

    centers = {wc.id: wc for wc in work_centers}
    names = {wo.workcenter_id: wo.workcenter for wo in work_orders} | {wc.id: wc.name for wc in work_centers}
    return [
        LoadDay(
            day=first_day + timedelta(days=i),
            workcenter_id=wc_id,
            workcenter=names[wc_id],
            planned_hours=round(hours.get((wc_id, first_day + timedelta(days=i)), 0.0), 2),
            capacity_hours=capacity_hours(centers.get(wc_id), first_day + timedelta(days=i)),
        )
        for wc_id in sorted(names, key=lambda i: names[i])
        for i in range(days)
    ]


def stats(
    work_orders: list[WorkOrder],
    work_centers: list[WorkCenter],
    *,
    since: datetime,
    now: datetime,
    timezone: str,
    days_ahead: int = 7,
) -> ShopfloorStats:
    tz = ZoneInfo(timezone)
    done = [w for w in work_orders if w.state == "done" and w.date_finished and w.date_finished >= since]
    by_wc: dict[int, list[WorkOrder]] = defaultdict(list)
    for w in done:
        by_wc[w.workcenter_id].append(w)
    overruns = sorted(
        (
            Overrun(
                production=w.production,
                product_code=w.product_code,
                operation=w.operation,
                workcenter=w.workcenter,
                finished=w.date_finished,
                planned_minutes=w.planned_minutes,
                actual_minutes=w.actual_minutes,
                variance_pct=variance_pct(w.planned_minutes, w.actual_minutes),
            )
            for w in done
            if w.planned_minutes > 0 and w.actual_minutes > w.planned_minutes
        ),
        key=lambda o: -o.variance_pct,
    )
    return ShopfloorStats(
        since=since,
        timezone=timezone,
        overall=_variance_row(0, "All work centers", done),
        by_workcenter=sorted(
            (_variance_row(wc_id, ws[0].workcenter, ws) for wc_id, ws in by_wc.items()), key=lambda v: v.workcenter
        ),
        top_overruns=overruns[:5],
        load=load_by_day(
            work_orders, work_centers, first_day=now.astimezone(tz).date(), days=days_ahead, tz=tz, now=now
        ),
    )


def _local(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _scheduled_fact(wo: WorkOrder, status: BarStatus, now: datetime, tz: ZoneInfo) -> ScheduledFact:
    start, end = bar_interval(wo, status, now)
    return ScheduledFact(
        production=wo.production,
        product=wo.product_code,
        operation=wo.operation,
        workcenter=wo.workcenter,
        planned_start=_local(start, tz),
        planned_end=_local(end, tz),
        planned_minutes=wo.planned_minutes,
    )


def daily_facts(
    day: date,
    *,
    timezone: str,
    now: datetime,
    work_orders: list[WorkOrder],
    manufacturing_orders: list[ManufacturingOrder],
    stock_levels: list[StockLevel],
    work_centers: list[WorkCenter],
) -> DailyFacts:
    """Everything the daily briefing may say about `day`, precomputed."""
    tz = ZoneInfo(timezone)
    day_start = datetime.combine(day, time.min, tz)
    day_end = day_start + timedelta(days=1)

    finished = sorted(
        (w for w in work_orders if w.state == "done" and w.date_finished and day_start <= w.date_finished < day_end),
        key=lambda w: w.date_finished,
    )
    scheduled, late = [], []
    for w in work_orders:
        status = bar_status(w, now)
        if status in ("planned", "late") and day_start <= w.date_start < day_end:
            scheduled.append((w, status))
        if status == "late":
            late.append((w, status))

    wos_by_mo: dict[int, list[WorkOrder]] = defaultdict(list)
    for w in work_orders:
        wos_by_mo[w.production_id].append(w)
    running = [
        RunningOrderFact(
            production=mo.name,
            product=mo.product_code,
            quantity=mo.quantity,
            work_orders_done=sum(w.state == "done" for w in wos_by_mo[mo.id]),
            work_orders_total=len(wos_by_mo[mo.id]),
        )
        for mo in manufacturing_orders
        if mo.state in ("progress", "to_close")
    ]
    readiness = [
        ReadinessFact(
            production=mo.name,
            product=mo.product_code,
            quantity=mo.quantity,
            planned_start=_local(_mo_start(mo, wos_by_mo[mo.id]), tz),
            components=mo.components_status or "unknown",
            note=mo.components_note,
            missing=[
                {
                    "code": m.product_code,
                    "needed": m.needed,
                    "reserved": m.reserved,
                    "short": round(m.needed - m.reserved, 4),
                }
                for m in mo.missing_components
            ],
        )
        for mo in sorted(manufacturing_orders, key=lambda m: m.date_start)
        if mo.state in ("confirmed", "progress") and _mo_start(mo, wos_by_mo[mo.id]) < day_end + READINESS_HORIZON
    ]
    load = load_by_day(work_orders, work_centers, first_day=day, days=1, tz=tz, now=now)
    not_ready = {r.production: r for r in readiness if r.components != "available"}
    scheduled_facts = [_scheduled_fact(w, s, now, tz) for w, s in sorted(scheduled, key=lambda x: x[0].date_start)]
    finished_planned = round(sum(w.planned_minutes for w in finished), 1)
    finished_actual = round(sum(w.actual_minutes for w in finished), 1)

    return DailyFacts(
        day=day,
        timezone=timezone,
        as_of=_local(now, tz),
        finished_count=len(finished),
        finished_planned_minutes=finished_planned,
        finished_actual_minutes=finished_actual,
        finished_variance_pct=variance_pct(finished_planned, finished_actual),
        finished=[
            FinishedFact(
                production=w.production,
                product=w.product_code,
                operation=w.operation,
                workcenter=w.workcenter,
                finished_at=_local(w.date_finished, tz),
                planned_minutes=w.planned_minutes,
                actual_minutes=w.actual_minutes,
                variance_pct=variance_pct(w.planned_minutes, w.actual_minutes),
            )
            for w in finished
        ],
        running_orders=running,
        scheduled=scheduled_facts,
        late=[_scheduled_fact(w, s, now, tz) for w, s in sorted(late, key=lambda x: x[0].date_start)],
        material_readiness=readiness,
        scheduled_without_materials=[
            {
                "production": f.production,
                "operation": f.operation,
                "planned_start": f.planned_start,
                "components": not_ready[f.production].components,
                "short": [f"{m['code']} x{m['short']:g}" for m in not_ready[f.production].missing],
            }
            for f in scheduled_facts
            if f.production in not_ready
        ],
        workcenter_load=[
            LoadFact(workcenter=ld.workcenter, planned_hours=ld.planned_hours, capacity_hours=ld.capacity_hours)
            for ld in load
            if ld.planned_hours > 0
        ],
        orders_by_state=dict(Counter(mo.state for mo in manufacturing_orders)),
        low_stock=[
            {"code": s.product_code, "on_hand": s.on_hand, "reorder_min": s.min_qty}
            for s in sorted(stock_levels, key=lambda s: s.on_hand / s.min_qty if s.min_qty else 0)
            if s.on_hand < s.min_qty
        ],
    )


def _mo_start(mo: ManufacturingOrder, wos: list[WorkOrder]) -> datetime:
    """Earliest planned work-order slot, falling back to the MO's own date."""
    starts = [w.date_start for w in wos if w.date_start and w.state not in ("done", "cancel")]
    return min(starts, default=mo.date_start).astimezone(UTC)

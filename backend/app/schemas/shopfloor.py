"""Shop-floor (MES) view: timeline, variance, load, and daily production facts."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

BarStatus = Literal["done", "in_progress", "planned", "late"]


class TimelineBar(BaseModel):
    id: int
    operation: str
    production: str
    product_code: str | None
    quantity: float
    status: BarStatus
    start: datetime
    end: datetime
    planned_minutes: float
    actual_minutes: float
    variance_pct: float | None  # finished work orders only


class TimelineRow(BaseModel):
    workcenter_id: int
    workcenter: str
    bars: list[TimelineBar]


class UnscheduledItem(BaseModel):
    production: str
    operation: str
    workcenter: str
    planned_minutes: float


class Timeline(BaseModel):
    start: datetime
    end: datetime
    now: datetime
    timezone: str
    rows: list[TimelineRow]
    unscheduled: list[UnscheduledItem]  # open work orders without a planned slot


class WorkcenterVariance(BaseModel):
    workcenter_id: int
    workcenter: str
    finished: int
    planned_minutes: float
    actual_minutes: float
    variance_pct: float | None


class Overrun(BaseModel):
    production: str
    product_code: str | None
    operation: str
    workcenter: str
    finished: datetime
    planned_minutes: float
    actual_minutes: float
    variance_pct: float


class LoadDay(BaseModel):
    day: date
    workcenter_id: int
    workcenter: str
    planned_hours: float
    capacity_hours: float


class ShopfloorStats(BaseModel):
    since: datetime
    timezone: str
    overall: WorkcenterVariance  # all work centers together (id 0)
    by_workcenter: list[WorkcenterVariance]
    top_overruns: list[Overrun]
    load: list[LoadDay]


# --- facts for the AI daily summary --------------------------------------------
# Times are local strings ("2026-10-05 08:00") so the model never converts
# time zones itself; every figure it may quote is precomputed here.


class FinishedFact(BaseModel):
    production: str
    product: str | None
    operation: str
    workcenter: str
    finished_at: str
    planned_minutes: float
    actual_minutes: float
    variance_pct: float | None


class ScheduledFact(BaseModel):
    production: str
    product: str | None
    operation: str
    workcenter: str
    planned_start: str
    planned_end: str
    planned_minutes: float


class RunningOrderFact(BaseModel):
    production: str
    product: str | None
    quantity: float
    work_orders_done: int
    work_orders_total: int


class ReadinessFact(BaseModel):
    production: str
    product: str | None
    quantity: float
    planned_start: str
    components: str  # available | expected | late | unavailable
    note: str | None
    missing: list[dict]  # [{"code", "needed", "reserved", "short"}]


class LoadFact(BaseModel):
    workcenter: str
    planned_hours: float
    capacity_hours: float


class DailyFacts(BaseModel):
    day: date
    timezone: str
    as_of: str
    finished_count: int
    finished_planned_minutes: float
    finished_actual_minutes: float
    finished_variance_pct: float | None
    finished: list[FinishedFact]
    running_orders: list[RunningOrderFact]
    scheduled: list[ScheduledFact]
    late: list[ScheduledFact]  # planned to have finished by now, not done
    material_readiness: list[ReadinessFact]  # open orders starting within 7 days
    # Work scheduled on this day for orders whose components are not all
    # available: the combination a supervisor most needs to hear about.
    scheduled_without_materials: list[dict]  # [{"production", "operation", "planned_start", "components", "short"}]
    workcenter_load: list[LoadFact]
    orders_by_state: dict[str, int]
    low_stock: list[dict]  # [{"code", "on_hand", "reorder_min"}]


SummaryLanguage = Literal["en", "zh-Hans", "zh-Hant"]


class SummaryRequest(BaseModel):
    day: date | None = None  # default: today in the company time zone
    language: SummaryLanguage = "en"
    regenerate: bool = False


class SummaryView(BaseModel):
    day: date
    language: SummaryLanguage
    text: str
    unverified_numbers: list[str]  # figures in the text not found in the facts
    facts: DailyFacts
    cached: bool
    provider: str
    model: str
    created_at: datetime

"""Dashboard business rules, as pure functions over ERP records.

No Odoo or HTTP here, so every rule is unit-testable with plain fixtures.
"""

from collections import Counter
from datetime import date, datetime, timedelta

from app.schemas.dashboard import WeeklyOrders
from app.schemas.erp import ManufacturingOrder, SaleOrder, StockLevel

QUOTATION_STATES = {"draft", "sent"}


def is_open_sale_order(order: SaleOrder) -> bool:
    """A quotation, or a confirmed order not yet fully delivered.

    Odoo 17+ dropped the "done" state for sale orders, so "still to do" has to
    be derived from the delivery status rather than read from `state`.
    """
    if order.state in QUOTATION_STATES:
        return True
    return order.state == "sale" and order.delivery_status != "full"


def open_sale_orders(orders: list[SaleOrder]) -> list[SaleOrder]:
    return [o for o in orders if is_open_sale_order(o)]


def active_manufacturing_orders(orders: list[ManufacturingOrder]) -> list[ManufacturingOrder]:
    return [o for o in orders if o.state not in {"done", "cancel"}]


def manufacturing_state_counts(orders: list[ManufacturingOrder]) -> dict[str, int]:
    return dict(Counter(o.state for o in orders))


def low_stock(levels: list[StockLevel]) -> list[StockLevel]:
    """Products below their reorder minimum, most critical (lowest coverage) first."""
    short = [lvl for lvl in levels if lvl.on_hand < lvl.min_qty]
    return sorted(short, key=lambda lvl: lvl.on_hand / lvl.min_qty if lvl.min_qty else 0)


def week_start(d: date) -> date:
    """Monday of the ISO week containing `d`."""
    return d - timedelta(days=d.weekday())


def orders_over_time(orders: list[SaleOrder], *, weeks: int, today: date) -> list[WeeklyOrders]:
    """Confirmed sale orders per week for the last `weeks` weeks, including empty weeks.

    Quotations and cancelled orders are excluded: the chart shows committed demand.
    """
    first_week = week_start(today) - timedelta(weeks=weeks - 1)
    buckets = {
        first_week + timedelta(weeks=i): WeeklyOrders(week_start=first_week + timedelta(weeks=i)) for i in range(weeks)
    }
    for order in orders:
        if order.state != "sale":
            continue
        bucket = buckets.get(week_start(order.date_order.date()))
        if bucket:
            bucket.order_count += 1
            bucket.revenue += order.amount_total
    return list(buckets.values())


def orders_window_start(*, weeks: int, today: date) -> datetime:
    """Earliest order date `orders_over_time` needs; lets callers fetch less from Odoo."""
    first = week_start(today) - timedelta(weeks=weeks - 1)
    return datetime(first.year, first.month, first.day)

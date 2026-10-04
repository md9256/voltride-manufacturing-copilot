from datetime import date

from app.services import dashboard as rules
from tests.fakes import sale_order, stock, utc


def test_open_sale_orders_include_quotations_and_undelivered():
    orders = [
        sale_order(1, "draft", None),
        sale_order(2, "sent", None),
        sale_order(3, "sale", "pending"),
        sale_order(4, "sale", "partial"),
        sale_order(5, "sale", "full"),
        sale_order(6, "cancel", None),
    ]
    assert [o.id for o in rules.open_sale_orders(orders)] == [1, 2, 3, 4]


def test_low_stock_sorted_by_coverage():
    levels = [stock("A", 10, 20), stock("B", 0, 5), stock("C", 30, 20), stock("D", 9, 10)]
    assert [s.product_code for s in rules.low_stock(levels)] == ["B", "A", "D"]


def test_low_stock_ignores_exactly_at_minimum():
    assert rules.low_stock([stock("A", 20, 20)]) == []


def test_orders_over_time_buckets_confirmed_orders_by_week():
    today = date(2026, 10, 4)  # a Sunday; its week starts Monday 2026-09-28
    orders = [
        sale_order(1, "sale", when=utc(2026, 9, 28, 9), amount=100),
        sale_order(2, "sale", when=utc(2026, 10, 4, 23), amount=50),
        sale_order(3, "sale", when=utc(2026, 9, 15, 9), amount=10),
        sale_order(4, "draft", when=utc(2026, 9, 29), amount=999),  # quotation: excluded
        sale_order(5, "cancel", when=utc(2026, 9, 29), amount=999),  # cancelled: excluded
        sale_order(6, "sale", when=utc(2026, 1, 1), amount=999),  # outside the window
    ]

    weeks = rules.orders_over_time(orders, weeks=3, today=today)

    assert [w.week_start for w in weeks] == [date(2026, 9, 14), date(2026, 9, 21), date(2026, 9, 28)]
    assert [(w.order_count, w.revenue) for w in weeks] == [(1, 10), (0, 0), (2, 150)]


def test_orders_window_start_is_monday_of_first_week():
    start = rules.orders_window_start(weeks=3, today=date(2026, 10, 4))
    assert start.date() == date(2026, 9, 14)

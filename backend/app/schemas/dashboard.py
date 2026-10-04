"""Response schemas for the dashboard and health endpoints."""

from datetime import date

from pydantic import BaseModel


class OdooStatus(BaseModel):
    mode: str
    reachable: bool
    version: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    odoo: OdooStatus


class DashboardSummary(BaseModel):
    currency: str
    open_sales_count: int
    open_sales_value: float
    quotations_count: int
    manufacturing_by_state: dict[str, int]
    active_manufacturing_count: int
    low_stock_count: int


class WeeklyOrders(BaseModel):
    week_start: date
    order_count: int = 0
    revenue: float = 0.0

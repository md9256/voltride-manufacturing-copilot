"""Proposed write actions: what will be written if the user confirms."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProposalLine(BaseModel):
    product_id: int
    code: str | None
    name: str
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)
    subtotal: float
    note: str | None = None  # e.g. "rounded up to supplier minimum of 50"


class ProposalOrder(BaseModel):
    supplier_id: int
    supplier: str
    partner_ref: str | None = None  # vendor's reference (their quote number)
    lead_days: int | None = None
    lines: list[ProposalLine] = Field(min_length=1)
    total: float


class QuoteSource(BaseModel):
    review_id: str
    quote_number: str | None
    filename: str
    file_sha256: str


class PurchaseProposal(BaseModel):
    kind: Literal["purchase_orders"] = "purchase_orders"
    summary: str  # human description, e.g. "Order shortages for building 10 x KIT-MID"
    currency: str
    orders: list[ProposalOrder] = Field(min_length=1)
    total: float
    warnings: list[str] = []
    quote: QuoteSource | None = None


class CreatedPurchaseOrder(BaseModel):
    name: str
    supplier: str
    amount_total: float
    url: str | None
    simulated: bool  # demo mode: never written to an ERP


class ActionView(BaseModel):
    id: str
    kind: str
    source: str
    status: Literal["pending", "executing", "executed", "failed", "rejected", "expired"]
    payload: PurchaseProposal
    created: list[CreatedPurchaseOrder] = []
    error: str | None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None

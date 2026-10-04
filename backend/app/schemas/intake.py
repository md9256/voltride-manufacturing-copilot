"""Supplier quote intake: what the LLM extracts, and the review shown to the user."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --- what the model must return (its JSON schema is sent to the provider) ---


class ExtractedQuoteLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="Line text exactly as printed.")
    supplier_product_code: str | None = Field(description="Product or part code printed on the line, if any.")
    quantity: float | None
    unit_price: float | None
    line_total: float | None = Field(description="The line amount as printed, not recomputed.")


class ExtractedQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["quote", "invoice", "other"]
    supplier_name: str | None = Field(description="The company issuing the document (the seller).")
    quote_number: str | None = Field(description="The document's own quote / invoice number.")
    quote_date: str | None = Field(description="Document date as YYYY-MM-DD if possible.")
    currency: str | None = Field(description="ISO 4217 code, e.g. HKD, USD.")
    lines: list[ExtractedQuoteLine]
    subtotal: float | None
    tax: float | None
    total: float | None
    uncertain_fields: list[str] = Field(
        description='Fields you could not read confidently, as paths like "total" or "lines[2].unit_price".'
    )


# --- the review (server-computed; the browser only sends corrections) ---


class Flag(BaseModel):
    severity: Literal["error", "warning"]  # errors block creating the order
    field: str  # "supplier", "total", "lines[1].unit_price", ...
    message: str


class ProductOption(BaseModel):
    id: int
    code: str | None
    name: str


class LineReview(BaseModel):
    index: int
    description: str
    supplier_product_code: str | None
    quantity: float | None
    unit_price: float | None
    line_total: float | None
    include: bool
    product: ProductOption | None
    match: Literal["code", "name", "manual", "none"]
    candidates: list[ProductOption]
    agreed_price: float | None  # this supplier's price-list price, when it has one
    flags: list[Flag]


class QuoteReviewView(BaseModel):
    id: str
    filename: str
    document_type: str
    supplier_name: str | None  # as printed
    supplier: ProductOption | None  # matched vendor (id, name); reuses the id/name shape
    supplier_match: Literal["exact", "fuzzy", "manual", "none"]
    supplier_candidates: list[ProductOption]
    quote_number: str | None
    quote_date: str | None
    currency: str | None
    company_currency: str
    lines: list[LineReview]
    subtotal: float | None
    tax: float | None
    total: float | None
    computed_total: float  # included lines at reviewed quantities and prices
    flags: list[Flag]  # document-level
    can_propose: bool


class LineCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int | None = None
    quantity: float | None = Field(None, gt=0)
    unit_price: float | None = Field(None, ge=0)
    line_total: float | None = Field(None, ge=0)
    include: bool | None = None


class ReviewCorrections(BaseModel):
    """The user's edits. Every override is recorded in the audit log."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: int | None = None
    lines: dict[int, LineCorrection] = {}

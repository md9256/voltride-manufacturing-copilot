"""Supplier quote intake: upload a PDF, review the extraction, propose a draft PO.

The PDF is processed in memory and never stored (the host disk is ephemeral
and quotes can be commercially sensitive); only its SHA-256 and the extracted
fields are kept, for duplicate detection and the review.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.extraction import ExtractionError, extract_quote
from app.ai.providers import LLMError
from app.api.deps import ClientId, Db, Provider
from app.models.actions import ProposedAction, QuoteReview
from app.odoo import OdooClient, get_odoo_client
from app.schemas.actions import ActionView
from app.schemas.intake import ExtractedQuote, QuoteReviewView, ReviewCorrections
from app.services import actions, audit
from app.services.bom import ManufacturingData
from app.services.purchasing import ProposalError
from app.services.quote_intake import ReviewContext, build_review, review_to_proposal

router = APIRouter(prefix="/api/intake", tags=["intake"])

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20

Odoo = Annotated[OdooClient, Depends(get_odoo_client)]


def check_pdf(content: bytes) -> int:
    """Reject anything that is not a reasonably sized, readable PDF. Returns the page count."""
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(415, "Only PDF files are accepted.")  # by content, not by file name
    try:
        pages = len(PdfReader(io.BytesIO(content)).pages)
    except (PdfReadError, ValueError, OSError):
        raise HTTPException(422, "The PDF could not be read (damaged or encrypted).") from None
    if pages == 0 or pages > MAX_PAGES:
        raise HTTPException(422, f"PDF must have between 1 and {MAX_PAGES} pages (this one has {pages}).")
    return pages


@router.post("/quotes", response_model=QuoteReviewView)
async def upload_quote(
    file: UploadFile, db: Db, client_id: ClientId, provider: Provider, odoo: Odoo
) -> QuoteReviewView:
    content = await file.read(MAX_PDF_BYTES + 1)
    pages = await asyncio.to_thread(check_pdf, content)
    sha256 = hashlib.sha256(content).hexdigest()
    filename = (file.filename or "quote.pdf")[:255]

    started = time.perf_counter()
    try:
        extracted = await extract_quote(provider, content)
    except (LLMError, ExtractionError) as exc:
        await audit.record(
            db,
            kind="extraction",
            name="supplier_quote",
            owner_id=client_id,
            ok=False,
            params={"filename": filename, "sha256": sha256, "pages": pages},
            result={"error": str(exc)},
            provider=provider.name,
            model=provider.model,
        )
        raise HTTPException(502, str(exc)) from None
    duration_ms = round((time.perf_counter() - started) * 1000, 1)

    seen_before = await db.scalar(select(QuoteReview.id).where(QuoteReview.file_sha256 == sha256).limit(1))
    review = QuoteReview(
        id=str(uuid.uuid4()),
        owner_id=client_id,
        file_sha256=sha256,
        filename=filename,
        extraction=extracted.model_dump(mode="json"),
        provider=provider.name,
        model=provider.model,
    )
    db.add(review)
    await audit.record(
        db,
        kind="extraction",
        name="supplier_quote",
        owner_id=client_id,
        params={"filename": filename, "sha256": sha256, "pages": pages, "review_id": review.id},
        result=review.extraction,
        duration_ms=duration_ms,
        provider=provider.name,
        model=provider.model,
    )
    return await _review(db, review, odoo, ReviewCorrections(), seen_before=seen_before is not None)


@router.post("/quotes/{review_id}/review", response_model=QuoteReviewView)
async def recheck(
    review_id: str, corrections: ReviewCorrections, db: Db, client_id: ClientId, odoo: Odoo
) -> QuoteReviewView:
    """Re-run every check with the user's corrections applied."""
    review = await _load(db, client_id, review_id)
    return await _review(db, review, odoo, corrections)


@router.post("/quotes/{review_id}/propose", response_model=ActionView)
async def propose(
    review_id: str, corrections: ReviewCorrections, db: Db, client_id: ClientId, odoo: Odoo
) -> ActionView:
    """Create a proposal from the reviewed quote. It still needs the user's Confirm."""
    review = await _load(db, client_id, review_id)
    view = await _review(db, review, odoo, corrections)
    if not view.can_propose:
        raise HTTPException(422, "Resolve the errors in the review first.")
    try:
        proposal = review_to_proposal(view, file_sha256=review.file_sha256)
    except (ValueError, ProposalError) as exc:
        raise HTTPException(422, str(exc)) from None
    action = await actions.create_proposal(
        db,
        owner_id=client_id,
        proposal=proposal,
        source="quote_intake",
        question=f"Quote intake: {review.filename}; corrections: {corrections.model_dump_json(exclude_defaults=True)}",
    )
    return actions.to_view(action)


async def _load(db: AsyncSession, client_id: str, review_id: str) -> QuoteReview:
    review = await db.get(QuoteReview, review_id)
    if review is None or review.owner_id != client_id:
        raise HTTPException(404, "Quote review not found")
    return review


async def _review(
    db: AsyncSession,
    review: QuoteReview,
    odoo: OdooClient,
    corrections: ReviewCorrections,
    *,
    seen_before: bool | None = None,
) -> QuoteReviewView:
    extracted = ExtractedQuote.model_validate(review.extraction)
    if seen_before is None:
        seen_before = (
            await db.scalar(
                select(QuoteReview.id)
                .where(QuoteReview.file_sha256 == review.file_sha256, QuoteReview.created_at < review.created_at)
                .limit(1)
            )
            is not None
        )
    pending = await db.scalars(
        select(ProposedAction).where(ProposedAction.status == "pending", ProposedAction.source == "quote_intake")
    )
    pending_quotes = [
        (order["supplier_id"], (a.payload.get("quote") or {}).get("quote_number") or "")
        for a in pending
        if (a.payload.get("quote") or {}).get("review_id") != review.id
        for order in a.payload["orders"]
    ]

    def erp_context() -> ReviewContext:
        return ReviewContext(
            data=ManufacturingData.build(odoo.list_products(), odoo.list_boms(), odoo.list_work_centers()),
            suppliers=odoo.list_suppliers(),
            company_currency=odoo.company_currency(),
            existing_orders=odoo.find_purchase_orders(partner_ref=extracted.quote_number)
            if extracted.quote_number
            else [],
            pending_quotes=pending_quotes,
            seen_file_before=seen_before,
        )

    ctx = await asyncio.to_thread(erp_context)
    return build_review(review.id, review.filename, extracted, ctx, corrections)

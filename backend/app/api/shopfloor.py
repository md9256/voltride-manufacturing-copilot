"""Shop-floor (MES) endpoints: timeline, statistics, and the AI daily summary."""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.ai.providers import LLMError
from app.ai.summary import untraceable_numbers, write_summary
from app.api.deps import ClientId, Db, Provider
from app.config import get_settings
from app.models.actions import ProductionSummary
from app.odoo import OdooClient, get_odoo_client
from app.schemas.shopfloor import DailyFacts, ShopfloorStats, SummaryRequest, SummaryView, Timeline
from app.services import audit
from app.services import shopfloor as rules

router = APIRouter(prefix="/api/shopfloor", tags=["shopfloor"])

Odoo = Annotated[OdooClient, Depends(get_odoo_client)]


def _now() -> datetime:
    return datetime.now(UTC)


@router.get("/timeline", response_model=Timeline)
def timeline(
    odoo: Odoo,
    days_back: Annotated[int, Query(ge=0, le=90)] = 21,
    days_ahead: Annotated[int, Query(ge=1, le=30)] = 7,
) -> Timeline:
    """Work orders in a window around now."""
    now = _now()
    return rules.timeline(
        odoo.list_work_orders(),
        start=now - timedelta(days=days_back),
        end=now + timedelta(days=days_ahead),
        now=now,
        timezone=get_settings().company_timezone,
    )


@router.get("/stats", response_model=ShopfloorStats)
def stats(odoo: Odoo, weeks: Annotated[int, Query(ge=1, le=52)] = 6) -> ShopfloorStats:
    now = _now()
    return rules.stats(
        odoo.list_work_orders(),
        odoo.list_work_centers(),
        since=now - timedelta(weeks=weeks),
        now=now,
        timezone=get_settings().company_timezone,
    )


def facts_for(odoo: OdooClient, day: date) -> DailyFacts:
    return rules.daily_facts(
        day,
        timezone=get_settings().company_timezone,
        now=_now(),
        work_orders=odoo.list_work_orders(),
        manufacturing_orders=odoo.list_manufacturing_orders(),
        stock_levels=odoo.list_stock_levels(),
        work_centers=odoo.list_work_centers(),
    )


def facts_hash(facts: DailyFacts) -> str:
    # "as_of" changes on every request; leaving it out lets identical data
    # reuse the cached summary instead of spending another LLM call.
    return hashlib.sha256(facts.model_dump_json(exclude={"as_of"}).encode()).hexdigest()


@router.post("/summary", response_model=SummaryView)
async def summary(body: SummaryRequest, db: Db, client_id: ClientId, provider: Provider, odoo: Odoo) -> SummaryView:
    tz = ZoneInfo(get_settings().company_timezone)
    day = body.day or _now().astimezone(tz).date()
    facts = await asyncio.to_thread(facts_for, odoo, day)
    digest = facts_hash(facts)

    if not body.regenerate:
        cached = await db.scalar(
            select(ProductionSummary)
            .where(
                ProductionSummary.day == day.isoformat(),
                ProductionSummary.language == body.language,
                ProductionSummary.facts_hash == digest,
            )
            .order_by(ProductionSummary.id.desc())
            .limit(1)
        )
        if cached:
            return _view(cached, facts, cached=True)

    started = time.perf_counter()
    try:
        text = await write_summary(provider, facts, body.language)
    except LLMError as exc:
        await audit.record(
            db,
            kind="summary",
            name="daily_production",
            owner_id=client_id,
            ok=False,
            params={"day": day.isoformat(), "language": body.language},
            result={"error": str(exc)},
            provider=provider.name,
            model=provider.model,
        )
        raise HTTPException(502, str(exc)) from None
    unverified = untraceable_numbers(text, facts)

    row = await db.scalar(
        select(ProductionSummary).where(
            ProductionSummary.day == day.isoformat(),
            ProductionSummary.language == body.language,
            ProductionSummary.facts_hash == digest,
        )
    )
    if row is None:
        row = ProductionSummary(day=day.isoformat(), language=body.language, facts_hash=digest)
        db.add(row)
    row.facts = facts.model_dump(mode="json")
    row.text = text
    row.unverified = unverified
    row.provider = provider.name
    row.model = provider.model
    row.created_at = _now()
    await audit.record(
        db,
        kind="summary",
        name="daily_production",
        owner_id=client_id,
        params={"day": day.isoformat(), "language": body.language, "regenerate": body.regenerate},
        result={"text": text, "unverified_numbers": unverified},
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        provider=provider.name,
        model=provider.model,
    )  # commits the summary row too
    return _view(row, facts, cached=False)


def _view(row: ProductionSummary, facts: DailyFacts, *, cached: bool) -> SummaryView:
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
    return SummaryView(
        day=date.fromisoformat(row.day),
        language=row.language,
        text=row.text,
        unverified_numbers=row.unverified,
        facts=facts,
        cached=cached,
        provider=row.provider,
        model=row.model,
        created_at=created,
    )

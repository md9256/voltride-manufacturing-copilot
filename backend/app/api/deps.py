"""Request dependencies shared by the chat, actions, intake and audit routers."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.providers import LLMProvider, ProviderNotConfigured, make_provider
from app.config import get_settings
from app.models.db import DatabaseNotConfigured, get_sessionmaker


def get_provider() -> LLMProvider:
    try:
        return make_provider(get_settings())
    except ProviderNotConfigured as exc:
        raise HTTPException(503, f"AI assistant is not configured: {exc}") from exc


def get_db_sessionmaker() -> async_sessionmaker[AsyncSession]:
    try:
        return get_sessionmaker()
    except DatabaseNotConfigured as exc:
        raise HTTPException(503, f"App database is not configured: {exc}") from exc


async def get_db(makers: Annotated[async_sessionmaker[AsyncSession], Depends(get_db_sessionmaker)]):
    async with makers() as session:
        yield session


def get_client_id(x_client_id: Annotated[str, Header()]) -> str:
    """Anonymous browser id scoping conversations, proposals and reviews.

    Not authentication (that arrives in Phase 6), but every lookup filters by
    it, so one visitor cannot read or confirm another's proposals by id.
    """
    try:
        return str(uuid.UUID(x_client_id))
    except ValueError:
        raise HTTPException(400, "X-Client-Id must be a UUID") from None


ClientId = Annotated[str, Depends(get_client_id)]
Db = Annotated[AsyncSession, Depends(get_db)]
Makers = Annotated[async_sessionmaker[AsyncSession], Depends(get_db_sessionmaker)]
Provider = Annotated[LLMProvider, Depends(get_provider)]

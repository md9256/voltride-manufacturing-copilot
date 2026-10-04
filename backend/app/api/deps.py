"""Request dependencies shared by the chat, actions, intake and audit routers."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.providers import LLMProvider, ModelNotAllowed, ProviderNotConfigured, make_provider
from app.config import get_settings
from app.models.db import DatabaseNotConfigured, get_sessionmaker

ProviderFactoryFn = Callable[[str | None], LLMProvider]


def get_provider_factory() -> ProviderFactoryFn:
    """Builds the configured provider for a given model (None: the default).

    A factory rather than a single provider because a conversation keeps the
    model it started with, which may differ from the one picked in the UI now.
    """

    def factory(model: str | None) -> LLMProvider:
        try:
            return make_provider(get_settings(), model)
        except ModelNotAllowed as exc:
            raise HTTPException(400, str(exc)) from exc
        except ProviderNotConfigured as exc:
            raise HTTPException(503, f"AI assistant is not configured: {exc}") from exc

    return factory


ProviderFactory = Annotated[ProviderFactoryFn, Depends(get_provider_factory)]


def get_provider(factory: ProviderFactory, x_llm_model: Annotated[str | None, Header()] = None) -> LLMProvider:
    """The LLM for this request: the model picked in the UI (X-LLM-Model), if allowed."""
    return factory(x_llm_model or None)


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

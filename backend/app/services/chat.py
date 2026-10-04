"""Chat orchestration: the tool-use loop between the user, the LLM and the tools.

One user message can take several LLM turns: the model asks for tools, we run
them, send the results back, and repeat until it answers in text. Each step is
saved as it happens and reported to the browser as a stream of events.

Why a hand-written loop rather than an SDK tool runner: we need to stream
progress events, validate every call through our own ToolRunner, persist each
step, cap the number of rounds, and support two providers with one loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import build_system_prompt
from app.ai.providers import LLMError, LLMProvider, TextDelta, ToolCall, TurnResult
from app.ai.tools import TOOLS, ToolContext, ToolOutcome, ToolRunner
from app.models.chat import Conversation
from app.odoo import OdooClient, OdooError
from app.services import chat_store

MAX_TOOL_ROUNDS = 8


@dataclass
class ChatEvent:
    """One server-sent event for the browser."""

    type: str  # text | tool_started | tool_finished | done | error
    data: dict

    def as_dict(self) -> dict:
        return {"type": self.type, **self.data}


def history_of(conv: Conversation) -> list[dict]:
    return [native for message in conv.messages for native in message.native]


async def run_chat_turn(
    *,
    session: AsyncSession,
    conv: Conversation,
    text: str,
    provider: LLMProvider,
    odoo: OdooClient,
) -> AsyncIterator[ChatEvent]:
    history = history_of(conv)
    user_native = provider.user_message(text)
    await chat_store.append_message(session, conv, role="user", native=user_native, display={"text": text})
    history.extend(user_native)

    try:
        currency = await asyncio.to_thread(odoo.company_currency)
    except OdooError:
        currency = "unknown"
    system = build_system_prompt(today=datetime.now(UTC).date(), currency=currency)
    runner = ToolRunner(ToolContext(odoo))

    for _ in range(MAX_TOOL_ROUNDS):
        result: TurnResult | None = None
        try:
            async for item in provider.stream_turn(system, history, TOOLS):
                if isinstance(item, TextDelta):
                    yield ChatEvent("text", {"delta": item.text})
                else:
                    result = item
        except LLMError as exc:
            yield ChatEvent("error", {"message": str(exc)})
            return
        assert result is not None, "provider ended a turn without a TurnResult"

        await chat_store.append_message(
            session,
            conv,
            role="assistant",
            native=result.native,
            display={
                "text": result.text,
                "tool_calls": [{"id": c.id, "name": c.name, "input": c.arguments} for c in result.tool_calls],
            },
        )
        history.extend(result.native)

        if result.stop == "refusal":
            yield ChatEvent("text", {"delta": "\n\n_The model declined to answer this request._"})
        if not result.tool_calls:
            if result.stop == "max_tokens":
                yield ChatEvent("text", {"delta": "\n\n_(The answer was cut off because it got too long.)_"})
            yield ChatEvent("done", {})
            return

        for call in result.tool_calls:
            yield ChatEvent("tool_started", {"id": call.id, "name": call.name, "input": call.arguments})
        outcomes = await _run_tools(runner, result.tool_calls)
        for call, outcome in outcomes:
            yield ChatEvent(
                "tool_finished", {"id": call.id, "name": call.name, "ok": outcome.ok, "summary": outcome.summary}
            )

        native = provider.tool_results(outcomes)
        await chat_store.append_message(
            session,
            conv,
            role="tool",
            native=native,
            display={"results": [{"id": c.id, "ok": o.ok, "summary": o.summary} for c, o in outcomes]},
        )
        history.extend(native)

    # The model kept calling tools; stop rather than loop (and spend) forever.
    yield ChatEvent("error", {"message": "Stopped after too many tool calls. Try a more specific question."})


async def _run_tools(runner: ToolRunner, calls: list[ToolCall]) -> list[tuple[ToolCall, ToolOutcome]]:
    """Run one turn's tool calls concurrently (they are read-only).

    Tools are synchronous (blocking Odoo HTTP calls), so each runs in a worker
    thread; results keep the order of the calls.
    """
    outcomes = await asyncio.gather(*(asyncio.to_thread(runner.run, c.name, c.arguments) for c in calls))
    return list(zip(calls, outcomes, strict=True))

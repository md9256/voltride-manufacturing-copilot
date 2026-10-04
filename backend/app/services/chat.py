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
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import build_system_prompt
from app.ai.providers import LLMError, LLMProvider, TextDelta, ToolCall, TurnResult
from app.ai.tools import TOOLS, ToolContext, ToolOutcome, ToolRunner
from app.models.chat import Conversation
from app.odoo import OdooClient, OdooError
from app.services import actions, audit, chat_store

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

        action_ids: dict[str, str] = {}
        for call, outcome, duration_ms in outcomes:
            if outcome.proposal is not None:
                action = await actions.create_proposal(
                    session,
                    owner_id=conv.owner_id,
                    conversation_id=conv.id,
                    proposal=outcome.proposal,
                    source="chat",
                    question=text,
                )
                action_ids[call.id] = action.id
                outcome.content = _proposal_message(action.id, outcome)
                view = actions.to_view(action).model_dump(mode="json")
                yield ChatEvent("action_proposed", {"tool_call_id": call.id, "action": view})
            await audit.record(
                session,
                kind="tool_call",
                name=call.name,
                owner_id=conv.owner_id,
                conversation_id=conv.id,
                question=text,
                params=call.arguments if isinstance(call.arguments, dict) else {"raw": call.arguments},
                result=outcome.content,
                ok=outcome.ok,
                duration_ms=duration_ms,
                provider=provider.name,
                model=provider.model,
            )
            yield ChatEvent(
                "tool_finished", {"id": call.id, "name": call.name, "ok": outcome.ok, "summary": outcome.summary}
            )

        pairs = [(call, outcome) for call, outcome, _ in outcomes]
        native = provider.tool_results(pairs)
        await chat_store.append_message(
            session,
            conv,
            role="tool",
            native=native,
            display={
                "results": [
                    {"id": c.id, "ok": o.ok, "summary": o.summary, "action_id": action_ids.get(c.id)} for c, o in pairs
                ]
            },
        )
        history.extend(native)

    # The model kept calling tools; stop rather than loop (and spend) forever.
    yield ChatEvent("error", {"message": "Stopped after too many tool calls. Try a more specific question."})


async def _run_tools(runner: ToolRunner, calls: list[ToolCall]) -> list[tuple[ToolCall, ToolOutcome, float]]:
    """Run one turn's tool calls concurrently (none of them write to the ERP).

    Tools are synchronous (blocking Odoo HTTP calls), so each runs in a worker
    thread; results keep the order of the calls, with durations for the audit log.
    """

    def timed(call: ToolCall) -> tuple[ToolOutcome, float]:
        start = time.perf_counter()
        outcome = runner.run(call.name, call.arguments)
        return outcome, round((time.perf_counter() - start) * 1000, 1)

    results = await asyncio.gather(*(asyncio.to_thread(timed, c) for c in calls))
    return [(call, outcome, ms) for call, (outcome, ms) in zip(calls, results, strict=True)]


def _proposal_message(action_id: str, outcome: ToolOutcome) -> str:
    """What the model is told after proposing: exactly what exists, and what does not."""
    p = outcome.proposal
    return json.dumps(
        {
            "proposal_id": action_id,
            "status": "awaiting_user_confirmation",
            "important": "Nothing has been created in the ERP. The user sees this proposal with Confirm and "
            "Reject buttons. Summarise it briefly and ask them to review it; do not say it was ordered.",
            "summary": p.summary,
            "currency": p.currency,
            "total": p.total,
            "orders": [
                {
                    "supplier": o.supplier,
                    "total": o.total,
                    "lead_days": o.lead_days,
                    "lines": [
                        {"code": ln.code, "quantity": ln.quantity, "unit_price": ln.unit_price} for ln in o.lines
                    ],
                }
                for o in p.orders
            ],
            "warnings": p.warnings,
        },
        ensure_ascii=False,
    )

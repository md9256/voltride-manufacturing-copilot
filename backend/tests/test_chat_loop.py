"""The tool-use loop, with a scripted fake provider and a real (SQLite) store."""

import json

from app.ai.providers import LLMError, LLMProvider, TextDelta, ToolCall, TurnResult
from app.services import chat_store
from app.services.chat import MAX_TOOL_ROUNDS, history_of, run_chat_turn
from tests.fakes import FakeOdooClient

OWNER = "11111111-1111-1111-1111-111111111111"


class ScriptedProvider(LLMProvider):
    """Plays back one scripted turn per stream_turn call and records what it was sent."""

    name = "fake"
    model = "fake-1"

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests: list[dict] = []

    def user_message(self, text):
        return [{"role": "user", "content": text}]

    def tool_results(self, results):
        return [{"role": "tool", "id": c.id, "ok": o.ok, "content": o.content} for c, o in results]

    async def stream_turn(self, system, history, tools):
        self.requests.append({"system": system, "history": list(history), "tools": [t.name for t in tools]})
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        for chunk in turn.get("deltas", []):
            yield TextDelta(chunk)
        text = "".join(turn.get("deltas", []))
        calls = [ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(turn.get("calls", []))]
        native = [{"role": "assistant", "text": text, "calls": [c.id for c in calls], "opaque": "signature-xyz"}]
        yield TurnResult(native=native, text=text, tool_calls=calls, stop=turn.get("stop", "end"))


async def chat(db, provider, text="hi", odoo=None):
    conv = await chat_store.create_conversation(db, owner_id=OWNER, provider=provider.name, model=provider.model)
    conv = await chat_store.get_conversation(db, OWNER, conv.id)
    events = [
        e.as_dict()
        async for e in run_chat_turn(session=db, conv=conv, text=text, provider=provider, odoo=odoo or FakeOdooClient())
    ]
    return events, await chat_store.get_conversation(db, OWNER, conv.id)


def types(events):
    return [e["type"] for e in events]


async def test_text_only_answer(db):
    events, conv = await chat(db, ScriptedProvider([{"deltas": ["Hel", "lo"]}]))
    assert types(events) == ["text", "text", "done"]
    assert [m.role for m in conv.messages] == ["user", "assistant"]
    assert conv.title == "hi"


async def test_tool_round_then_answer(db):
    provider = ScriptedProvider(
        [
            {"calls": [("get_bom_shortages", {"product": "KIT", "quantity": 2, "count_incoming": False})]},
            {"deltas": ["You are short 1 CHIP."]},
        ]
    )
    events, conv = await chat(db, provider, "can we build 2 kits?")

    assert types(events) == ["tool_started", "tool_finished", "text", "done"]
    assert events[1]["ok"] is True
    assert [m.role for m in conv.messages] == ["user", "assistant", "tool", "assistant"]
    # The second request carried the tool result, whose content is the real planner output.
    tool_msg = provider.requests[1]["history"][-1]
    assert json.loads(tool_msg["content"])["short_components"][0]["code"] == "CHIP"


async def test_parallel_calls_answered_together_in_order(db):
    provider = ScriptedProvider(
        [
            {"calls": [("get_stock_levels", {"products": ["CHIP"]}), ("get_bom", {"product": "KIT"})]},
            {"deltas": ["done"]},
        ]
    )
    events, conv = await chat(db, provider)
    assert [e["id"] for e in events if e["type"] == "tool_finished"] == ["c0", "c1"]
    tool_step = conv.messages[2]
    assert [n["id"] for n in tool_step.native] == ["c0", "c1"]  # one step, both results


async def test_invalid_tool_call_is_reported_to_model_not_raised(db):
    provider = ScriptedProvider(
        [
            {"calls": [("get_bom_shortages", {"product": "KIT", "quantity": -5})]},
            {"deltas": ["Sorry, quantity must be positive."]},
        ]
    )
    events, conv = await chat(db, provider)
    finished = next(e for e in events if e["type"] == "tool_finished")
    assert finished["ok"] is False
    assert provider.requests[1]["history"][-1]["ok"] is False
    assert types(events)[-1] == "done"


async def test_native_history_is_replayed_verbatim(db):
    provider = ScriptedProvider([{"deltas": ["first"]}])
    _, conv = await chat(db, provider)
    provider.turns.append({"deltas": ["second"]})
    _ = [e async for e in run_chat_turn(session=db, conv=conv, text="again", provider=provider, odoo=FakeOdooClient())]

    replayed = provider.requests[1]["history"]
    assert replayed[0] == {"role": "user", "content": "hi"}
    assert replayed[1]["opaque"] == "signature-xyz"  # provider-specific data survived the database
    assert replayed[2] == {"role": "user", "content": "again"}
    assert history_of(await chat_store.get_conversation(db, OWNER, conv.id))[1] == replayed[1]


async def test_round_cap_stops_runaway_tool_use(db):
    looping = [{"calls": [("get_stock_levels", {})]}] * MAX_TOOL_ROUNDS
    events, conv = await chat(db, ScriptedProvider(looping))
    assert events[-1]["type"] == "error"
    assert "too many tool calls" in events[-1]["message"]
    assert sum(1 for m in conv.messages if m.role == "assistant") == MAX_TOOL_ROUNDS


async def test_provider_error_becomes_error_event_and_keeps_history(db):
    events, conv = await chat(db, ScriptedProvider([LLMError("rate limited, try later")]))
    assert events == [{"type": "error", "message": "rate limited, try later"}]
    assert [m.role for m in conv.messages] == ["user"]


async def test_refusal_and_truncation_notes(db):
    events, _ = await chat(db, ScriptedProvider([{"deltas": ["partial"], "stop": "refusal"}]))
    assert "declined" in events[-2]["delta"]
    events, _ = await chat(db, ScriptedProvider([{"deltas": ["long"], "stop": "max_tokens"}]))
    assert "cut off" in events[-2]["delta"]


async def test_system_prompt_has_currency_date_and_language_rule(db):
    provider = ScriptedProvider([{"deltas": ["ok"]}])
    await chat(db, provider)
    system = provider.requests[0]["system"]
    assert "Company currency: HKD" in system
    assert "Today's date:" in system
    assert "Simplified Chinese" in system


async def test_odoo_down_does_not_block_chat(db):
    odoo = FakeOdooClient()
    odoo.fail = True
    provider = ScriptedProvider([{"calls": [("get_stock_levels", {})]}, {"deltas": ["ERP is down"]}])
    events, _ = await chat(db, provider, odoo=odoo)
    assert next(e for e in events if e["type"] == "tool_finished")["ok"] is False
    assert types(events)[-1] == "done"

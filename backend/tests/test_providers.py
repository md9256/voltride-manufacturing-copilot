"""Provider adapters, driven by fake SDK clients that emit the SDKs' real types."""

from types import SimpleNamespace

import anthropic
import httpx2
import openai
import pytest
from anthropic.types.beta import BetaMessage
from openai.types.chat import ChatCompletionChunk

from app.ai.providers import LLMError, TextDelta, ToolCall, TurnResult
from app.ai.providers.anthropic import FALLBACK_BETA, AnthropicProvider
from app.ai.providers.openai_compat import OpenAICompatProvider
from app.ai.tools import TOOLS, ToolOutcome


async def collect(provider, history=None):
    items = [i async for i in provider.stream_turn("system prompt", history or [], TOOLS)]
    deltas = [i.text for i in items if isinstance(i, TextDelta)]
    [result] = [i for i in items if isinstance(i, TurnResult)]
    assert items[-1] is result  # the TurnResult always comes last
    return deltas, result


# --- OpenAI-compatible (Gemini) ---------------------------------------------


def chunk(delta: dict, finish: str | None = None) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "gemini",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    )


class FakeOpenAI:
    def __init__(self, chunks=None, error: Exception | None = None):
        self.chunks, self.error, self.calls = chunks or [], error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error

        async def stream():
            for c in self.chunks:
                yield c

        return stream()


def gemini(client) -> OpenAICompatProvider:
    return OpenAICompatProvider(name="gemini", model="gemini-test", api_key="k", base_url="http://x", client=client)


async def test_openai_text_stream():
    client = FakeOpenAI([chunk({"content": "Hel"}), chunk({"content": "lo"}), chunk({}, "stop")])
    deltas, result = await collect(gemini(client), [{"role": "user", "content": "hi"}])

    assert deltas == ["Hel", "lo"]
    assert (result.text, result.stop, result.tool_calls) == ("Hello", "end", [])
    assert result.native == [{"role": "assistant", "content": "Hello"}]
    sent = client.calls[0]
    assert sent["messages"][0] == {"role": "system", "content": "system prompt"}
    assert sent["stream"] is True
    assert {t["function"]["name"] for t in sent["tools"]} == {t.name for t in TOOLS}


async def test_openai_tool_call_fragments_and_gemini_signature_are_kept():
    signature = {"google": {"thought_signature": "SIG=="}}
    client = FakeOpenAI(
        [
            chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_bom", "arguments": '{"prod'},
                            "extra_content": signature,
                        }
                    ]
                }
            ),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'uct": "KIT"}'}}]}),
            # Gemini reports "stop" even though the turn ended in a tool call.
            chunk({}, "stop"),
        ]
    )
    _, result = await collect(gemini(client))

    assert result.stop == "tool_use"
    assert result.tool_calls == [ToolCall(id="call_1", name="get_bom", arguments={"product": "KIT"})]
    [call] = result.native[0]["tool_calls"]
    assert call["extra_content"] == signature  # replayed verbatim next turn
    assert call["function"] == {"name": "get_bom", "arguments": '{"product": "KIT"}'}


async def test_openai_unparseable_arguments_passed_through_for_validation():
    client = FakeOpenAI(
        [chunk({"tool_calls": [{"index": 0, "id": "c", "function": {"name": "get_bom", "arguments": "{oops"}}]})]
    )
    _, result = await collect(gemini(client))
    assert result.tool_calls[0].arguments == "{oops"  # the ToolRunner turns this into an error result


def test_openai_tool_results_one_message_per_call():
    msgs = gemini(FakeOpenAI()).tool_results(
        [
            (ToolCall("a", "x", {}), ToolOutcome(True, '{"v":1}', "ok")),
            (ToolCall("b", "y", {}), ToolOutcome(False, '{"error":"no"}', "no")),
        ]
    )
    assert msgs == [
        {"role": "tool", "tool_call_id": "a", "content": '{"v":1}'},
        {"role": "tool", "tool_call_id": "b", "content": '{"error":"no"}'},
    ]


@pytest.mark.parametrize(("status", "text"), [(429, "rate-limited"), (503, "overloaded"), (401, "credentials")])
async def test_openai_http_errors_become_user_safe_messages(status, text):
    response = httpx2.Response(status, request=httpx2.Request("POST", "http://x"))
    error = openai.APIStatusError("boom", response=response, body=None)
    with pytest.raises(LLMError, match=text):
        await collect(gemini(FakeOpenAI(error=error)))


# --- Anthropic ----------------------------------------------------------------


def message(content, stop="end_turn") -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


class FakeStream:
    def __init__(self, texts, final):
        self.texts, self.final = texts, final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def events():
            for t in self.texts:
                yield SimpleNamespace(type="text", text=t)

        return events()

    async def get_final_message(self):
        return self.final


class FakeAnthropic:
    def __init__(self, streams):
        self.streams, self.requests = list(streams), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append(kwargs)
        stream = self.streams.pop(0)
        if isinstance(stream, Exception):
            raise stream
        return stream


def claude(client, model="claude-opus-5-5", effort="") -> AnthropicProvider:
    return AnthropicProvider(model=model, api_key="k", effort=effort, client=client)


async def test_anthropic_keeps_every_block_including_thinking():
    final = message(
        [
            {"type": "thinking", "thinking": "", "signature": "SIG"},
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "tu_1", "name": "get_bom", "input": {"product": "KIT"}},
        ],
        stop="tool_use",
    )
    deltas, result = await collect(claude(FakeAnthropic([FakeStream(["Checking."], final)])))

    assert deltas == ["Checking."]
    assert result.stop == "tool_use"
    assert result.tool_calls == [ToolCall(id="tu_1", name="get_bom", arguments={"product": "KIT"})]
    blocks = result.native[0]["content"]
    assert blocks[0] == {"type": "thinking", "thinking": "", "signature": "SIG"}  # replayed verbatim


async def test_anthropic_request_shape():
    client = FakeAnthropic([FakeStream([], message([{"type": "text", "text": "ok"}]))])
    await collect(claude(client, effort="low"))
    req = client.requests[0]
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"] == {"effort": "low"}
    assert req["betas"] == [FALLBACK_BETA] and req["fallbacks"] == "default"
    assert all(t["eager_input_streaming"] for t in req["tools"])


async def test_anthropic_no_fallback_or_effort_for_other_models():
    client = FakeAnthropic([FakeStream([], message([{"type": "text", "text": "ok"}]))])
    await collect(claude(client, model="claude-haiku-4-5"))
    assert "fallbacks" not in client.requests[0]
    assert "output_config" not in client.requests[0]


async def test_anthropic_truncated_tool_input_is_never_run():
    final = message([{"type": "tool_use", "id": "t", "name": "get_bom", "input": {"prod": ""}}], stop="max_tokens")
    _, result = await collect(claude(FakeAnthropic([FakeStream([], final)])))
    assert (result.stop, result.tool_calls) == ("max_tokens", [])


async def test_anthropic_retries_unparseable_eager_input_then_succeeds():
    good = FakeStream(["ok"], message([{"type": "text", "text": "ok"}]))
    client = FakeAnthropic([ValueError("bad partial json"), good])
    deltas, result = await collect(claude(client))
    assert (deltas, result.text, len(client.requests)) == (["ok"], "ok", 2)


def test_anthropic_tool_results_single_user_message():
    [msg] = claude(FakeAnthropic([])).tool_results(
        [
            (ToolCall("a", "x", {}), ToolOutcome(True, "{}", "ok")),
            (ToolCall("b", "y", {}), ToolOutcome(False, '{"error":"e"}', "e")),
        ]
    )
    assert msg["role"] == "user"
    assert [(b["tool_use_id"], b["is_error"]) for b in msg["content"]] == [("a", False), ("b", True)]


async def test_anthropic_rate_limit_becomes_llm_error():
    response = httpx2.Response(429, request=httpx2.Request("POST", "http://x"))
    error = anthropic.RateLimitError("slow down", response=response, body=None)
    with pytest.raises(LLMError, match="rate-limited"):
        await collect(claude(FakeAnthropic([error])))

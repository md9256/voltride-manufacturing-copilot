"""Adapter for the Anthropic Messages API (Claude).

- History is replayed exactly as received: assistant messages keep every
  content block (including thinking blocks), as recent Claude models require.
- The system prompt is marked for prompt caching; it and the tool list are
  identical across requests, so repeat turns read them from cache.
- Server-side refusal fallback is enabled for models that support it: if the
  model declines, the API retries on a fallback model within the same call.
- Tool inputs stream eagerly (`eager_input_streaming`); the server then no
  longer validates them, which is fine because the ToolRunner validates every
  input with Pydantic before running anything.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

import anthropic
from anthropic import AsyncAnthropic

from app.ai.providers.base import LLMError, LLMProvider, TextDelta, ToolCall, TurnResult
from app.ai.tools import Tool, ToolOutcome

MAX_OUTPUT_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_STOP = {"end_turn": "end", "tool_use": "tool_use", "max_tokens": "max_tokens", "refusal": "refusal"}
JSON_PARSE_RETRIES = 2


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, *, model: str, api_key: str, effort: str = "", client: AsyncAnthropic | None = None):
        self.model = model
        self._effort = effort
        self._client = client or AsyncAnthropic(api_key=api_key, max_retries=3)

    def user_message(self, text: str) -> list[dict]:
        return [{"role": "user", "content": text}]

    def tool_results(self, results: list[tuple[ToolCall, ToolOutcome]]) -> list[dict]:
        # All results of one turn go back in a single user message.
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": outcome.content,
                        "is_error": not outcome.ok,
                    }
                    for call, outcome in results
                ],
            }
        ]

    def _request(self, system: str, history: list[dict], tools: list[Tool]) -> dict:
        request: dict = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": history,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.json_schema(),
                    "eager_input_streaming": True,
                }
                for t in tools
            ],
        }
        if self._effort:
            request["output_config"] = {"effort": self._effort}
        if self.model in FALLBACK_MODELS:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    async def stream_turn(
        self, system: str, history: list[dict], tools: list[Tool]
    ) -> AsyncIterator[TextDelta | TurnResult]:
        request = self._request(system, history, tools)
        for attempt in range(JSON_PARSE_RETRIES + 1):
            emitted = False
            try:
                async with self._client.beta.messages.stream(**request) as stream:
                    async for event in stream:
                        if event.type == "text":
                            emitted = True
                            yield TextDelta(event.text)
                    final = await stream.get_final_message()
                break
            except ValueError:
                # Eagerly streamed tool input the SDK could not parse at all.
                # Re-issue the turn, unless text already reached the user.
                if emitted or attempt == JSON_PARSE_RETRIES:
                    raise LLMError("The AI produced malformed tool arguments. Please try again.") from None
            except anthropic.RateLimitError as exc:
                raise LLMError("The AI service is rate-limited right now. Please try again shortly.") from exc
            except anthropic.APIStatusError as exc:
                raise LLMError(f"The AI service returned an error (HTTP {exc.status_code}).") from exc
            except anthropic.APIConnectionError as exc:
                raise LLMError("Could not reach the AI service. Please try again.") from exc

        content = [block.to_dict() for block in final.content]
        text = "".join(b["text"] for b in content if b.get("type") == "text")
        tool_calls = [
            ToolCall(id=b["id"], name=b["name"], arguments=b.get("input"))
            for b in content
            if b.get("type") == "tool_use"
        ]
        stop = _STOP.get(final.stop_reason or "", "end")
        if stop == "max_tokens" and tool_calls:
            # A truncated tool input parses as a valid-looking partial object; never run it.
            tool_calls = []
        yield TurnResult(
            native=[{"role": "assistant", "content": content}], text=text, tool_calls=tool_calls, stop=stop
        )

    async def extract_pdf(self, pdf: bytes, instruction: str, schema: dict) -> dict:
        # Native PDF document block + structured output (output_config.format),
        # which guarantees the first text block is JSON matching the schema.
        request: dict = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": base64.b64encode(pdf).decode(),
                            },
                        },
                        {"type": "text", "text": instruction},
                    ],
                }
            ],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if self._effort:
            request["output_config"]["effort"] = self._effort
        try:
            message = await self._client.messages.create(**request)
        except anthropic.RateLimitError as exc:
            raise LLMError("The AI service is rate-limited right now. Please try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"The AI service returned an error (HTTP {exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service. Please try again.") from exc
        if message.stop_reason == "refusal":
            raise LLMError("The model declined to read this document.")
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("The AI did not return valid JSON for this document.") from exc

    async def complete(self, system: str, prompt: str) -> str:
        request: dict = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._effort:
            request["output_config"] = {"effort": self._effort}
        try:
            message = await self._client.messages.create(**request)
        except anthropic.RateLimitError as exc:
            raise LLMError("The AI service is rate-limited right now. Please try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"The AI service returned an error (HTTP {exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service. Please try again.") from exc
        if message.stop_reason == "refusal":
            raise LLMError("The model declined to write this summary.")
        return "".join(b.text for b in message.content if b.type == "text")

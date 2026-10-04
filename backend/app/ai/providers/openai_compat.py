"""Adapter for OpenAI-compatible chat-completions APIs.

Used for Google Gemini (through Google's OpenAI-compatible endpoint, free
tier) and any other compatible host (Hugging Face router, Groq, OpenRouter).

Two Gemini behaviours, verified against the live API, shape this code:
- Gemini sends `finish_reason: "stop"` even when the reply contains tool
  calls, so tool use is detected from the tool calls themselves.
- Each Gemini tool call carries `extra_content.google.thought_signature`,
  which must be sent back unchanged with the assistant message or the next
  request fails with HTTP 400. Unknown fields on streamed tool-call deltas
  are therefore kept and replayed, not dropped.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI

from app.ai.providers.base import LLMError, LLMProvider, TextDelta, ToolCall, TurnResult
from app.ai.tools import Tool, ToolOutcome

MAX_OUTPUT_TOKENS = 8192
_STANDARD_TOOL_CALL_KEYS = {"index", "id", "type", "function"}


class OpenAICompatProvider(LLMProvider):
    def __init__(self, *, name: str, model: str, api_key: str, base_url: str, client: AsyncOpenAI | None = None):
        self.name = name
        self.model = model
        # The SDK retries 429/5xx/connection errors with backoff; free tiers
        # return 429 and 503 ("high demand") often enough that 3 is worth it.
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=3, timeout=90)

    def user_message(self, text: str) -> list[dict]:
        return [{"role": "user", "content": text}]

    def tool_results(self, results: list[tuple[ToolCall, ToolOutcome]]) -> list[dict]:
        return [{"role": "tool", "tool_call_id": call.id, "content": outcome.content} for call, outcome in results]

    @staticmethod
    def _tools(tools: list[Tool]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.json_schema()},
            }
            for t in tools
        ]

    async def stream_turn(
        self, system: str, history: list[dict], tools: list[Tool]
    ) -> AsyncIterator[TextDelta | TurnResult]:
        messages = [{"role": "system", "content": system}, *history]
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self._tools(tools),
                max_tokens=MAX_OUTPUT_TOKENS,
                stream=True,
            )
            text_parts: list[str] = []
            calls: dict[int, dict] = {}
            finish = None
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta.content:
                    text_parts.append(delta.content)
                    yield TextDelta(delta.content)
                for tc in delta.tool_calls or []:
                    _merge_tool_call_delta(calls.setdefault(tc.index or 0, {}), tc.to_dict())
                finish = choice.finish_reason or finish
        except openai.APIStatusError as exc:
            raise LLMError(_status_message(exc.status_code, str(exc))) from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service. Please try again.") from exc

        text = "".join(text_parts)
        native_calls = [calls[i] for i in sorted(calls)]
        assistant: dict = {"role": "assistant", "content": text or None}
        if native_calls:
            assistant["tool_calls"] = native_calls

        tool_calls = [
            ToolCall(id=c["id"], name=c["function"]["name"], arguments=_parse_arguments(c["function"]["arguments"]))
            for c in native_calls
        ]
        if tool_calls:
            stop = "tool_use"
        elif finish == "length":
            stop = "max_tokens"
        elif finish == "content_filter":
            stop = "refusal"
        else:
            stop = "end"
        yield TurnResult(native=[assistant], text=text, tool_calls=tool_calls, stop=stop)

    async def complete(self, system: str, prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except openai.APIStatusError as exc:
            raise LLMError(_status_message(exc.status_code, str(exc))) from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service. Please try again.") from exc
        text = response.choices[0].message.content if response.choices else None
        if not text:
            raise LLMError("The AI returned an empty answer.")
        return text

    async def extract_pdf(self, pdf: bytes, instruction: str, schema: dict) -> dict:
        # Gemini's OpenAI-compatible endpoint accepts a PDF as a data URL in an
        # image_url part (a `file` part is rejected with HTTP 400 - verified).
        data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode()
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {"type": "text", "text": instruction},
                        ],
                    }
                ],
                response_format={"type": "json_schema", "json_schema": {"name": "extraction", "schema": schema}},
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except openai.APIStatusError as exc:
            raise LLMError(_status_message(exc.status_code, str(exc))) from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service. Please try again.") from exc
        content = response.choices[0].message.content if response.choices else None
        try:
            return json.loads(content or "")
        except json.JSONDecodeError as exc:
            raise LLMError("The AI did not return valid JSON for this document.") from exc


def _merge_tool_call_delta(acc: dict, delta: dict) -> None:
    """Accumulate one streamed tool-call fragment into the full native call."""
    if delta.get("id"):
        acc["id"] = delta["id"]
    acc["type"] = "function"
    fn = acc.setdefault("function", {"name": "", "arguments": ""})
    fn["name"] += (delta.get("function") or {}).get("name") or ""
    fn["arguments"] += (delta.get("function") or {}).get("arguments") or ""
    # Provider-specific extras (Gemini's thought signature) are replayed as-is.
    for key, value in delta.items():
        if key not in _STANDARD_TOOL_CALL_KEYS and value is not None:
            acc[key] = value


def _parse_arguments(raw: str):
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return raw  # the ToolRunner reports non-object arguments back to the model


def _status_message(status: int, detail: str = "") -> str:
    if status == 429:
        # Google's free tier has per-minute and per-day quotas; its message says
        # which ("Please retry in 11h10m..."), so pass the wait time on.
        wait = re.search(r"retry in ((?:\d+h)?(?:\d+m)?[\d.]+s)", detail)
        if wait and "h" in wait.group(1):
            hours = wait.group(1).split("h")[0]
            return f"The AI service's free daily quota is used up; it resets in about {hours} h."
        return "The AI service is rate-limited right now (free tier). Please wait a minute and try again."
    if status in (500, 502, 503, 504):
        return "The AI service is overloaded or unavailable. Please try again shortly."
    if status in (401, 403):
        return "The AI service rejected the server's credentials. Check the API key configuration."
    return f"The AI service returned an error (HTTP {status})."

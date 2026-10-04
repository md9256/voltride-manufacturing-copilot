"""Provider-neutral interface for one streamed LLM turn.

The orchestrator (services/chat.py) owns the tool loop and talks only to this
interface. Each adapter translates to its wire format and back, and keeps
history in that provider's own message format ("native"), which is stored and
replayed verbatim: Anthropic thinking blocks and Gemini thought signatures
must come back unchanged on the next request or the API rejects it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai.tools import Tool, ToolOutcome

StopReason = Literal["end", "tool_use", "max_tokens", "refusal"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Any  # parsed JSON; validated by the ToolRunner, never trusted here


@dataclass
class TextDelta:
    text: str


@dataclass
class TurnResult:
    native: list[dict]  # assistant message(s) exactly as the provider returned them
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop: StopReason = "end"


class LLMError(Exception):
    """A provider failure, with a message safe to show the user."""


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def user_message(self, text: str) -> list[dict]:
        """Native message(s) for a user's text."""

    @abstractmethod
    def tool_results(self, results: list[tuple[ToolCall, ToolOutcome]]) -> list[dict]:
        """Native message(s) answering every tool call of the previous turn."""

    @abstractmethod
    def stream_turn(self, system: str, history: list[dict], tools: list[Tool]) -> AsyncIterator[TextDelta | TurnResult]:
        """Stream one assistant turn: TextDelta items, then exactly one TurnResult."""

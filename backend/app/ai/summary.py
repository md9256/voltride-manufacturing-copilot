"""AI daily production summary: code computes the facts, the model narrates.

The model receives a DailyFacts JSON document and nothing else, and is told
to quote figures exactly as given. Afterwards every number in its text is
checked against the facts; any figure that cannot be traced is reported to
the user instead of being trusted.
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal

from app.ai.providers import LLMProvider
from app.schemas.shopfloor import DailyFacts, SummaryLanguage

LANGUAGE_NAMES = {
    "en": "English",
    "zh-Hans": "Simplified Chinese (简体中文)",
    "zh-Hant": "Traditional Chinese (繁體中文)",
}

SYSTEM = """\
You write the daily production briefing for the production supervisor at VoltRide Systems, \
an e-bike drive-system manufacturer.

Rules:
- Use only the facts in the JSON you are given. Do not add knowledge, assumptions or advice \
that the facts do not support.
- Quote numbers exactly as they appear in the facts, with their units. Do not add, subtract, \
convert units or compute percentages yourself: every figure you need is already provided.
- Keep order references (WH/MO/00004), product codes and work-center names unchanged.
- If a section has nothing to report, leave it out.
- Write in {language}, including the section headings below (translate them).

Format (Markdown, at most about 180 words):
1. A one-sentence headline.
2. **Done**: finished work and how it compared with plan.
3. **Running and late**: orders in progress, and work that is late.
4. **Today's schedule**: what is planned, and the work that is scheduled without its materials.
5. **Watch**: up to three bullets on the most important risks (materials, low stock, load).
"""


def build_prompt(facts: DailyFacts) -> str:
    return (
        f"Briefing for {facts.day.isoformat()} (times are {facts.timezone}; data as of {facts.as_of}).\n\n"
        "Facts:\n```json\n" + facts.model_dump_json(indent=1) + "\n```"
    )


async def write_summary(provider: LLMProvider, facts: DailyFacts, language: SummaryLanguage) -> str:
    return await provider.complete(SYSTEM.format(language=LANGUAGE_NAMES[language]), build_prompt(facts))


# --- grounding check ----------------------------------------------------------

# A number not continuing another one. Digits after letters count ("x3",
# "CHP-MCU x7"), so the same pattern applies to the facts and to the text.
_NUMBER = re.compile(r"(?<![\d.])\d[\d,]*(?:\.\d+)?")


def _numbers_in(text: str) -> list[str]:
    return _NUMBER.findall(text)


def fact_numbers(facts: DailyFacts) -> set[float]:
    """Every number that appears anywhere in the facts, including inside
    strings such as references (WH/MO/00004 -> 4) and times (08:48 -> 8, 48)."""
    values: set[float] = set()

    def walk(node) -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, int | float):
            values.add(float(node))
        elif isinstance(node, str):
            for raw in _numbers_in(node):
                values.add(float(raw.replace(",", "")))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(json.loads(facts.model_dump_json()))
    return values


def _half_up(value: float, places: int) -> float:
    """Rounding as people (and models) do it: 112.5 -> 113. Python's round()
    rounds halves to even (112.5 -> 112) and would flag "113 min" as invented."""
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def untraceable_numbers(text: str, facts: DailyFacts) -> list[str]:
    """Figures in the summary that do not match any number in the facts.

    A figure matches if it equals a fact value, or that value rounded to 0
    or 1 decimal places (models round "37.5 min" to "38 min"). Counts of
    list items (e.g. "3 orders" when three orders are listed) also match.
    """
    known = fact_numbers(facts)
    list_lengths = {float(len(v)) for v in json.loads(facts.model_dump_json()).values() if isinstance(v, list)}
    allowed = known | {_half_up(v, 0) for v in known} | {_half_up(v, 1) for v in known} | list_lengths
    unknown = []
    for raw in _numbers_in(text):
        value = float(raw.replace(",", ""))
        if value not in allowed and raw not in unknown:
            unknown.append(raw)
    return unknown

from datetime import date

from app.ai.summary import SYSTEM, build_prompt, fact_numbers, untraceable_numbers, write_summary
from app.schemas.shopfloor import DailyFacts, FinishedFact
from tests.test_chat_loop import ScriptedProvider


def facts(**overrides) -> DailyFacts:
    values = dict(
        day=date(2026, 10, 5),
        timezone="Asia/Hong_Kong",
        as_of="2026-10-05 12:00",
        finished_count=2,
        finished_planned_minutes=100.0,
        finished_actual_minutes=112.5,
        finished_variance_pct=12.5,
        finished=[
            FinishedFact(
                production="WH/MO/00007",
                product="SA-CTL-STD",
                operation="Solder",
                workcenter="PCB Line",
                finished_at="2026-10-05 09:15",
                planned_minutes=37.5,
                actual_minutes=45.0,
                variance_pct=20.0,
            )
        ],
        running_orders=[],
        scheduled=[],
        late=[],
        material_readiness=[],
        scheduled_without_materials=[{"production": "WH/MO/00005", "short": ["SA-DRV-HP x3"]}],
        workcenter_load=[],
        orders_by_state={"done": 14, "confirmed": 2},
        low_stock=[{"code": "LCD-35", "on_hand": 0, "reorder_min": 15}],
    )
    values.update(overrides)
    return DailyFacts(**values)


def test_numbers_inside_strings_count_as_facts():
    known = fact_numbers(facts())
    assert {7.0, 5.0, 9.0, 15.0, 3.0, 2026.0, 112.5, 14.0} <= known  # MO refs, times, "x3", codes


def test_traceable_summary_passes():
    text = (
        "**Done**: 2 work orders finished, 112.5 min against 100 min planned (+12.5%). "
        "WH/MO/00007 solder took 45 min vs 37.5 planned (+20%), finished 09:15. "
        "WH/MO/00005 is scheduled without SA-DRV-HP (short 3). LCD-35: 0 on hand, reorder at 15."
    )
    assert untraceable_numbers(text, facts()) == []


def test_rounded_figures_are_accepted():
    assert untraceable_numbers("Solder took about 38 minutes; total 113 min.", facts()) == []


def test_invented_figures_are_reported():
    text = "Output rose 30% and the line saved 4.5 hours; 2 orders done."
    assert untraceable_numbers(text, facts()) == ["30", "4.5"]


def test_chinese_text_is_checked_too():
    assert untraceable_numbers("今日完成 2 张工单，超出计划 12.5%，另有 99 件待处理。", facts()) == ["99"]


def test_prompt_contains_facts_and_language_rule():
    prompt = build_prompt(facts())
    assert '"WH/MO/00007"' in prompt and "2026-10-05" in prompt
    assert "Quote numbers exactly" in SYSTEM


async def test_write_summary_uses_requested_language():
    provider = ScriptedProvider([])
    provider.completion = "简报"
    assert await write_summary(provider, facts(), "zh-Hans") == "简报"
    system, prompt = provider.completions[0]
    assert "Simplified Chinese" in system and "112.5" in prompt

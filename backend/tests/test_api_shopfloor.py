from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import main
from app.ai.providers import LLMError
from app.api import deps
from app.main import app
from app.odoo import get_odoo_client
from tests.conftest import SqliteDb
from tests.fakes import FakeOdooClient
from tests.test_chat_loop import ScriptedProvider
from tests.test_shopfloor import wo

A = {"X-Client-Id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}


@pytest.fixture
def env(monkeypatch):
    database = SqliteDb()
    odoo = FakeOdooClient()
    now = datetime.now(UTC)
    odoo.work_orders = [
        wo(1, "done", now - timedelta(days=2, hours=2), now - timedelta(days=2, hours=1), planned=60, actual=75),
        wo(2, "ready", now + timedelta(hours=2), now + timedelta(hours=3), mo=2),
        wo(3, "ready", mo=3, op="Pack"),
    ]
    provider = ScriptedProvider([])
    provider.completion = "All good: 1 work order finished."
    monkeypatch.setattr(main, "upgrade_to_head", lambda: None)
    app.dependency_overrides[deps.get_provider] = lambda: provider
    app.dependency_overrides[deps.get_db_sessionmaker] = database.sessionmaker
    app.dependency_overrides[get_odoo_client] = lambda: odoo
    with TestClient(app) as client:
        yield client, odoo, provider
    app.dependency_overrides.clear()


def test_timeline_endpoint(env):
    client, *_ = env
    body = client.get("/api/shopfloor/timeline?days_back=14&days_ahead=7").json()
    statuses = sorted(b["status"] for r in body["rows"] for b in r["bars"])
    assert statuses == ["done", "planned"]
    assert [u["operation"] for u in body["unscheduled"]] == ["Pack"]
    assert client.get("/api/shopfloor/timeline?days_ahead=0").status_code == 422
    narrow = client.get("/api/shopfloor/timeline?days_back=0&days_ahead=1").json()
    assert [b["status"] for r in narrow["rows"] for b in r["bars"]] == ["planned"]  # done one was 2 days ago
    start = datetime.fromisoformat(narrow["start"]).astimezone(ZoneInfo("Asia/Hong_Kong"))
    assert (start.hour, start.minute) == (0, 0)  # local midnight


def test_stats_endpoint(env):
    client, *_ = env
    body = client.get("/api/shopfloor/stats").json()
    assert body["overall"]["variance_pct"] == 25.0
    assert len([ld for ld in body["load"] if ld["workcenter"] == "Assembly"]) == 7  # next 7 days


def test_summary_is_generated_then_served_from_cache(env):
    client, _, provider = env
    first = client.post("/api/shopfloor/summary", json={"language": "en"}, headers=A).json()
    assert (first["text"], first["cached"], first["unverified_numbers"]) == (
        "All good: 1 work order finished.",
        False,
        [],
    )
    second = client.post("/api/shopfloor/summary", json={"language": "en"}, headers=A).json()
    assert second["cached"] is True
    assert len(provider.completions) == 1  # no second LLM call for the same facts
    regenerated = client.post("/api/shopfloor/summary", json={"language": "en", "regenerate": True}, headers=A).json()
    assert regenerated["cached"] is False and len(provider.completions) == 2


def test_summary_cache_is_per_language_and_per_facts(env):
    client, odoo, provider = env
    client.post("/api/shopfloor/summary", json={"language": "en"}, headers=A)
    client.post("/api/shopfloor/summary", json={"language": "zh-Hant"}, headers=A)
    assert len(provider.completions) == 2
    odoo.work_orders = odoo.work_orders[:1]  # the data changed
    client.post("/api/shopfloor/summary", json={"language": "en"}, headers=A)
    assert len(provider.completions) == 3


def test_summary_flags_untraceable_numbers_and_is_audited(env):
    client, _, provider = env
    provider.completion = "Throughput up 42% this week."
    body = client.post("/api/shopfloor/summary", json={"language": "en"}, headers=A).json()
    assert body["unverified_numbers"] == ["42"]
    [entry] = client.get("/api/audit?kind=summary", headers=A).json()
    assert entry["result"]["unverified_numbers"] == ["42"]


def test_summary_llm_failure_is_502(env):
    client, _, provider = env
    provider.completion = LLMError("The AI service's free daily quota is used up; it resets in about 11 h.")
    resp = client.post("/api/shopfloor/summary", json={"language": "en"}, headers=A)
    assert resp.status_code == 502 and "quota" in resp.json()["detail"]

import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import chat as chat_api
from app.main import app
from app.odoo import get_odoo_client
from tests.conftest import SqliteDb
from tests.fakes import FakeOdooClient
from tests.test_chat_loop import ScriptedProvider

CLIENT_A = {"X-Client-Id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
CLIENT_B = {"X-Client-Id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}


@pytest.fixture
def provider():
    return ScriptedProvider([])


@pytest.fixture
def api(provider, monkeypatch):
    database = SqliteDb()
    monkeypatch.setattr(main, "upgrade_to_head", lambda: None)  # never touch the real database
    app.dependency_overrides[chat_api.get_provider] = lambda: provider
    app.dependency_overrides[chat_api.get_db_sessionmaker] = database.sessionmaker
    app.dependency_overrides[get_odoo_client] = FakeOdooClient
    # One TestClient context = one event loop for every request, which the
    # single shared SQLite connection needs.
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def sse_events(response) -> list[dict]:
    return [json.loads(line[len("data: ") :]) for line in response.text.splitlines() if line.startswith("data: ")]


def new_conversation(api, headers=CLIENT_A) -> str:
    resp = api.post("/api/chat/conversations", headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


def test_full_exchange_over_sse(api, provider):
    conv_id = new_conversation(api)
    provider.turns += [{"calls": [("get_stock_levels", {"products": ["CHIP"]})]}, {"deltas": ["3 free."]}]

    resp = api.post(f"/api/chat/conversations/{conv_id}/messages", json={"text": "chip stock?"}, headers=CLIENT_A)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert [e["type"] for e in sse_events(resp)] == ["tool_started", "tool_finished", "text", "done"]

    detail = api.get(f"/api/chat/conversations/{conv_id}", headers=CLIENT_A).json()
    assert detail["title"] == "chip stock?"
    assert detail["can_continue"] is False  # the fake provider is not the configured one
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert detail["messages"][1]["display"]["tool_calls"][0]["name"] == "get_stock_levels"
    assert "native" not in detail["messages"][0]  # provider formats never reach the browser


def test_conversations_are_scoped_to_client_id(api):
    conv_id = new_conversation(api, CLIENT_A)
    assert [c["id"] for c in api.get("/api/chat/conversations", headers=CLIENT_A).json()] == [conv_id]
    assert api.get("/api/chat/conversations", headers=CLIENT_B).json() == []
    assert api.get(f"/api/chat/conversations/{conv_id}", headers=CLIENT_B).status_code == 404
    send = api.post(f"/api/chat/conversations/{conv_id}/messages", json={"text": "hi"}, headers=CLIENT_B)
    assert send.status_code == 404


def test_client_id_must_be_a_uuid(api):
    assert api.get("/api/chat/conversations", headers={"X-Client-Id": "me"}).status_code == 400
    assert api.get("/api/chat/conversations").status_code == 422


@pytest.mark.parametrize("text", ["", "x" * 4001])
def test_message_length_is_validated(api, text):
    conv_id = new_conversation(api)
    assert (
        api.post(f"/api/chat/conversations/{conv_id}/messages", json={"text": text}, headers=CLIENT_A).status_code
        == 422
    )


def test_conversation_from_another_provider_cannot_continue(api, provider):
    conv_id = new_conversation(api)
    provider.name = "other"
    resp = api.post(f"/api/chat/conversations/{conv_id}/messages", json={"text": "hi"}, headers=CLIENT_A)
    assert resp.status_code == 409


def test_delete_conversation(api):
    conv_id = new_conversation(api)
    assert api.delete(f"/api/chat/conversations/{conv_id}", headers=CLIENT_B).status_code == 404
    assert api.delete(f"/api/chat/conversations/{conv_id}", headers=CLIENT_A).status_code == 204
    assert api.get(f"/api/chat/conversations/{conv_id}", headers=CLIENT_A).status_code == 404


def test_unconfigured_assistant_returns_503(api, monkeypatch):
    def unavailable():
        raise chat_api.HTTPException(503, "AI assistant is not configured: GEMINI_API_KEY is not set")

    app.dependency_overrides[chat_api.get_provider] = unavailable
    resp = api.post("/api/chat/conversations", headers=CLIENT_A)
    assert resp.status_code == 503
    assert "GEMINI_API_KEY" in resp.json()["detail"]

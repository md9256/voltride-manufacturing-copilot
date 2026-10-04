import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import deps as chat_api
from app.main import app
from app.odoo import get_odoo_client
from tests.conftest import SqliteDb
from tests.fakes import FakeOdooClient
from tests.test_chat_loop import ScriptedProvider

CLIENT_A = {"X-Client-Id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
CLIENT_B = {"X-Client-Id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}


@pytest.fixture
def provider():
    fake = ScriptedProvider([])
    # Look like the configured provider and an allowed model, as a real one would.
    fake.name, fake.model = "gemini", "gemini-3.5-flash"
    return fake


@pytest.fixture
def api(provider, monkeypatch):
    database = SqliteDb()
    monkeypatch.setattr(main, "upgrade_to_head", lambda: None)  # never touch the real database
    app.dependency_overrides[chat_api.get_provider_factory] = lambda: lambda model: provider
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
    assert detail["can_continue"] is True
    assert detail["model"] == "gemini-3.5-flash"
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

    app.dependency_overrides[chat_api.get_provider_factory] = lambda: lambda model: unavailable()
    resp = api.post("/api/chat/conversations", headers=CLIENT_A)
    assert resp.status_code == 503
    assert "GEMINI_API_KEY" in resp.json()["detail"]


def test_status_lists_pickable_models(api):
    body = api.get("/api/chat/status").json()
    assert [m["id"] for m in body["models"]] == ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert body["models"][2]["label"] == "Gemini 3.5 Flash Lite"


def test_unknown_model_header_is_rejected(api):
    app.dependency_overrides.pop(chat_api.get_provider_factory)  # real allowlist check
    resp = api.post("/api/chat/conversations", headers={**CLIENT_A, "X-LLM-Model": "gpt-9-ultra"})
    assert resp.status_code == 400
    assert "not available" in resp.json()["detail"]


def test_message_uses_the_conversations_model_not_the_picker(api, provider):
    asked_for = []

    def factory(model):
        asked_for.append(model)
        return provider

    app.dependency_overrides[chat_api.get_provider_factory] = lambda: factory
    conv_id = new_conversation(api)  # created with the default model
    provider.turns.append({"deltas": ["ok"]})
    picker = {**CLIENT_A, "X-LLM-Model": "gemini-3.8-flash"}
    api.post(f"/api/chat/conversations/{conv_id}/messages", json={"text": "hi"}, headers=picker)
    assert asked_for[-1] == "gemini-3.5-flash"  # the conversation's model, not the newly picked one

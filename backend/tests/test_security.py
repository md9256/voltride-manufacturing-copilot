"""Demo password gate, access tokens and rate limits."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.api import deps
from app.config import get_settings
from app.main import app
from app.odoo import get_odoo_client
from app.security import Limit, RateLimiter, ai_limiter, issue_token, token_valid
from tests.conftest import SqliteDb
from tests.fakes import FakeOdooClient
from tests.test_chat_loop import ScriptedProvider

CLIENT = {"X-Client-Id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_password", "test-password")
    monkeypatch.setattr(main, "upgrade_to_head", lambda: None)
    database = SqliteDb()
    provider = ScriptedProvider([])
    provider.name, provider.model = "gemini", "gemini-3.5-flash"  # an allowed model
    app.dependency_overrides[deps.get_provider_factory] = lambda: lambda model: provider
    app.dependency_overrides[deps.get_db_sessionmaker] = database.sessionmaker
    app.dependency_overrides[get_odoo_client] = FakeOdooClient
    with TestClient(app) as client:
        yield client, provider
    app.dependency_overrides.clear()


def login(client, password="test-password"):
    return client.post("/api/auth/login", json={"password": password})


def bearer(client) -> dict:
    return {**CLIENT, "Authorization": f"Bearer {login(client).json()['token']}"}


# --- tokens ---------------------------------------------------------------------


def test_token_round_trip_and_expiry():
    token, expires = issue_token(now=1_000)
    assert token_valid(token, now=1_001)
    assert not token_valid(token, now=expires + 1)


def test_tampered_or_foreign_token_is_rejected(monkeypatch):
    token, _ = issue_token()
    payload, signature = token.split(".")
    assert not token_valid(f"{payload}x.{signature}")
    assert not token_valid("garbage")
    monkeypatch.setattr(get_settings(), "auth_secret", "another-secret")
    assert not token_valid(token)  # rotating the secret revokes every token


# --- gate -----------------------------------------------------------------------


def test_status_reports_gate(api):
    client, _ = api
    assert client.get("/api/auth/status").json() == {"required": True}


def test_wrong_password_is_refused(api):
    client, _ = api
    assert login(client, "nope").status_code == 401
    assert login(client).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/chat/conversations"),
        ("post", "/api/chat/conversations"),
        ("post", "/api/chat/conversations/x/messages"),
        ("get", "/api/actions/x"),
        ("post", "/api/actions/x/confirm"),
        ("post", "/api/intake/quotes"),
        ("post", "/api/shopfloor/summary"),
        ("get", "/api/audit"),
    ],
)
def test_ai_and_write_endpoints_need_a_token(api, method, path):
    client, _ = api
    resp = getattr(client, method)(path, headers=CLIENT)
    assert resp.status_code == 401
    assert "demo password" in resp.json()["detail"]


def test_read_only_endpoints_stay_open(api):
    client, _ = api
    for path in (
        "/api/health",
        "/api/dashboard/summary",
        "/api/products",
        "/api/shopfloor/timeline",
        "/api/chat/status",
    ):
        assert client.get(path).status_code == 200, path


def test_valid_token_opens_the_gate(api):
    client, _ = api
    headers = bearer(client)
    assert client.post("/api/chat/conversations", headers=headers).status_code == 201
    assert client.get("/api/audit", headers=headers).status_code == 200


def test_bad_token_is_refused(api):
    client, _ = api
    headers = {**CLIENT, "Authorization": "Bearer abc.def"}
    assert client.get("/api/chat/conversations", headers=headers).status_code == 401


def test_password_guessing_is_rate_limited(api):
    client, _ = api
    codes = [login(client, f"guess{i}").status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


# --- rate limits ------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_per_ip_limit_and_window_slides():
    clock = Clock()
    limiter = RateLimiter([Limit(2, 60, "ip", "minute")], clock=clock)
    limiter.check("1.1.1.1")
    limiter.check("1.1.1.1")
    with pytest.raises(HTTPException) as exc:
        limiter.check("1.1.1.1")
    assert exc.value.status_code == 429 and exc.value.headers["Retry-After"] == "61"
    limiter.check("2.2.2.2")  # another address has its own budget
    clock.t = 61
    limiter.check("1.1.1.1")  # window moved on


def test_global_cap_applies_across_addresses():
    limiter = RateLimiter(
        [Limit(100, 60, "ip", "minute"), Limit(3, 86_400, "global", "day for everyone")], clock=Clock()
    )
    for ip in ("a", "b", "c"):
        limiter.check(ip)
    with pytest.raises(HTTPException, match="on this demo"):
        limiter.check("d")


def test_rejected_requests_do_not_use_up_quota():
    limiter = RateLimiter([Limit(1, 60, "ip", "minute"), Limit(1, 60, "global", "minute")], clock=Clock())
    limiter.check("a")
    for _ in range(5):
        with pytest.raises(HTTPException):
            limiter.check("b")  # blocked by the global limit; must not record a hit for "b"
    assert len(limiter._hits[("minute", "b")]) == 0


def test_chat_messages_are_rate_limited(api, monkeypatch):
    client, provider = api
    monkeypatch.setattr(ai_limiter, "limits", [Limit(2, 60, "ip", "minute")])
    headers = bearer(client)
    conv = client.post("/api/chat/conversations", headers=headers).json()["id"]
    provider.turns += [{"deltas": ["ok"]}] * 3
    codes = [
        client.post(f"/api/chat/conversations/{conv}/messages", json={"text": "hi"}, headers=headers).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_security_headers_on_api_responses(api):
    client, _ = api
    headers = client.get("/api/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"

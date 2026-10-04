import json

import httpx
import pytest

from app.odoo.rpc import OdooAuthError, OdooError, OdooRpc


def make_rpc(handler, **kwargs) -> OdooRpc:
    return OdooRpc(
        "https://odoo.test", "db1", "secret-key", backoff_s=0, transport=httpx.MockTransport(handler), **kwargs
    )


def counting(response_factory):
    """Wrap a handler so tests can assert how many HTTP attempts were made."""
    calls = []

    def handler(request):
        calls.append(request)
        return response_factory(request)

    return handler, calls


def test_call_sends_json2_request():
    handler, calls = counting(lambda r: httpx.Response(200, json=[{"id": 7, "name": "x"}]))

    rows = make_rpc(handler).call("res.partner", "read", ids=[7], fields=["name"])

    assert rows == [{"id": 7, "name": "x"}]
    [request] = calls
    assert request.url.path == "/json/2/res.partner/read"
    assert request.headers["Authorization"] == "bearer secret-key"
    assert request.headers["X-Odoo-Database"] == "db1"
    assert json.loads(request.content) == {"ids": [7], "fields": ["name"]}


def test_401_raises_auth_error_without_traceback_or_retry():
    handler, calls = counting(
        lambda r: httpx.Response(401, json={"name": "Unauthorized", "message": "Invalid apikey", "debug": "Traceback"})
    )
    with pytest.raises(OdooAuthError) as exc:
        make_rpc(handler).call("res.users", "context_get")
    assert "Invalid apikey" in str(exc.value)
    assert "Traceback" not in str(exc.value)
    assert len(calls) == 1


def test_503_is_retried_for_reads():
    responses = iter([httpx.Response(503), httpx.Response(200, json=5)])
    assert make_rpc(lambda r: next(responses)).call("sale.order", "search_count", domain=[]) == 5


def test_503_is_not_retried_for_writes():
    # The create may have committed before the gateway failed; retrying could duplicate it.
    handler, calls = counting(lambda r: httpx.Response(503))
    with pytest.raises(OdooError):
        make_rpc(handler).call("res.partner", "create", vals_list=[{"name": "x"}])
    assert len(calls) == 1


def test_timeout_is_not_retried_for_writes():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    handler, calls = counting(timeout)
    with pytest.raises(OdooError, match="timed out"):
        make_rpc(handler).create("res.partner", {"name": "x"})
    assert len(calls) == 1


def test_connect_error_is_retried_even_for_writes():
    # A refused connection means the request never reached Odoo.
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=[42])

    assert make_rpc(handler).create("res.partner", {"name": "x"}) == 42


def test_retries_are_bounded():
    handler, calls = counting(lambda r: httpx.Response(502))
    with pytest.raises(OdooError, match="HTTP 502"):
        make_rpc(handler, max_retries=2).call("res.partner", "search_read", domain=[])
    assert len(calls) == 3


def test_429_is_retried_for_writes():
    responses = iter([httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json=[9])])
    assert make_rpc(lambda r: next(responses)).create("res.partner", {"name": "x"}) == 9


def test_persistent_429_gives_clear_error():
    rpc = make_rpc(lambda r: httpx.Response(429, headers={"Retry-After": "0"}), max_rate_limit_retries=2)
    with pytest.raises(OdooError, match="rate limited"):
        rpc.call("res.partner", "search_read", domain=[])

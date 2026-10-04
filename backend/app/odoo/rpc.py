"""Low-level transport for Odoo's JSON-2 external API.

JSON-2 (Odoo 19+) is `POST /json/2/<model>/<method>` with the API key as a bearer
token and keyword arguments as the JSON body. Each call runs in its own database
transaction. We use it rather than XML-RPC because XML-RPC/JSON-RPC are
deprecated and scheduled for removal.

Retry policy - the non-obvious part:
- A connection error means the request never reached Odoo, so any call is safe
  to retry.
- A timeout or 502/503/504 is ambiguous: Odoo may have committed the call. We
  only retry those for read-only methods, otherwise a retried `create` could
  silently create a duplicate record.
- 429 (Odoo Online rate limiting) means the request was rejected before it
  ran, so it is retried for any method, waiting for Retry-After if given.
- Other 4xx responses (bad key, access error, validation error) are never retried.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

READ_METHODS = frozenset(
    {"search", "search_read", "search_count", "read", "read_group", "fields_get", "context_get", "has_group"}
)
RETRYABLE_STATUS = frozenset({502, 503, 504})


class OdooError(Exception):
    """An Odoo call failed. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, *, status: int | None = None, model: str = "", method: str = "") -> None:
        self.status = status
        self.model = model
        self.method = method
        where = f"{model}.{method}: " if model else ""
        super().__init__(f"{where}{message}")


class OdooAuthError(OdooError):
    """The API key, login or database is wrong (HTTP 401)."""


class OdooRpc:
    def __init__(
        self,
        url: str,
        db: str,
        api_key: str,
        *,
        timeout_s: float = 15.0,
        max_retries: int = 2,
        max_rate_limit_retries: int = 6,
        backoff_s: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._max_rate_limit_retries = max_rate_limit_retries
        self._backoff_s = backoff_s
        self._client = httpx.Client(
            base_url=url.rstrip("/"),
            timeout=timeout_s,
            transport=transport,
            headers={
                "Authorization": f"bearer {api_key}",
                "X-Odoo-Database": db,
                "User-Agent": "voltride-copilot/0.1",
            },
        )

    def close(self) -> None:
        self._client.close()

    def call(self, model: str, method: str, *, ids: list[int] | None = None, **kwargs: Any) -> Any:
        body = dict(kwargs)
        if ids is not None:
            body["ids"] = ids
        is_read = method in READ_METHODS

        attempt = 0
        rate_limited = 0
        while True:
            try:
                resp = self._client.post(f"/json/2/{model}/{method}", json=body)
            except httpx.ConnectError as exc:
                error = OdooError(f"cannot connect to Odoo: {exc}", model=model, method=method)
                retryable = True
            except httpx.TimeoutException as exc:
                error = OdooError(f"timed out: {exc}", model=model, method=method)
                retryable = is_read
            except httpx.HTTPError as exc:
                raise OdooError(f"network error: {exc}", model=model, method=method) from exc
            else:
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429 and rate_limited < self._max_rate_limit_retries:
                    time.sleep(_retry_after_s(resp, default=self._backoff_s * 2 ** (rate_limited + 2)))
                    rate_limited += 1
                    continue
                error = _error_from_response(resp, model, method)
                retryable = is_read and resp.status_code in RETRYABLE_STATUS

            if not retryable or attempt >= self._max_retries:
                raise error
            time.sleep(self._backoff_s * 2**attempt)
            attempt += 1

    def server_version(self) -> str:
        """Server version from the unauthenticated /web/version endpoint."""
        try:
            resp = self._client.get("/web/version")
            resp.raise_for_status()
            return resp.json()["version"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise OdooError(f"cannot read server version: {exc}") from exc

    # Thin conveniences over call(); they keep calling code readable.

    def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        *,
        order: str | None = None,
        limit: int | None = None,
        context: dict | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {"domain": domain or [], "fields": fields or ["id"]}
        if order:
            kwargs["order"] = order
        if limit:
            kwargs["limit"] = limit
        if context:
            kwargs["context"] = context
        return self.call(model, "search_read", **kwargs)

    def search_ids(self, model: str, domain: list, *, limit: int | None = None) -> list[int]:
        kwargs: dict[str, Any] = {"domain": domain}
        if limit:
            kwargs["limit"] = limit
        return self.call(model, "search", **kwargs)

    def create(self, model: str, vals: dict, *, context: dict | None = None) -> int:
        kwargs: dict[str, Any] = {"vals_list": [vals]}
        if context:
            kwargs["context"] = context
        return self.call(model, "create", **kwargs)[0]

    def write(self, model: str, ids: list[int], vals: dict, *, context: dict | None = None) -> None:
        kwargs: dict[str, Any] = {"vals": vals}
        if context:
            kwargs["context"] = context
        self.call(model, "write", ids=ids, **kwargs)


def _retry_after_s(resp: httpx.Response, *, default: float) -> float:
    try:
        return min(float(resp.headers["Retry-After"]), 60.0)
    except (KeyError, ValueError):
        return min(default, 60.0)


def _error_from_response(resp: httpx.Response, model: str, method: str) -> OdooError:
    # Odoo's JSON-2 errors look like {"name": "...", "message": "...", "debug": "<traceback>"}.
    # We surface the message and drop the server traceback.
    try:
        payload = resp.json()
        message = payload.get("message") or payload.get("name") or resp.text[:300]
    except ValueError:
        message = resp.text[:300] or resp.reason_phrase
    if resp.status_code == 429:
        message = "rate limited by Odoo (too many requests)"
    cls = OdooAuthError if resp.status_code == 401 else OdooError
    return cls(f"HTTP {resp.status_code}: {message}", status=resp.status_code, model=model, method=method)

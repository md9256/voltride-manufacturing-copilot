"""Phase 0 connection check for the VoltRide Odoo database.

Run from the repo root:  python backend/scripts/check_odoo.py

Checks, in order: server reachable + version, authentication (and which
external API protocol works), required apps installed, read access to the key
models, and write access (create + delete a throwaway contact). Prints a
PASS/FAIL table and exits non-zero if anything failed.

Protocol choice: Odoo 19 introduced the JSON-2 API (POST /json/2/<model>/<method>,
API key as a bearer token) and deprecated XML-RPC/JSON-RPC, which are scheduled
for removal. We try JSON-2 first and fall back to XML-RPC so the report tells us
which one the Phase 1 client should be built on.

This script is deliberately standalone (no import from backend/app): it is a
diagnostic that must work before any of the app exists.
"""

from __future__ import annotations

import os
import sys
import uuid
import xmlrpc.client
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

TIMEOUT_S = 15.0

KEY_MODELS = [
    "res.partner",
    "product.product",
    "mrp.bom",
    "stock.quant",
    "sale.order",
    "mrp.production",
    "purchase.order",
]
# Also needed by later phases (work centers / work orders), so check them now.
EXTRA_MODELS = ["mrp.workcenter", "mrp.workorder"]

# Community-edition apps the spec allows (Odoo rule 2).
REQUIRED_APPS = {
    "sale_management": "Sales",
    "stock": "Inventory",
    "mrp": "Manufacturing",
    "purchase": "Purchase",
}


class OdooError(Exception):
    """A failed Odoo call, carrying a human-readable message."""


# --------------------------------------------------------------------------
# Transports: one small adapter per protocol, same call() signature.
# --------------------------------------------------------------------------


class Json2Transport:
    name = "JSON-2"

    def __init__(self, url: str, db: str, api_key: str) -> None:
        self._client = httpx.Client(
            base_url=url,
            timeout=TIMEOUT_S,
            headers={
                "Authorization": f"bearer {api_key}",
                "X-Odoo-Database": db,
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "voltride-check-odoo/0.1",
            },
        )

    def call(self, model: str, method: str, ids: list[int] | None = None, **kwargs: Any) -> Any:
        body = dict(kwargs)
        if ids is not None:
            body["ids"] = ids
        try:
            resp = self._client.post(f"/json/2/{model}/{method}", json=body)
        except httpx.HTTPError as exc:
            raise OdooError(f"network error: {exc}") from exc
        if resp.status_code == 200:
            return resp.json()
        # Odoo returns {"name", "message", "debug", ...}; the message is enough.
        try:
            message = resp.json().get("message", resp.text[:200])
        except ValueError:
            message = resp.text[:200]
        raise OdooError(f"HTTP {resp.status_code}: {message}")


class XmlRpcTransport:
    name = "XML-RPC"

    def __init__(self, url: str, db: str, login: str, api_key: str) -> None:
        self._db, self._login, self._key = db, login, api_key
        transport = _TimeoutTransport()
        self._common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", transport=transport, allow_none=True)
        self._object = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", transport=transport, allow_none=True)
        self.uid: int | None = None

    def authenticate(self) -> int:
        try:
            uid = self._common.authenticate(self._db, self._login, self._key, {})
        except (xmlrpc.client.Error, OSError) as exc:
            raise OdooError(_xmlrpc_message(exc)) from exc
        if not uid:
            raise OdooError("authenticate() returned False (wrong login, API key or database)")
        self.uid = uid
        return uid

    def call(self, model: str, method: str, ids: list[int] | None = None, **kwargs: Any) -> Any:
        args = [ids] if ids is not None else []
        try:
            return self._object.execute_kw(self._db, self.uid, self._key, model, method, args, kwargs)
        except (xmlrpc.client.Error, OSError) as exc:
            raise OdooError(_xmlrpc_message(exc)) from exc


class _TimeoutTransport(xmlrpc.client.SafeTransport):
    def make_connection(self, host):  # type: ignore[override]
        conn = super().make_connection(host)
        conn.timeout = TIMEOUT_S
        return conn


def _xmlrpc_message(exc: Exception) -> str:
    if isinstance(exc, xmlrpc.client.Fault):
        # faultString is a full server traceback; the last line is the useful bit.
        return exc.faultString.strip().splitlines()[-1][:200]
    return str(exc)[:200]


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


@dataclass
class Result:
    name: str
    ok: bool
    detail: str


results: list[Result] = []


def record(name: str, fn: Callable[[], str]) -> bool:
    """Run one check, record PASS/FAIL with its detail, never raise."""
    try:
        detail = fn()
        results.append(Result(name, True, detail))
        return True
    except OdooError as exc:
        results.append(Result(name, False, str(exc)))
    except Exception as exc:  # noqa: BLE001 - a diagnostic must report, not crash
        results.append(Result(name, False, f"{type(exc).__name__}: {exc}"))
    return False


def check_version(url: str) -> str:
    try:
        resp = httpx.get(f"{url}/web/version", timeout=TIMEOUT_S)
        resp.raise_for_status()
        info = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OdooError(f"cannot reach {url}/web/version: {exc}") from exc
    vi = info.get("version_info", [])
    edition = "Enterprise" if vi and vi[-1] == "e" else "Community"
    return f"Odoo {info.get('version')} ({edition})"


def connect(url: str, db: str, login: str, api_key: str) -> Json2Transport | XmlRpcTransport:
    """Try JSON-2, then XML-RPC. Returns the first transport that authenticates."""
    errors = []
    json2 = Json2Transport(url, db, api_key)
    try:
        ctx = json2.call("res.users", "context_get")
        results.append(Result("Auth (JSON-2)", True, f"authenticated, lang={ctx.get('lang')}, tz={ctx.get('tz')}"))
        return json2
    except OdooError as exc:
        errors.append(f"JSON-2: {exc}")
        results.append(Result("Auth (JSON-2)", False, str(exc)))

    if not login:
        results.append(Result("Auth (XML-RPC)", False, "skipped: ODOO_USER is empty"))
    else:
        xml = XmlRpcTransport(url, db, login, api_key)
        try:
            uid = xml.authenticate()
            results.append(Result("Auth (XML-RPC)", True, f"authenticated as uid {uid}"))
            return xml
        except OdooError as exc:
            errors.append(f"XML-RPC: {exc}")
            results.append(Result("Auth (XML-RPC)", False, str(exc)))
    raise OdooError("; ".join(errors))


def check_apps(odoo) -> str:
    mods = odoo.call(
        "ir.module.module",
        "search_read",
        domain=[["name", "in", list(REQUIRED_APPS)]],
        fields=["name", "state"],
    )
    state = {m["name"]: m["state"] for m in mods}
    missing = [f"{label} ({tech})" for tech, label in REQUIRED_APPS.items() if state.get(tech) != "installed"]
    if missing:
        raise OdooError("not installed: " + ", ".join(missing))
    return "Sales, Inventory, Manufacturing, Purchase installed"


def check_read(odoo, model: str) -> str:
    count = odoo.call(model, "search_count", domain=[])
    # fields_get proves we can introspect the model too (Odoo rule 1).
    fields = odoo.call(model, "fields_get", attributes=["type"])
    return f"{count} records, {len(fields)} fields"


def check_write(odoo) -> str:
    """Create a uniquely named contact, read it back, delete it, verify it's gone."""
    name = f"check_odoo probe {uuid.uuid4().hex[:8]}"
    created = odoo.call("res.partner", "create", vals_list=[{"name": name, "comment": "Temporary record from check_odoo.py"}])
    partner_id = created[0] if isinstance(created, list) else created
    try:
        rows = odoo.call("res.partner", "read", ids=[partner_id], fields=["name"])
        if not rows or rows[0]["name"] != name:
            raise OdooError(f"created res.partner {partner_id} but could not read it back")
    finally:
        # Always clean up, even if the read-back failed.
        odoo.call("res.partner", "unlink", ids=[partner_id])
    if odoo.call("res.partner", "search_count", domain=[["id", "=", partner_id]]) != 0:
        raise OdooError(f"res.partner {partner_id} still exists after unlink")
    return f"created, read back and deleted res.partner {partner_id}"


def print_report(protocol: str | None) -> None:
    width = max(len(r.name) for r in results)
    print()
    for r in results:
        print(f"  {'PASS' if r.ok else 'FAIL'}  {r.name.ljust(width)}  {r.detail}")
    passed = sum(r.ok for r in results)
    print(f"\n  {passed}/{len(results)} checks passed" + (f" - protocol: {protocol}" if protocol else ""))


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    url = os.environ.get("ODOO_URL", "").rstrip("/")
    db = os.environ.get("ODOO_DB", "")
    login = os.environ.get("ODOO_USER", "")
    api_key = os.environ.get("ODOO_API_KEY", "")

    missing = [k for k, v in {"ODOO_URL": url, "ODOO_DB": db, "ODOO_API_KEY": api_key}.items() if not v]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)} (see .env.example)")
        return 2

    print(f"Checking {url} (db={db}, user={login or '-'})")
    if not record("Server version", lambda: check_version(url)):
        print_report(None)
        return 1

    try:
        odoo = connect(url, db, login, api_key)
    except OdooError:
        print_report(None)
        print("\n  Authentication failed. Create a key under avatar > My Preferences >")
        print("  Account Security > New API Key (the MCP token is not an API key).")
        return 1

    record("Required apps", lambda: check_apps(odoo))
    for model in KEY_MODELS + EXTRA_MODELS:
        record(f"Read {model}", lambda m=model: check_read(odoo, m))
    record("Write (create+delete)", lambda: check_write(odoo))

    print_report(odoo.name)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

"""HTTP layer for proposals, quote intake and the audit log."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import deps
from app.main import app
from app.odoo import get_odoo_client
from tests.conftest import SqliteDb
from tests.fakes import FakeOdooClient
from tests.test_chat_loop import ScriptedProvider

A = {"X-Client-Id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
B = {"X-Client-Id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}
SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "quotes"


def extraction() -> dict:
    return {
        "document_type": "quote",
        "supplier_name": "ChipCo",
        "quote_number": "Q-55",
        "quote_date": "2026-10-01",
        "currency": "HKD",
        "lines": [
            {
                "description": "CHIP",
                "supplier_product_code": "CHIP",
                "quantity": 10,
                "unit_price": 60,
                "line_total": 600,
            }
        ],
        "subtotal": 600,
        "tax": 0,
        "total": 600,
        "uncertain_fields": [],
    }


@pytest.fixture
def env(monkeypatch):
    database = SqliteDb()
    odoo = FakeOdooClient()
    provider = ScriptedProvider([], extraction=extraction())
    monkeypatch.setattr(main, "upgrade_to_head", lambda: None)
    app.dependency_overrides[deps.get_provider_factory] = lambda: lambda model: provider
    app.dependency_overrides[deps.get_db_sessionmaker] = database.sessionmaker
    app.dependency_overrides[get_odoo_client] = lambda: odoo
    with TestClient(app) as client:
        yield client, odoo, provider
    app.dependency_overrides.clear()


def pdf_bytes() -> bytes:
    # A real PDF from scripts/make_sample_quotes.py; the fake provider decides
    # what is "extracted", so its content does not matter here.
    return (SAMPLES / "1-clean-taipei-circuit.pdf").read_bytes()


def upload(client, headers=A, content=None):
    files = {"file": ("q.pdf", content if content is not None else pdf_bytes(), "application/pdf")}
    return client.post("/api/intake/quotes", files=files, headers=headers)


def propose(client, review_id, headers=A):
    return client.post(f"/api/intake/quotes/{review_id}/propose", json={}, headers=headers)


def test_quote_upload_review_propose_confirm(env):
    client, odoo, provider = env
    resp = upload(client)
    assert resp.status_code == 200, resp.text
    review = resp.json()
    assert review["can_propose"] and review["supplier"]["name"] == "ChipCo"
    assert provider.extracted == [pdf_bytes()]  # sent to the model from memory

    action = propose(client, review["id"])
    assert action.status_code == 200
    action = action.json()
    assert (action["status"], action["source"]) == ("pending", "quote_intake")
    assert odoo.created == []  # proposing writes nothing

    done = client.post(f"/api/actions/{action['id']}/confirm", headers=A).json()
    assert done["status"] == "executed"
    [(supplier_id, lines, _, partner_ref)] = odoo.created
    assert (supplier_id, partner_ref, lines[0].quantity, lines[0].unit_price) == (201, "Q-55", 10, 60)
    assert client.post(f"/api/actions/{action['id']}/confirm", headers=A).status_code == 409


def test_second_upload_of_same_quote_is_flagged(env):
    client, *_ = env
    first = upload(client).json()
    propose(client, first["id"])
    second = upload(client).json()
    messages = [f["message"] for f in second["flags"]]
    assert any("uploaded before" in m for m in messages)
    assert any("already waiting for confirmation" in m for m in messages)
    assert not second["can_propose"]


def test_corrections_are_rechecked_server_side(env):
    client, _, provider = env
    provider.extraction["lines"][0]["quantity"] = 80  # the model misread 10 as 80
    review = upload(client).json()
    assert not review["can_propose"]
    fixed = client.post(f"/api/intake/quotes/{review['id']}/review", json={"lines": {"0": {"quantity": 10}}}, headers=A)
    assert fixed.json()["can_propose"]
    assert propose(client, review["id"]).status_code == 422  # without the correction it still has errors
    corrected = client.post(
        f"/api/intake/quotes/{review['id']}/propose", json={"lines": {"0": {"quantity": 10}}}, headers=A
    )
    assert corrected.json()["payload"]["orders"][0]["lines"][0]["quantity"] == 10


def test_upload_rejects_non_pdf_oversized_and_unreadable(env):
    client, *_ = env
    assert upload(client, content=b"PK\x03\x04 a zip").status_code == 415
    assert upload(client, content=b"%PDF-" + b"0" * (10 * 1024 * 1024)).status_code == 413
    assert upload(client, content=b"%PDF-1.7 garbage").status_code == 422


def test_extraction_failure_is_502_and_audited(env):
    client, _, provider = env
    provider.extraction = {"document_type": "quote"}  # missing required fields
    assert upload(client).status_code == 502
    [entry] = client.get("/api/audit?kind=extraction", headers=A).json()
    assert entry["ok"] is False


def test_reviews_actions_and_audit_are_owner_scoped(env):
    client, *_ = env
    review = upload(client).json()
    assert client.post(f"/api/intake/quotes/{review['id']}/review", json={}, headers=B).status_code == 404
    action = propose(client, review["id"]).json()
    assert client.get(f"/api/actions/{action['id']}", headers=B).status_code == 404
    assert client.post(f"/api/actions/{action['id']}/confirm", headers=B).status_code == 404
    assert client.get("/api/audit", headers=B).json() == []


def test_reject_then_confirm_is_refused(env):
    client, odoo, _ = env
    action = propose(client, upload(client).json()["id"]).json()
    assert client.post(f"/api/actions/{action['id']}/reject", headers=A).json()["status"] == "rejected"
    assert client.get(f"/api/actions/{action['id']}", headers=A).json()["status"] == "rejected"
    assert client.post(f"/api/actions/{action['id']}/confirm", headers=A).status_code == 409
    assert odoo.created == []


def test_audit_log_newest_first_and_validated(env):
    client, *_ = env
    propose(client, upload(client).json()["id"])
    entries = client.get("/api/audit", headers=A).json()
    assert [(e["kind"], e["name"]) for e in entries] == [("action", "proposed"), ("extraction", "supplier_quote")]
    assert client.get("/api/audit?limit=0", headers=A).status_code == 422

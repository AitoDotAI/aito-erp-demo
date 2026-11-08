"""A PO one visitor submits is shown to that visitor only.

Smart Entry's submit puts the PO at the top of the PO Queue, which is the
workflow loop the demo exists to show. The store behind it was one list for
the whole process, so every visitor's queue and /api/po/submissions listed
what any other visitor had typed as supplier and description, across every
tenant. A submission now belongs to the visitor (an opaque cookie the
submit sets) and the tenant it was made in.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from src import submission_store
from src.config import TENANT_IDS

SECRET_SUPPLIER = "Visitor A Private Supplier Oy"

_FAKE = {"AITO_API_URL": "https://example.invalid", "AITO_API_KEY": "not-a-real-key"}


class Pred:
    def __init__(self, po):
        self.po = po

    def to_dict(self):
        return {"purchase_id": self.po["purchase_id"], "supplier": self.po["supplier"]}


@pytest.fixture
def app(monkeypatch):
    yield from _app(monkeypatch)


@pytest.fixture
def public_app(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "1")
    yield from _app(monkeypatch)


def _app(monkeypatch):
    for key, value in _FAKE.items():
        monkeypatch.setenv(key, value)
    # Reload under these settings: an earlier test may have left the app
    # built with a tiny rate limit (tests/test_app_middleware.py).
    import src.app
    import src.rate_limit

    importlib.reload(src.rate_limit)
    app_module = importlib.reload(src.app)

    # The queue's predictions are Aito's; here only which POs are listed matters.
    monkeypatch.setattr(app_module, "demo_pos_for", lambda tenant: [])
    monkeypatch.setattr(app_module, "predict_batch", lambda aito, pos, tenant: [])
    monkeypatch.setattr(app_module, "predict_single", lambda aito, po, tenant: Pred(po))
    monkeypatch.setattr(app_module, "compute_metrics", lambda preds: {})
    submission_store.clear()
    yield app_module.app
    submission_store.clear()


def submit(client, tenant="metsa"):
    r = client.post("/api/po/submit", headers={"X-Tenant": tenant},
                    json={"supplier": SECRET_SUPPLIER, "description": "private", "amount_eur": 120})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    return r.json()["purchase_id"]


def listed(client, tenant="metsa"):
    subs = client.get("/api/po/submissions", headers={"X-Tenant": tenant}).json()["submissions"]
    queue = client.get("/api/po/pending", headers={"X-Tenant": tenant}).json()
    return subs, queue


def test_visitor_b_does_not_see_visitor_a_submission(app):
    visitor_a, visitor_b = TestClient(app), TestClient(app)
    po = submit(visitor_a)

    subs, queue = listed(visitor_b)
    assert SECRET_SUPPLIER not in str(subs) + str(queue)
    assert subs == [] and queue["recent_submissions"] == []

    subs, queue = listed(visitor_a)
    assert [s["purchase_id"] for s in subs] == [po]
    assert [s["purchase_id"] for s in queue["recent_submissions"]] == [po]
    assert [p["purchase_id"] for p in queue["pos"]] == [po]


def test_a_visitor_with_no_cookie_sees_no_submissions(app):
    submit(TestClient(app))
    subs, queue = listed(TestClient(app))
    assert subs == [] and queue["recent_submissions"] == []


def test_a_submission_stays_in_the_tenant_it_was_made_in(app):
    visitor = TestClient(app)
    po = submit(visitor, tenant="metsa")
    other = next(t for t in TENANT_IDS if t != "metsa")
    subs, queue = listed(visitor, tenant=other)
    assert subs == [] and queue["recent_submissions"] == []
    assert [s["purchase_id"] for s in listed(visitor, tenant="metsa")[0]] == [po]


@pytest.mark.parametrize("body", [
    {"amount_eur": 120},
    {"supplier": "Acme", "amount_eur": "a lot"},
    {"supplier": "Acme", "amount_eur": None},
], ids=["no supplier", "non-numeric amount", "no amount"])
def test_a_submit_it_cannot_store_is_a_400_naming_the_problem(app, body):
    r = TestClient(app).post("/api/po/submit", json=body)
    assert r.status_code == 400, r.text
    assert "amount_eur" in r.json()["detail"] or "supplier" in r.json()["detail"]
    assert submission_store.list_submissions(None, "metsa") == []


def test_the_public_demo_cookie_is_secure_behind_a_tls_proxy(public_app):
    # TLS ends at the proxy, so the app itself sees plain http.
    r = TestClient(public_app, base_url="http://testserver").post(
        "/api/po/submit", json={"supplier": "Acme", "amount_eur": 10})
    assert r.status_code == 200, r.text
    cookie = r.headers["set-cookie"]
    assert "erp_visitor=" in cookie and "Secure" in cookie and "HttpOnly" in cookie, cookie

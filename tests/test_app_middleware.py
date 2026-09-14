"""The middleware stack, and the one property its order has to have.

A throttled request never reaches anything registered before the
throttler, so whatever adds CORS headers must sit OUTSIDE it. It did
not, and the symptom was not "some requests are rate limited" — it was
every view in the browser showing "Failed to fetch" at once, because a
429 with no `Access-Control-Allow-Origin` is a response JavaScript is
not allowed to read at all. It read as a total outage.
"""

import importlib
import os

import pytest


def test_cors_is_the_outermost_middleware():
    """Starlette applies `user_middleware` outside-in, so index 0 wraps
    everything else. This is the cheap version of the test below and the
    one that will still run if the app ever stops importing without
    credentials."""
    import src.app

    names = [m.cls.__name__ for m in src.app.app.user_middleware]
    assert names[0] == "CORSMiddleware", (
        f"CORS must wrap every middleware that can answer on its own; "
        f"the stack is {names}")


@pytest.fixture
def public_client(monkeypatch):
    """The app as a public deployment sees it, with a cap of two."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PUBLIC_DEMO", "1")
    monkeypatch.setenv("CORS_ORIGINS", "https://erp.aito.ai")
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "2")

    import src.app
    import src.rate_limit

    importlib.reload(src.rate_limit)
    importlib.reload(src.app)
    yield TestClient(src.app.app)

    # Put the modules back the way the rest of the suite expects them.
    monkeypatch.undo()
    importlib.reload(src.rate_limit)
    importlib.reload(src.app)


def test_a_throttled_response_is_still_readable_by_the_browser(public_client):
    origin = "https://erp.aito.ai"
    headers = {"Origin": origin, "X-Tenant": "aurora"}

    last = None
    for _ in range(6):
        last = public_client.get("/api/tenants", headers=headers)
        if last.status_code == 429:
            break

    assert last.status_code == 429, (
        "the per-IP cap of 2 never tripped — is PUBLIC_DEMO gating wrong?")
    assert last.headers.get("access-control-allow-origin") == origin, (
        "a 429 came back without CORS headers, so the browser cannot read "
        f"it and reports a network failure instead: {dict(last.headers)}")


def test_the_limiter_is_off_when_the_demo_is_not_public():
    """A developer running the 2000-line eval from a laptop is not the
    traffic this protects against. The deployment docs have always said
    PUBLIC_DEMO gates it; the code did not, until it did."""
    monkey = os.environ.get("PUBLIC_DEMO", "")
    assert monkey.lower() not in ("1", "true", "yes"), (
        "this test assumes the dev environment is not PUBLIC_DEMO")

    import src.app

    assert src.app._PUBLIC is False

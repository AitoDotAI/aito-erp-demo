"""The middleware stack, and the one property its order has to have.

A throttled request never reaches anything registered before the
throttler, so whatever adds CORS headers must sit OUTSIDE it. It did
not, and the symptom was not "some requests are rate limited" — it was
every view in the browser showing "Failed to fetch" at once, because a
429 with no `Access-Control-Allow-Origin` is a response JavaScript is
not allowed to read at all. It read as a total outage.
"""

import importlib

import pytest

# Building the app needs credentials to construct its Aito clients. It
# does not need them to declare a middleware stack, and CI has none, so
# these tests bring their own rather than skipping — an ordering bug
# that only CI could not check for is an ordering bug that comes back.
_FAKE = {
    "AITO_API_URL": "https://example.invalid",
    "AITO_API_KEY": "not-a-real-key",
}


def _import_app(monkeypatch, **extra):
    for key, value in {**_FAKE, **extra}.items():
        monkeypatch.setenv(key, value)
    import src.app
    import src.rate_limit

    importlib.reload(src.rate_limit)
    importlib.reload(src.app)
    return src.app


# No teardown reload. Undoing the fake credentials and re-importing
# raises the very "no credentials" error these tests exist to work
# around — which is how this file failed in CI while passing locally,
# where a .env made the restore survivable. Nothing else in the suite
# imports `src.app`, so leaving it loaded costs nothing.
@pytest.fixture
def app_module(monkeypatch):
    return _import_app(monkeypatch)


def test_cors_is_the_outermost_middleware(app_module):
    """Starlette applies `user_middleware` outside-in, so index 0 wraps
    everything else."""
    names = [m.cls.__name__ for m in app_module.app.user_middleware]
    assert names[0] == "CORSMiddleware", (
        f"CORS must wrap every middleware that can answer on its own; "
        f"the stack is {names}")


def test_a_throttled_response_is_still_readable_by_the_browser(monkeypatch):
    from fastapi.testclient import TestClient

    origin = "https://erp.aito.ai"
    module = _import_app(
        monkeypatch,
        PUBLIC_DEMO="1", CORS_ORIGINS=origin, RATE_LIMIT_PER_IP="2")
    client = TestClient(module.app)
    headers = {"Origin": origin, "X-Tenant": "aurora"}

    last = None
    for _ in range(6):
        last = client.get("/api/tenants", headers=headers)
        if last.status_code == 429:
            break

    assert last.status_code == 429, (
        "the per-IP cap of 2 never tripped — is PUBLIC_DEMO gating wrong?")
    assert last.headers.get("access-control-allow-origin") == origin, (
        "a 429 came back without CORS headers, so the browser cannot read "
        f"it and reports a network failure instead: {dict(last.headers)}")


def test_the_limiter_is_off_when_the_demo_is_not_public(monkeypatch):
    """A developer running the 2000-line eval from a laptop is not the
    traffic this protects against. The deployment docs have always said
    PUBLIC_DEMO gates it; the code did not, until it did."""
    monkeypatch.delenv("PUBLIC_DEMO", raising=False)
    module = _import_app(monkeypatch)
    assert module._PUBLIC is False

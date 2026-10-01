"""Importing the app does nothing to Aito; starting the server warms it.

`src/app.py` ran its cache warm-up at module level, so every script that
imported it — `crosssell_eval`, `demand_eval`, `price_eval`, the
dragon-hunt script's first attempt — computed every view for every
tenant and wrote the results to `prediction_cache` on shared Aito,
as a side effect of `import src.app`. An eval that writes is not an
eval. The warm-up now runs from the FastAPI lifespan, i.e. only when a
server actually starts.
"""

import importlib
import threading

from fastapi.testclient import TestClient

_FAKE = {"AITO_API_URL": "https://example.invalid", "AITO_API_KEY": "not-a-real-key"}


def _reload_app(monkeypatch):
    for key, value in _FAKE.items():
        monkeypatch.setenv(key, value)
    import src.app
    return importlib.reload(src.app)


def test_importing_the_app_starts_no_warm_up(monkeypatch):
    started = []
    real_start = threading.Thread.start

    def recording_start(self):
        started.append(getattr(self, "_target", None))
        return real_start(self)
    monkeypatch.setattr(threading.Thread, "start", recording_start)
    _reload_app(monkeypatch)
    assert not [t for t in started if t and t.__name__ == "warm"], \
        "import src.app started the cache warm-up"


def test_starting_the_server_runs_the_warm_up(monkeypatch):
    app_module = _reload_app(monkeypatch)
    calls = []
    monkeypatch.setattr(app_module, "_warm_cache", lambda: calls.append("warm"))
    with TestClient(app_module.app):
        pass
    assert calls == ["warm"]

"""Scripts that query shared Aito refuse the 08:00-10:00 Helsinki window.

A rule kept by habit was broken twice in two days; this makes it
mechanical. These pin the edges and that every shared-calling script
actually calls the guard before anything else.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.shared_window import in_batch_window, refuse_in_batch_window

HKI = ZoneInfo("Europe/Helsinki")
ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize("hhmm, inside", [("07:59", False), ("08:00", True), ("09:59", True),
                                          ("10:00", False), ("02:09", False)])
def test_the_window_edges(hhmm, inside):
    h, m = map(int, hhmm.split(":"))
    assert in_batch_window(datetime(2026, 10, 3, h, m, tzinfo=HKI)) is inside


def test_the_window_is_helsinki_time_whatever_the_machine_says():
    # 05:04 UTC is 08:04 in Helsinki (EEST) — the slip of 2026-10-03.
    assert in_batch_window(datetime(2026, 10, 3, 5, 4, tzinfo=timezone.utc))


def test_refusal_says_what_and_when():
    with pytest.raises(SystemExit, match=r"match-eval: refused at 08:04 Helsinki"):
        refuse_in_batch_window("match-eval", datetime(2026, 10, 3, 8, 4, tzinfo=HKI))


SHARED_SCRIPTS = ["src/match_eval.py", "src/demand_eval.py", "src/price_eval.py",
                  "src/crosssell_eval.py", "src/v2_conformance.py", "src/v2_optimize_ab.py",
                  "src/data_loader.py", "src/preflight.py", "scripts/capture_coldstart.py",
                  "scripts/dragon_hunt_demo_path.py"]


@pytest.mark.parametrize("path", SHARED_SCRIPTS)
def test_every_shared_calling_script_guards_its_main(path):
    source = (ROOT / path).read_text()
    main = re.search(r"^def main\(.*?(?=^def |\Z)", source, re.S | re.M)
    assert main, f"{path} has no main()"
    first_lines = "\n".join(main.group(0).splitlines()[:12])
    assert "refuse_in_batch_window(" in first_lines, f"{path}: main() must call the guard first"


def test_a_live_query_in_the_window_skips_instead_of_sending(monkeypatch):
    """The conftest guard, exercised offline: in the window, a real client
    send becomes a skip and never a request. The host is .invalid, so even
    a broken guard could not reach shared Aito."""
    from src import aito_client
    import tests.conftest as conftest
    monkeypatch.setattr(conftest, "in_batch_window", lambda now=None: True)
    monkeypatch.setattr(aito_client.AitoClient, "_request", aito_client.AitoClient._request)
    monkeypatch.setattr(aito_client._TimedAitoClientV2, "request", aito_client._TimedAitoClientV2.request)
    assert conftest.install_batch_window_guard()
    client = aito_client.AitoClient.from_creds("https://example.invalid/db/x", "k", api_version="v1")
    with pytest.raises(pytest.skip.Exception, match="batch window"):
        client.search("purchases", {}, limit=1)

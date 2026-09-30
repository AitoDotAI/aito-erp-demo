"""Side-panel stats and landing claims come from code or measurement.

The audit of 2026-09-30 found the side panels quoting numbers nothing
measured — "Avg latency 12ms", "18ms", "30-80ms" (the latency pill shows
the real ones), Catalog's "Incomplete 12 / Predictable 9 / Avg missing
2.3" on screen after the real list had loaded, Rule Mining's "Min
support 10" while the service uses 3 — and the retail landing quoting
only the half of each measurement where Aito wins.
"""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "frontend"
STAT = re.compile(r'\{\s*label:\s*"([^"]+)",\s*value:\s*"([^"]*)"\s*\}')

# Literal numbers allowed only where they describe the QUERY's shape,
# which is fixed by the code on the same screen, not a result.
QUERY_SHAPE_LABELS = {"Cutoffs", "Fields", "Predict fields"}


def _stats():
    for path in sorted([*FRONTEND.joinpath("app").rglob("*.tsx"), *FRONTEND.joinpath("lib").rglob("*.ts")]):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for label, value in STAT.findall(line):
                yield f"{path.relative_to(FRONTEND)}:{n}", label, value


def test_no_panel_stat_is_a_typed_in_number():
    bad = [f"{where} {label}={value!r}" for where, label, value in _stats()
           if re.match(r"[~0-9€$<>]", value) and label not in QUERY_SHAPE_LABELS]
    assert not bad, "typed-in panel stats:\n" + "\n".join(bad)


def test_no_panel_quotes_a_latency_nobody_measured():
    bad = [f"{where} {label}={value!r}" for where, label, value in _stats()
           if re.search(r"\d\s*ms\b", value)]
    assert not bad, "unmeasured latencies:\n" + "\n".join(bad)


def test_rule_mining_reports_the_support_floor_it_uses():
    from src.rulemining_service import MIN_SUPPORT, get_rule_summary
    assert get_rule_summary([])["min_support"] == MIN_SUPPORT
    page = (FRONTEND / "app" / "rules" / "page.tsx").read_text()
    assert "min_support" in page, "the page must read the floor from the response"


def test_the_retail_tiles_quote_where_aito_loses_too():
    """A measured claim is quoted whole: the demand tile names the rule
    Aito does not beat on Aurora, the cross-sell tile the band where
    counting wins."""
    from src.demand_service import MEASURED
    from src.recommendation_service import CROSS_SELL_MEASURED
    page = (FRONTEND / "app" / "retail" / "page.tsx").read_text()
    aurora = MEASURED["by_tenant"]["aurora"]
    for figure in (aurora["aito"], aurora["last_year"], aurora["trailing"]):
        assert f"{figure * 100:.1f}%" in page, figure
    reduction = round((1 - aurora["aito"] / aurora["trailing"]) * 100)
    assert f"{reduction}% less error than the reorder rule" in page
    rare = CROSS_SELL_MEASURED["rarely_bought"]
    assert f"{rare['view']}/{rare['of']}" in page and f"{rare['counting']}/{rare['of']}" in page

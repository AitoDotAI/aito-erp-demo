"""The live smoke's content checks (scripts/live_smoke.py), offline.

Shapes follow main (#46: demand/pricing/inventory computed from data). The
failing shapes are what erp.aito.ai served on 29.9 before #46 was deployed.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "live_smoke", Path(__file__).resolve().parents[1] / "scripts" / "live_smoke.py")
smoke = importlib.util.module_from_spec(_spec)
sys.modules["live_smoke"] = smoke          # @dataclass looks its module up here
_spec.loader.exec_module(smoke)


def _product(history, aito):
    return {"sku": "SKU-1", "history": history, "horizon": [{"month": "2026-10", "aito": aito}]}


def test_demand_passes_when_a_product_is_forecast_from_history():
    assert "1/2" in smoke.check_demand(
        {"products": [_product([{"month": "2026-08", "qty": 3}], 4.2), _product([], 0)]})


def test_demand_fails_when_every_forecast_is_zero():
    # 29.9: every hero SKU had history [] and forecast 0
    with pytest.raises(AssertionError, match="non-zero forecast"):
        smoke.check_demand({"products": [_product([], 0), _product([], 0.0)]})


def test_demand_fails_on_the_pre_46_shape():
    with pytest.raises(AssertionError, match="no `products` list"):
        smoke.check_demand({"forecasts": [], "impact": {}, "month": "2026-09"})


def test_inventory_fails_when_everything_is_overstock():
    items = [{"sku": f"S{i}", "status": "overstock"} for i in range(4)]
    with pytest.raises(AssertionError, match="overstock"):
        smoke.check_inventory({"items": items, "counts": {"overstock": 4}})
    items[0]["status"] = "low"
    assert "3 overstock" in smoke.check_inventory({"items": items, "counts": {"overstock": 3}})


def test_pricing_needs_an_aito_estimate():
    body = {"products": [{"sku": "S", "quotes": [{"aito": 0, "flagged": False}]}]}
    with pytest.raises(AssertionError, match="Aito estimate"):
        smoke.check_pricing(body)
    body["products"][0]["quotes"].append({"aito": 24.9, "flagged": True})
    assert "1/2 quotes estimated, 1 flagged" in smoke.check_pricing(body)


def test_estimate_needs_comparables():
    with pytest.raises(AssertionError, match="comparable"):
        smoke.check_estimate({"cost_eur": 160904.76, "duration_days": 143, "neighbour_count": 0})
    assert "8 neighbours" in smoke.check_estimate(
        {"cost_eur": 160904.76, "duration_days": 143, "neighbour_count": 8})


def test_every_step_is_a_read():
    # the planner POSTs predict/estimate and store nothing; everything else is a GET
    posts = {s.name for s in smoke.STEPS if s.body is not None}
    assert posts == {"planner/plan", "planner/estimate"}


def test_each_view_runs_on_a_tenant_that_shows_it():
    # frontend/lib/tenants.ts hideRoutes: demand is aurora-only, utilization studio-only
    by_name = {s.name: s.tenant for s in smoke.STEPS}
    assert by_name["demand/forecast"] == "aurora"
    assert by_name["utilization/overview"] == "studio"
    assert by_name["recommendations/cross-sell"] == by_name["recommendations/similar"] == "aurora"

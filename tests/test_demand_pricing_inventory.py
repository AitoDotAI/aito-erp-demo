"""Demand, Pricing and Inventory: what each number on screen is allowed to be.

These three views used to read hard-coded SKUs whose names had drifted
to other products, and fill the gaps with invented confidences and euro
figures. Each test below pins one property that keeps the replacement
honest: the estimate never sees what it is judged on, names come from
the same row as the SKU, and a missing number is an error, not a zero.
"""

import pytest

from src import demand_service, inventory_service, pricing_service
from src.demand_service import FEATURES, pick_products


def _row(sku, month, units, category="Fleet & Fuel", supplier="Neste Oyj"):
    moy = int(month[5:])
    season = ["winter", "winter", "spring", "spring", "spring", "summer", "summer",
              "summer", "autumn", "autumn", "autumn", "winter"][moy - 1]
    return {"sku": sku, "month": month, "units_sold": units, "category": category,
            "supplier": supplier, "season": season, "last_year_band": "20-26",
            "month_of_year": month[5:], "year": month[:4]}


HISTORY = ([_row("SKU-A", f"2024-{m:02d}", 30) for m in range(1, 13)]
           + [_row("SKU-A", f"2025-{m:02d}", 30) for m in range(1, 10)]
           + [_row("SKU-B", f"2025-{m:02d}", 5) for m in range(1, 10)]
           + [_row("SKU-C", f"2024-{m:02d}", 50, category="Spare Parts") for m in range(10, 13)]
           + [_row("SKU-C", f"2025-{m:02d}", 50, category="Spare Parts") for m in range(1, 10)])
HOLDOUT = [_row("SKU-A", "2025-10", 33), _row("SKU-A", "2025-11", 35),
           _row("SKU-C", "2025-10", 48, category="Spare Parts")]


class _Aito:
    """Answers `search` from in-memory tables and `estimate` with a fixed
    number, recording every `where` it was asked about."""

    def __init__(self, tables, estimate=31.0):
        self.tables, self.value, self.asked = tables, estimate, []

    def search(self, table, where, limit=10):
        rows = [r for r in self.tables[table] if all(r.get(k) == v for k, v in where.items())]
        return {"total": len(rows), "hits": rows[:limit]}

    def estimate(self, table, where, field):
        self.asked.append((table, dict(where)))
        return {"estimate": self.value, "why": {"components": [{}, {}, {}]}}


def _tables(**extra):
    return {"monthly_demand": HISTORY, "monthly_demand_holdout": HOLDOUT,
            "products": [{"sku": "SKU-A", "name": "AdBlue 10L", "unit_price": 20.0},
                         {"sku": "SKU-C", "name": "Drive Shaft", "unit_price": 800.0}],
            **extra}


# ── Demand ──────────────────────────────────────────────────────────

def test_products_are_picked_from_the_data_one_per_category():
    """Hard-coded SKUs went stale when the catalogue was regenerated:
    every name pointed at another product. The pick is recomputed."""
    assert pick_products(HISTORY) == ["SKU-C", "SKU-A"]   # SKU-B loses Fleet & Fuel to SKU-A


def test_the_forecast_never_names_the_month_it_forecasts():
    """`month` is unique per product, so in the `where` it names a row
    rather than describing one."""
    aito = _Aito(_tables())
    demand_service.get_demand_forecast(aito, tenant="metsa")
    assert aito.asked and all(set(w) == set(FEATURES) for _, w in aito.asked)
    assert all(t == "monthly_demand" for t, _ in aito.asked), "the holdout is never estimated FROM"


def test_the_name_comes_from_the_same_row_as_the_sku():
    out = demand_service.get_demand_forecast(_Aito(_tables()), tenant="metsa")
    names = {p["sku"]: p["name"] for p in out["products"]}
    assert names == {"SKU-A": "AdBlue 10L", "SKU-C": "Drive Shaft"}


def test_each_forecast_month_carries_what_happened_and_the_two_rules():
    out = demand_service.get_demand_forecast(_Aito(_tables()), tenant="metsa")
    oct_ = next(p for p in out["products"] if p["sku"] == "SKU-A")["horizon"][0]
    assert oct_ == {"month": "2025-10", "aito": 31.0, "last_year": 30, "trailing": 30.0,
                    "actual": 33, "neighbours": 3,
                    # the exact `where` sent, which is what the panel shows
                    "where": {"sku": "SKU-A", "season": "autumn", "last_year_band": "20-26"}}


def test_a_missing_baseline_month_is_named_not_guessed():
    history = [r for r in HISTORY if not (r["sku"] == "SKU-C" and r["month"] == "2024-10")]
    with pytest.raises(KeyError, match="SKU-C: no sales row for 2024-10"):
        demand_service.get_demand_forecast(_Aito(_tables(monthly_demand=history)), tenant="metsa")


def test_an_estimate_without_a_number_is_an_error_not_a_zero():
    aito = _Aito(_tables(), estimate=None)
    with pytest.raises(ValueError):
        demand_service.get_demand_forecast(aito, tenant="metsa")


def test_a_short_read_is_an_error_not_a_smaller_table():
    class _Short(_Aito):
        def search(self, table, where, limit=10):
            res = super().search(table, where, limit)
            return {**res, "total": res["total"] + 1}
    with pytest.raises(RuntimeError, match="read"):
        demand_service.get_demand_forecast(_Short(_tables()), tenant="metsa")


# ── Pricing ─────────────────────────────────────────────────────────

REFERENCE = [{"price_id": f"R{i}", "product_id": "SKU-A", "supplier": "Neste Oyj",
              "unit_price": p, "volume": 10, "order_date": f"2025-0{i}-01"}
             for i, p in enumerate([19.0, 20.0, 21.0], start=1)]
QUOTES = [{"price_id": "Q1", "product_id": "SKU-A", "supplier": "Neste Oyj",
           "unit_price": 20.5, "volume": 10, "order_date": "2025-10-03"},
          {"price_id": "Q2", "product_id": "SKU-A", "supplier": "Shell",
           "unit_price": 27.0, "volume": 10, "order_date": "2025-11-03"},
          {"price_id": "Q3", "product_id": "SKU-C", "supplier": "Shell",
           "unit_price": 900.0, "volume": 1, "order_date": "2025-11-09"}]


def _pricing(estimate=20.0):
    return _Aito(_tables(price_reference=REFERENCE, price_quotes=QUOTES), estimate=estimate)


def test_a_quote_is_judged_only_by_prices_from_before_it():
    """The estimate reads `price_reference` — never the table holding the
    quote it is scoring."""
    aito = _pricing()
    pricing_service.get_pricing_overview(aito, tenant="metsa")
    assert aito.asked and all(t == "price_reference" for t, _ in aito.asked)
    assert all(set(w) == set(pricing_service.FEATURES) for _, w in aito.asked)


def test_a_product_never_priced_before_is_not_shown():
    """With no earlier price the estimate falls back on supplier and
    volume alone and misses by half; showing it would teach the wrong
    thing."""
    out = pricing_service.get_pricing_overview(_pricing(), tenant="metsa")
    assert [p["sku"] for p in out["products"]] == ["SKU-A"]


def test_the_flag_is_the_margin_over_the_estimate_and_the_median_sits_beside_it():
    out = pricing_service.get_pricing_overview(_pricing(), tenant="metsa")
    q1, q2 = out["products"][0]["quotes"]
    assert (q1["flagged"], q2["flagged"]) == (False, True)     # 2.5% vs 35% over 20.0
    assert q1["median"] == 20.0 and out["products"][0]["list_price"] == 20.0


# ── Inventory ───────────────────────────────────────────────────────

def _stock(**over):
    return [{"sku": "SKU-A", "supplier": "Neste Oyj", "on_hand": 10, "on_order": 50,
             "next_delivery_month": "2025-12", "lead_time_days": 20,
             "reorder_point": 25, "safety_stock": 5, "as_of_month": "2025-09", **over}]


def _inventory(stock, estimate=30.0):
    return inventory_service.get_inventory_status(
        _Aito(_tables(stock=stock), estimate=estimate), tenant="metsa")["items"][0]


def test_a_delivery_after_the_lead_time_does_not_count():
    """10 on hand covers 10 days at 1/day; the 50 on order lands in
    December, after a new order could — so it is short."""
    item = _inventory(_stock())
    assert item["arriving_in_time"] == 0 and item["status"] == "critical"


def test_a_delivery_within_the_lead_time_counts():
    item = _inventory(_stock(next_delivery_month="2025-10"))
    assert item["arriving_in_time"] == 50 and item["status"] != "critical"


def test_no_delivery_month_means_nothing_is_on_order():
    """Aito omits a null column from the hit; absence is the null."""
    stock = _stock(on_order=0)
    del stock[0]["next_delivery_month"]
    assert _inventory(stock)["arriving_in_time"] == 0


def test_the_warning_is_checked_against_what_happened():
    out = inventory_service.get_inventory_status(
        _Aito(_tables(stock=_stock())), tenant="metsa")
    # Aito forecasts 1/day and says short; October actually sold 33 (1.1/day) — short too.
    assert out["warnings"]["aito"] == {"raised": 1, "right": 1, "real_shortfalls": 1, "caught": 1}


# ── The generated tables ────────────────────────────────────────────

def _generator():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "generate_demand", Path(__file__).parent.parent / "data" / "generate_demand.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_demand_tables_regenerate_to_the_same_universe():
    """The tables are loaded into Aito once; a rebuild that drew
    differently would describe a world the database does not hold."""
    gen = _generator()
    products = [{"sku": "SKU-1", "category": "DIY", "unit_price": 40.0, "supplier": "Bauhaus"}]
    assert gen.generate_demand("aurora", products) == gen.generate_demand("aurora", products)


def test_a_category_without_a_declared_season_is_an_error():
    """Every seasonal pattern is written down per category; one that is
    not declared must not quietly default to flat."""
    with pytest.raises(ValueError, match="no seasonality declared"):
        _generator().generate_demand("aurora", [{"sku": "S", "category": "Space Rockets",
                                                 "unit_price": 1.0}])

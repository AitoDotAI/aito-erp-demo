"""Demand Forecast — `_estimate units_sold`, checked against what happened.

Reads `monthly_demand` (history up to the cutoff) and forecasts the six
months in `monthly_demand_holdout`, which `_estimate` has never seen, so
each forecast is shown next to the actual and next to the two rules a
buyer already has: same month last year, and the trailing three-month
average a plain ERP reorder rule uses.

Why these tables and not `orders`: `orders` draws units uniformly at
random, so there was nothing to forecast and the view filled the gap
with a rule-of-thumb "confidence" and invented euro savings. See
data/generate_demand.py.

The measured accuracy below is quoted on screen and is the only claim
the view makes. On this corpus Aito is ahead of "same month last year"
on Metsä and behind it on Aurora and Studio, and has 15-42% less error
than the trailing average. It does not beat every rule, and the view
computes its wording from the numbers rather than saying it does.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from src.aito_client import AitoClient
from src.concurrency import parallel_map

# The `where` of every forecast. Which product, when in the year, and
# what that product sold in the same month last year (banded). `month`
# itself is left out: it is unique per product, so it names a row
# rather than describing one.
#
# Chosen by `./do demand-eval`, and the search stopped at ten shapes on
# purpose: past that, picking the best is fitting the holdout.
# `last_year_band` is what moved it — without recency evidence
# `_estimate` averaged every past December equally and lost to the
# seasonal naive rule by 6-9 points; with it, it is within 3 points
# either way.
FEATURES = ("sku", "season", "last_year_band")

PRODUCTS_SHOWN = 4
HISTORY_SHOWN = 24   # months of history on the chart

# `./do demand-eval`, 2026-09-28, WAPE over the six held-out months.
# Restated here because the view quotes it; re-run and update together.
MEASURED = {
    "measured_on": "2026-09-28",
    "engine_build": "2.10.3 (88786b4dc970), rep2",
    "metric": "WAPE: total |forecast - actual| / total actual units",
    "by_tenant": {
        "metsa":  {"n": 282, "aito": 0.168, "last_year": 0.185, "trailing": 0.292},
        "aurora": {"n": 300, "aito": 0.188, "last_year": 0.177, "trailing": 0.240},
        "studio": {"n": 174, "aito": 0.204, "last_year": 0.176, "trailing": 0.239},
    },
}


@dataclass
class HorizonMonth:
    month: str
    aito: float          # `_estimate units_sold`
    last_year: int       # same month last year
    trailing: float      # mean of the three months before the cutoff
    actual: int          # what happened (held out from the estimate)
    neighbours: int      # history rows the estimate weighted
    where: dict          # the exact `where` sent, so the panel can show it

    def to_dict(self) -> dict:
        return {"month": self.month, "where": self.where, "aito": round(self.aito, 1),
                "last_year": self.last_year, "trailing": round(self.trailing, 1),
                "actual": self.actual, "neighbours": self.neighbours}


@dataclass
class ProductForecast:
    sku: str
    name: str
    category: str
    supplier: str
    history: list[dict]
    horizon: list[HorizonMonth]

    def to_dict(self) -> dict:
        return {"sku": self.sku, "name": self.name, "category": self.category,
                "supplier": self.supplier, "history": self.history,
                "horizon": [h.to_dict() for h in self.horizon]}


def _whole_table(client: AitoClient, table: str, where: dict | None = None) -> list[dict]:
    """Every matching row. A short page would silently forecast from a
    subset, so the count is asserted."""
    res = client.search(table, where or {}, limit=50_000)
    hits = res.get("hits") or []
    if res.get("total") != len(hits):
        raise RuntimeError(f"{table}: read {len(hits)} of {res.get('total')} rows")
    return hits


def pick_products(history: list[dict], count: int = PRODUCTS_SHOWN) -> list[str]:
    """The products the view shows, chosen from the data every time.

    The best seller of each category over the last twelve months, busiest
    categories first. A list of SKUs typed into the code went stale the
    moment the catalogue was regenerated: every hard-coded name pointed at
    a different product and eleven of twelve had no sales at all.
    """
    last_months = sorted({r["month"] for r in history})[-12:]
    units: dict[str, int] = defaultdict(int)
    category_of: dict[str, str] = {}
    for r in history:
        if r["month"] in last_months:
            units[r["sku"]] += r["units_sold"]
            category_of[r["sku"]] = r["category"]
    best: dict[str, str] = {}
    for sku in sorted(units, key=lambda s: (-units[s], s)):
        best.setdefault(category_of[sku], sku)
    ranked = sorted(best.values(), key=lambda s: (-units[s], s))
    if not ranked:
        raise RuntimeError("monthly_demand has no sales in its last twelve months")
    return ranked[:count]


def forecast_product(client: AitoClient, sku: str, history: list[dict],
                     holdout: list[dict], product: dict) -> ProductForecast:
    """Forecast one product across the held-out months."""
    own = sorted((r for r in history if r["sku"] == sku), key=lambda r: r["month"])
    by_month = {r["month"]: r["units_sold"] for r in own}
    trailing = sum(r["units_sold"] for r in own[-3:]) / 3
    ahead = sorted((r for r in holdout if r["sku"] == sku), key=lambda r: r["month"])
    if not ahead:
        raise RuntimeError(f"{sku}: no held-out months to forecast")

    def estimate(row: dict) -> HorizonMonth:
        where = {k: row[k] for k in FEATURES}
        res = client.estimate("monthly_demand", where, "units_sold")
        value = res.get("estimate")
        if not isinstance(value, (int, float)):
            raise ValueError(f"_estimate units_sold returned no number for {sku}: {res}")
        prior = f"{int(row['month'][:4]) - 1}{row['month'][4:]}"
        if prior not in by_month:
            raise KeyError(f"{sku}: no sales row for {prior}, so no same-month-last-year baseline")
        return HorizonMonth(
            month=row["month"], aito=float(value), last_year=by_month[prior],
            trailing=trailing, actual=row["units_sold"],
            neighbours=len((res.get("why") or {}).get("components") or []),
            where=where)

    horizon = parallel_map(estimate, ahead, workers=6)

    return ProductForecast(
        sku=sku, name=product["name"], category=own[-1]["category"],
        supplier=own[-1]["supplier"],
        history=[{"month": r["month"], "units": r["units_sold"]} for r in own[-HISTORY_SHOWN:]],
        horizon=horizon)


def get_demand_forecast(client: AitoClient, tenant: str) -> dict:
    history = _whole_table(client, "monthly_demand")
    holdout = _whole_table(client, "monthly_demand_holdout")
    products = []
    for sku in pick_products(history):
        # Name and history come from the same SKU, read in the same pass:
        # a price or a forecast under the wrong product name is the
        # mistake this replaces.
        rows = client.search("products", {"sku": sku}, limit=1).get("hits") or []
        if not rows:
            raise RuntimeError(f"{sku} sells in monthly_demand but is not in products")
        products.append(forecast_product(client, sku, history, holdout, rows[0]))

    # Indexed, not defaulted: quoting one tenant's measurement on
    # another tenant's screen would be a number the page cannot back.
    measured = MEASURED["by_tenant"].get(tenant)
    if measured is None:
        raise KeyError(f"no demand measurement recorded for tenant {tenant!r}")
    return {
        "cutoff": min(r["month"] for r in holdout),
        "products": [p.to_dict() for p in products],
        "features": list(FEATURES),
        "measured": {**{k: v for k, v in MEASURED.items() if k != "by_tenant"}, **measured},
    }

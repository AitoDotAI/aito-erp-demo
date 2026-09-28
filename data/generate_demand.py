"""Demand, stock and price tables with structure worth predicting.

Demand Forecast, Price Intelligence and Inventory used to read `orders`,
and `orders` is noise: `generate_orders` draws `units_sold` uniformly
from 1-35, independent of product, month and season. No forecast can
beat "predict the average" on that, so those views had nothing true to
show and filled the gap with made-up confidences and euro figures.

This script writes five ADDITIVE tables per tenant. Nothing existing is
changed, so `orders` keeps serving the trending ribbon it serves today.

  monthly_demand          one row per product per month, up to CUTOFF.
                          Per-category seasonality, a per-product level
                          and trend, Poisson noise. What `_estimate
                          units_sold` learns from.
  monthly_demand_holdout  the six months after CUTOFF, never shown to
                          `_estimate`. What happened, so a forecast can
                          be checked on screen. Deliberately link-free,
                          like `invoice_lines_holdout`.
  stock                   the position at CUTOFF, simulated by playing
                          `monthly_demand` against a reorder policy.
                          Synthetic, and labelled so on screen, but
                          depleted by the same sales the forecast sees.
  price_reference         `price_history` rows dated before CUTOFF.
  price_quotes            `price_history` rows dated on or after it: the
                          "incoming quotes" Pricing scores against an
                          estimate that has never seen them.

The one policy choice that matters for the story: the simulated
reorder point is set from a TRAILING three-month average, the way a
plain ERP min/max rule does it. It cannot see a seasonal peak coming.
That is a real, common failure, and it is the gap a seasonal forecast
closes. It is declared here rather than hidden in the numbers.

Run: `python data/generate_demand.py` (reads data/<tenant>/products.json
and price_history.json, writes the five tables next to them).
"""

from __future__ import annotations

import json
import math
import random
import zlib
from pathlib import Path

DATA = Path(__file__).parent
TENANTS = ("metsa", "aurora", "studio")

HISTORY_START = (2022, 6)
CUTOFF = "2025-10"          # first month the forecast has NOT seen
HOLDOUT_END = (2026, 3)

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SEASON_BY_MONTH = ["winter", "winter", "spring", "spring", "spring", "summer",
                   "summer", "summer", "autumn", "autumn", "autumn", "winter"]

# Demand multiplier by calendar month, January first. Each line is a
# claim about the category that a buyer would recognise.
SEASONALITY: dict[str, list[float]] = {
    # Metsä — industrial maintenance
    "Fleet & Fuel":          [1.35, 1.30, 1.15, 0.95, 0.85, 0.75, 0.70, 0.75, 0.90, 1.05, 1.20, 1.35],  # heating, winter diesel
    "Maintenance Services":  [0.80, 0.85, 1.30, 1.35, 1.00, 0.80, 0.55, 0.80, 1.35, 1.30, 1.00, 0.80],  # spring + autumn service rounds
    "Electrical Components": [1.00, 1.00, 1.05, 1.05, 1.00, 0.95, 0.80, 0.90, 1.10, 1.10, 1.05, 0.95],  # near-flat
    "Spare Parts":           [0.95, 0.95, 1.00, 1.00, 1.00, 1.10, 1.50, 1.20, 0.90, 0.90, 0.90, 0.80],  # July shutdown overhauls
    "PPE & Workwear":        [1.20, 0.90, 0.90, 1.00, 1.00, 0.90, 0.80, 1.60, 1.20, 0.90, 0.80, 0.80],  # August hiring, January kit
    # Aurora — retail
    "Electronics":           [0.80, 0.70, 0.80, 0.80, 0.80, 0.80, 0.80, 0.90, 0.90, 1.00, 1.60, 2.10],  # Black Friday, Christmas
    "Groceries":             [0.95, 0.90, 0.95, 1.00, 1.05, 1.15, 1.20, 1.05, 0.95, 0.95, 1.00, 1.40],  # midsummer, Christmas
    "Fashion":               [0.70, 0.70, 1.00, 1.10, 1.10, 1.00, 0.90, 1.20, 1.20, 1.00, 1.00, 1.30],  # new seasons, gifts
    "Household":             [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.05, 1.10],  # staples
    "Beauty":                [0.90, 1.00, 0.95, 0.95, 1.05, 1.00, 0.90, 0.95, 1.00, 1.00, 1.20, 1.60],  # gift season
    "Homeware":              [0.80, 0.80, 0.90, 0.95, 1.00, 1.00, 0.90, 0.95, 1.00, 1.10, 1.30, 1.60],
    "DIY":                   [0.50, 0.60, 0.90, 1.40, 1.70, 1.60, 1.40, 1.10, 0.90, 0.80, 0.60, 0.50],  # spring projects
    # Vire — consultancy back office
    "Catering":              [1.05, 1.05, 1.05, 1.00, 1.00, 0.85, 0.35, 0.90, 1.15, 1.10, 1.10, 0.90],  # July holiday
    "Office Supplies":       [1.30, 1.00, 1.00, 0.95, 0.90, 0.80, 0.50, 1.40, 1.30, 1.00, 0.95, 0.80],  # back to work
    "Software Licenses":     [1.90, 1.00, 0.90, 0.90, 0.90, 0.90, 0.80, 0.90, 1.00, 0.90, 0.90, 1.00],  # January renewals
}

# Services and licences are not stocked: they have demand, not inventory.
NOT_STOCKED = {"Maintenance Services", "Software Licenses"}

# Replenishment lead time by category, in days, before per-SKU jitter.
LEAD_TIME_DAYS: dict[str, int] = {
    "Fleet & Fuel": 7, "Electrical Components": 21, "Spare Parts": 45,
    "PPE & Workwear": 14, "Electronics": 30, "Groceries": 3, "Fashion": 45,
    "Household": 10, "Beauty": 14, "Homeware": 21, "DIY": 21,
    "Catering": 5, "Office Supplies": 7,
}


# Geometric bands for last year's units: each ~1.35x the one before, so
# a band means the same RELATIVE thing for a slow and a fast mover.
BAND_EDGES = [0, 1, 2, 3, 4, 6, 8, 11, 15, 20, 27, 36, 48, 64, 85, 113, 150, 200, 270, 360, 480]


def units_band(units: int | None) -> str:
    """Bucket a unit count. Aito matches a raw number in a `where` as an
    exact value, which no other row shares; a band is evidence it can
    generalise across — the same reason `quotes.price_band` exists."""
    if units is None:
        return "none"
    for lo, hi in zip(BAND_EDGES, BAND_EDGES[1:]):
        if units < hi:
            return f"{lo}-{hi - 1}" if hi - 1 > lo else str(lo)
    return f"{BAND_EDGES[-1]}+"


def _months(start: tuple[int, int], end: tuple[int, int]) -> list[str]:
    y, m = start
    out = []
    while (y, m) <= end:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _poisson(rng: random.Random, lam: float) -> int:
    """Poisson draw; normal approximation above 30, where it is exact enough."""
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    threshold, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


def _base_level(rng: random.Random, price: float) -> float:
    """Monthly units at seasonality 1.0. Cheap goods move in volume."""
    typical = 40 * (50 / max(price, 5.0)) ** 0.35
    return math.exp(rng.gauss(math.log(typical), 0.5))


def generate_demand(tenant: str, products: list[dict]) -> tuple[list[dict], list[dict]]:
    rng = random.Random(zlib.crc32(f"{tenant}:demand".encode()))
    all_months = _months(HISTORY_START, HOLDOUT_END)
    history, holdout = [], []
    for p in sorted(products, key=lambda r: r["sku"]):
        category = p.get("category")
        if not category:
            continue  # uncategorised catalogue rows are Catalog's case, not sold goods
        if category not in SEASONALITY:
            raise ValueError(f"{tenant}: no seasonality declared for {category!r}")
        level = _base_level(rng, p.get("unit_price") or 50.0)
        trend = rng.gauss(0.004, 0.008)          # per month
        for i, month in enumerate(all_months):
            moy = int(month[5:]) - 1
            lam = level * SEASONALITY[category][moy] * (1 + trend) ** i
            row = {
                "sku": p["sku"],
                "month": month,
                "month_of_year": MONTH_NAMES[moy],
                "season": SEASON_BY_MONTH[moy],
                "category": category,
                "supplier": p.get("supplier") or "",
                "units_sold": _poisson(rng, max(lam, 0.05)),
            }
            (history if month < CUTOFF else holdout).append(row)
    # Recency. `_estimate` weighs neighbours with no notion of time, so
    # it averaged three Decembers equally and lost to "same month last
    # year" wherever a product trended. Each row now carries what that
    # rule knows — last year's same-month sales, banded — as evidence.
    # It is a fact about the past, known at forecast time for every
    # holdout month, so nothing from the future leaks in.
    units_at = {(r["sku"], r["month"]): r["units_sold"] for r in history + holdout}
    for row in history + holdout:
        row["year"] = row["month"][:4]
        prior = f"{int(row['month'][:4]) - 1}{row['month'][4:]}"
        row["last_year_band"] = units_band(units_at.get((row["sku"], prior)))
    for n, row in enumerate(history, 1):
        row["demand_id"] = f"MD-{n:06d}"
    for n, row in enumerate(holdout, 1):
        row["demand_id"] = f"MDH-{n:05d}"
    return history, holdout


def simulate_stock(tenant: str, products: list[dict], history: list[dict]) -> list[dict]:
    """Play each stocked product's sales against a trailing-average min/max
    rule and report where it stands at CUTOFF."""
    rng = random.Random(zlib.crc32(f"{tenant}:stock".encode()))
    by_sku: dict[str, list[dict]] = {}
    for row in history:
        by_sku.setdefault(row["sku"], []).append(row)
    names = {p["sku"]: p for p in products}
    stock_rows = []
    for sku in sorted(by_sku):
        rows = sorted(by_sku[sku], key=lambda r: r["month"])
        category = rows[0]["category"]
        if category in NOT_STOCKED:
            continue
        lead_days = max(1, round(LEAD_TIME_DAYS[category] * rng.uniform(0.7, 1.3)))
        lead_months = max(1, math.ceil(lead_days / 30))
        # How generously this item is ordered: some buyers over-order,
        # some cut it fine. The spread is what makes the table worth reading.
        order_months = rng.uniform(0.6, 3.5)
        on_hand = round(rows[0]["units_sold"] * 2)
        pipeline: list[tuple[int, int]] = []     # (arrival index, qty)
        last_received = ""
        for i, row in enumerate(rows):
            for arrival in [a for a in pipeline if a[0] == i]:
                on_hand += arrival[1]
                last_received = row["month"]
            pipeline = [a for a in pipeline if a[0] > i]
            on_hand = max(0, on_hand - row["units_sold"])   # a stockout is a lost sale
            window = [r["units_sold"] for r in rows[max(0, i - 2): i + 1]]
            trailing = sum(window) / len(window)
            daily = trailing / 30
            safety = round(daily * lead_days * 0.5)
            reorder_point = round(daily * lead_days) + safety
            on_order = sum(q for _, q in pipeline)
            if on_hand + on_order <= reorder_point:
                pipeline.append((i + lead_months, max(1, round(trailing * order_months))))
        on_order = sum(q for _, q in pipeline)
        next_arrival = min((a for a, _ in pipeline), default=None)
        calendar = _months(HISTORY_START, HOLDOUT_END)   # arrivals can land after CUTOFF
        stock_rows.append({
            "sku": sku,
            "supplier": names[sku].get("supplier") or "",
            "on_hand": on_hand,
            "on_order": on_order,
            "next_delivery_month": calendar[next_arrival] if next_arrival is not None else None,
            "lead_time_days": lead_days,
            "reorder_point": reorder_point,
            "safety_stock": safety,
            "last_received_month": last_received or None,
            "as_of_month": rows[-1]["month"],
        })
    return stock_rows


def split_prices(price_history: list[dict]) -> tuple[list[dict], list[dict]]:
    cutoff_date = f"{CUTOFF}-01"
    reference = [r for r in price_history if r["order_date"] < cutoff_date]
    quotes = [r for r in price_history if r["order_date"] >= cutoff_date]
    return reference, quotes


def main() -> None:
    for tenant in TENANTS:
        folder = DATA / tenant
        products = json.loads((folder / "products.json").read_text())
        prices = json.loads((folder / "price_history.json").read_text())
        # The products that sell: the SKUs `orders` covers. The rest of
        # the catalogue (3200 rows on Aurora) is Catalog and Matching's
        # territory, and 46 months of it would be ~150k rows of nothing.
        sold = {r["product_id"] for r in json.loads((folder / "orders.json").read_text())}
        products = [p for p in products if p["sku"] in sold]
        history, holdout = generate_demand(tenant, products)
        stock = simulate_stock(tenant, products, history)
        reference, quotes = split_prices(prices)
        for name, rows in (("monthly_demand", history), ("monthly_demand_holdout", holdout),
                           ("stock", stock), ("price_reference", reference),
                           ("price_quotes", quotes)):
            (folder / f"{name}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
        print(f"{tenant}: monthly_demand {len(history)}, holdout {len(holdout)}, "
              f"stock {len(stock)}, price_reference {len(reference)}, price_quotes {len(quotes)}")


if __name__ == "__main__":
    main()

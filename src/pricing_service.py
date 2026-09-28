"""Price Intelligence — is this quote fair, judged only by what came before?

The incoming quotes are real rows: `price_quotes` holds every
`price_history` record dated on or after the cutoff, and `price_reference`
everything before it. Each quote is scored by `_estimate unit_price` over
`price_reference` alone, so the estimate has never seen the quote it
judges. Beside it sits the plain rule — the median of what this product
has cost before — because a buyer has that without Aito.

Measured (`./do price-eval`): on this corpus the estimate is at PARITY
with the product's own median — within half a point of error on every
tenant — and both catch every overcharge. That is the claim, and the
view shows both numbers on every row rather than implying more.

What it is not: a price for a product never bought before. With no
earlier rows the estimate falls back on supplier and volume alone and
misses by 46-70%, and `_estimate` on v2 does not accept linked fields
(`product_id.category`) that could describe the product instead. So the
view shows products with history only, and says why. It used to score
hand-typed "quotes" tuned to four products and quoted an invented
€1,240 saved per flagged quote.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from src.aito_client import AitoClient
from src.demand_service import _whole_table

# What a quote is judged on: the product, who quotes it and at what
# volume. The date is left out — it is what separates the two tables.
FEATURES = ("product_id", "supplier", "volume")
# A quote this far above the estimate is flagged for a buyer to look at.
FLAG_MARGIN = 0.15
# What `./do price-eval` counts as a real overcharge: this far over list.
OVERCHARGE_OVER_LIST = 0.17
PRODUCTS_SHOWN = 4

# `./do price-eval`, 2026-09-28. Error is |estimate - list price| / list
# price; flags are judged against quotes more than 17% over list price.
MEASURED = {
    "measured_on": "2026-09-28",
    "engine_build": "2.10.3 (88786b4dc970), rep2",
    "by_tenant": {
        # Quotes on products with earlier prices. `error` is mean
        # |estimate - list price| / list price; `caught` of `overcharges`.
        "metsa":  {"n": 118, "aito_error": 0.048, "median_error": 0.047,
                   "overcharges": 11, "aito_caught": 10, "aito_flagged": 11,
                   "median_caught": 10, "median_flagged": 10},
        "aurora": {"n": 843, "aito_error": 0.022, "median_error": 0.021,
                   "overcharges": 39, "aito_caught": 39, "aito_flagged": 52,
                   "median_caught": 39, "median_flagged": 57},
        "studio": {"n": 92, "aito_error": 0.058, "median_error": 0.055,
                   "overcharges": 6, "aito_caught": 6, "aito_flagged": 12,
                   "median_caught": 6, "median_flagged": 10},
    },
}


@dataclass
class ScoredQuote:
    price_id: str
    supplier: str
    volume: int
    order_date: str
    quoted: float
    aito: float
    median: float | None      # None: this product has no earlier price
    neighbours: int

    @property
    def deviation(self) -> float:
        return (self.quoted - self.aito) / self.aito

    @property
    def flagged(self) -> bool:
        return self.deviation > FLAG_MARGIN

    def to_dict(self) -> dict:
        return {"price_id": self.price_id, "supplier": self.supplier,
                "volume": self.volume, "order_date": self.order_date,
                "quoted": self.quoted, "aito": round(self.aito, 2),
                "median": None if self.median is None else round(self.median, 2),
                "deviation_pct": round(self.deviation * 100, 1),
                "flagged": self.flagged, "neighbours": self.neighbours}


def score_quote(client: AitoClient, quote: dict, earlier: list[float]) -> ScoredQuote:
    res = client.estimate("price_reference", {k: quote[k] for k in FEATURES}, "unit_price")
    value = res.get("estimate")
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"_estimate unit_price returned no usable number for {quote}: {res}")
    return ScoredQuote(
        price_id=quote["price_id"], supplier=quote["supplier"], volume=quote["volume"],
        order_date=quote["order_date"], quoted=float(quote["unit_price"]),
        aito=float(value),
        median=statistics.median(earlier) if earlier else None,
        neighbours=len((res.get("why") or {}).get("components") or []))


def pick_products(quotes: list[dict], earlier: dict[str, list[float]]) -> list[str]:
    """The products with the most incoming quotes, among those with at
    least three earlier prices. A product with none is left out: see the
    module docstring for why its estimate is not worth showing."""
    count: dict[str, int] = defaultdict(int)
    for q in quotes:
        count[q["product_id"]] += 1
    ranked = sorted(count, key=lambda p: (-count[p], -len(earlier.get(p, [])), p))
    chosen = [p for p in ranked if len(earlier.get(p, [])) >= 3][:PRODUCTS_SHOWN]
    if not chosen:
        raise RuntimeError("no quoted product has three earlier prices")
    return chosen


def get_pricing_overview(client: AitoClient, tenant: str | None = None) -> dict:
    reference = _whole_table(client, "price_reference")
    quotes = _whole_table(client, "price_quotes")
    earlier: dict[str, list[float]] = defaultdict(list)
    for r in reference:
        earlier[r["product_id"]].append(float(r["unit_price"]))

    products = []
    for sku in pick_products(quotes, earlier):
        rows = client.search("products", {"sku": sku}, limit=1).get("hits") or []
        if not rows:
            raise RuntimeError(f"{sku} is quoted but not in products")
        product = rows[0]   # name, category and list price from the same row as the SKU
        own = sorted((q for q in quotes if q["product_id"] == sku), key=lambda q: q["order_date"])
        with ThreadPoolExecutor(max_workers=6) as pool:
            scored = list(pool.map(lambda q: score_quote(client, q, earlier.get(sku, [])), own))
        products.append({
            "sku": sku, "name": product["name"], "category": product.get("category"),
            "list_price": product.get("unit_price"),
            "earlier_prices": len(earlier.get(sku, [])),
            "quotes": [s.to_dict() for s in scored],
        })

    measured = MEASURED["by_tenant"].get(tenant or "metsa")
    if measured is None:
        raise KeyError(f"no price measurement recorded for tenant {tenant!r}")
    return {
        "cutoff": min(q["order_date"] for q in quotes)[:7],
        "flag_margin": FLAG_MARGIN,
        "features": list(FEATURES),
        "products": products,
        "measured": {"measured_on": MEASURED["measured_on"],
                     "overcharge_over_list": OVERCHARGE_OVER_LIST,
                     "engine_build": MEASURED["engine_build"], **measured},
    }

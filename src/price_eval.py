"""`./do price-eval` — does the price estimate beat the product's own median?

Scores every quote in `price_quotes` with `_estimate unit_price` over
`price_reference` (the history before the cutoff, which never contains
the quote), next to the median of that product's earlier prices.

Truth is the catalogue list price (`products.unit_price`): the fixture
draws each price around it, so it is the fair price the quotes deviate
from. A quote more than 17% over list is an overcharge — the fixture's
outliers sit at 20-45% over, ordinary noise at ~8%.

Reported separately for quotes on products WITH earlier prices and
products WITHOUT any, because they are different problems: the first is
a lookup a median handles, the second is the one only an estimate from
comparable products can answer. A blended number would hide both.
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from src.config import TENANT_IDS
from src.demand_service import _whole_table
from src.pricing_service import FLAG_MARGIN, OVERCHARGE_OVER_LIST, score_quote

OVERCHARGE = 1 + OVERCHARGE_OVER_LIST


def evaluate(client, tenant: str) -> dict:
    reference = _whole_table(client, "price_reference")
    quotes = _whole_table(client, "price_quotes")
    listed = {p["sku"]: float(p["unit_price"])
              for p in _whole_table(client, "products") if p.get("unit_price")}
    earlier: dict[str, list[float]] = defaultdict(list)
    for r in reference:
        earlier[r["product_id"]].append(float(r["unit_price"]))
    # Truth is the list price, so a quote on an unpriced product cannot be
    # scored. Say how many that leaves out rather than shrinking n quietly.
    unscored = [q for q in quotes if q["product_id"] not in listed]
    if unscored:
        print(f"{tenant}: {len(unscored)} quotes on products with no list price are not scored")
    quotes = [q for q in quotes if q["product_id"] in listed]

    with ThreadPoolExecutor(max_workers=8) as pool:
        scored = list(pool.map(lambda q: score_quote(client, q, earlier.get(q["product_id"], [])), quotes))

    def summary(pairs: list[tuple[dict, float]]) -> dict:
        if not pairs:
            return {"n": 0}
        err = statistics.mean(abs(p - listed[q["product_id"]]) / listed[q["product_id"]] for q, p in pairs)
        flags = [(float(q["unit_price"]) > p * (1 + FLAG_MARGIN),
                  float(q["unit_price"]) > listed[q["product_id"]] * OVERCHARGE) for q, p in pairs]
        return {"n": len(pairs), "error": round(err, 3),
                "flagged": sum(f for f, _ in flags),
                "right": sum(f and t for f, t in flags),
                "overcharges": sum(t for _, t in flags)}

    warm = [(q, s) for q, s in zip(quotes, scored) if s.median is not None]
    cold = [(q, s) for q, s in zip(quotes, scored) if s.median is None]
    return {
        "tenant": tenant,
        "with_history": {"aito": summary([(q, s.aito) for q, s in warm]),
                         "median": summary([(q, s.median) for q, s in warm])},
        "no_history": {"aito": summary([(q, s.aito) for q, s in cold])},
    }


def main() -> None:
    import src.app as app
    clients = app._build_clients()
    tenants = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--tenant=")]
    for tenant in (tenants or list(TENANT_IDS)):
        r = evaluate(clients[tenant], tenant)
        print(tenant, r)


if __name__ == "__main__":
    main()

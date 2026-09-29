"""`./do crosssell-eval` — does "frequently bought together" discriminate?

For a sample of anchor products, takes the cross-sell list the view
shows and asks how much of it lands in a category the impressions were
generated to favour after the anchor's (the same category, or a declared
cross-category pull such as Fashion -> Beauty). Reported next to what a
list drawn at random from the catalogue would score, and next to the
spread of `$p` across the list — a ranking whose scores are all ~0.74
is not ranking anything.

It also asks the item-level question: does an anchor's list contain
the products it is actually bought with — the three companions
data/generate_impressions.py gives each product? Those are seeded by
SKU, so they are recomputed here from the generator's own function.

Aurora only: it is the one tenant with impressions.
"""

from __future__ import annotations

import random
import statistics
import zlib
from collections import Counter

from src.demand_service import _whole_table
from src.recommendation_service import get_cross_sell


def _companions_fn():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "generate_impressions", Path(__file__).parent.parent / "data" / "generate_impressions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.companions

# Mirrors the affinities data/generate_impressions.py declares. The
# eval states what it checks for rather than importing it, so a change
# to the generator shows up here as a changed score, not a moved goalpost.
RELATED = {
    ("Fashion", "Beauty"), ("Beauty", "Fashion"),
    ("DIY", "Homeware"), ("Homeware", "DIY"),
    ("Groceries", "Household"), ("Household", "Groceries"),
    ("Electronics", "Homeware"),
}
ANCHORS = 40
TOP = 8


def _related(anchor: str, other: str) -> bool:
    return anchor == other or (anchor, other) in RELATED


def evaluate(client) -> dict:
    products = {p["sku"]: p for p in _whole_table(client, "products") if p.get("category")}
    shown = Counter(r["prev_product_id"] for r in _whole_table(client, "impressions")
                    if r.get("prev_product_id"))
    # Anchors people actually browse from: the view is asked about those.
    pool = sorted(s for s, n in shown.items() if s in products)
    anchors = random.Random(zlib.crc32(b"crosssell")).sample(pool, min(ANCHORS, len(pool)))

    catalogue = Counter(p["category"] for p in products.values())
    total = sum(catalogue.values())
    by_cat: dict[str, list[str]] = {}
    for p in sorted(products.values(), key=lambda p: p["sku"]):
        by_cat.setdefault(p["category"], []).append(p["sku"])
    companions = _companions_fn()
    found, possible = 0, 0
    hit, expected, spreads, n = 0, 0.0, [], 0
    for sku in anchors:
        cat = products[sku]["category"]
        items = get_cross_sell(client, sku, limit=TOP)
        if not items:
            raise RuntimeError(f"cross-sell for {sku} is empty")
        hit += sum(_related(cat, i.category) for i in items)
        n += len(items)
        expected += len(items) * sum(c for k, c in catalogue.items() if _related(cat, k)) / total
        spreads.append(max(i.p_click for i in items) - min(i.p_click for i in items))
        truth = set(companions(sku, cat, by_cat))
        found += len(truth & {i.sku for i in items})
        possible += len(truth)
    return {"anchors": len(anchors), "related_share": round(hit / n, 3),
            "random_share": round(expected / n, 3),
            "median_p_spread": round(statistics.median(spreads), 3),
            "companions_in_top": f"{found}/{possible}"}


def main() -> None:
    import src.app as app
    print("aurora", evaluate(app._build_clients()["aurora"]))


if __name__ == "__main__":
    main()

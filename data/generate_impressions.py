"""Aurora's browsing impressions, with a signal a cross-sell can find.

The first generator clicked at 50% and spread 6790 impressions over
5282 distinct anchor -> product pairs, each seen at most twice. So
`_recommend ... goal: {clicked: true}` for one anchor had no evidence
about that anchor, fell back on general popularity, and ranked a glass
set, a drill-bit set and a cheese at ~0.74 after a T-shirt. Measured
(`./do crosssell-eval`): 33.8% of the list in a related category against
28.3% for a random pick, and 6 points of spread between first and last.

This one is built the way shop traffic is, each choice declared here:

  - Clicks are rare. 3% base click-through; more for related items.
  - Popularity is skewed (Zipf). A head of products draws most views,
    so the pairs that matter repeat and carry evidence.
  - Every product has three COMPANIONS — two in its own category, one
    in a related one — that shoppers move to and click far more often.
    That is the item-level "bought together" the view claims to find.
  - The category affinities are the old generator's, unchanged.

Its own RNG, seeded per tenant. `generate_personas.py` still draws the
old walk and discards it, because the tables generated after it read
the same random stream and must not move.

Run after generate_personas: `python data/generate_impressions.py`.
"""

from __future__ import annotations

import json
import random
import zlib
from pathlib import Path

DATA = Path(__file__).parent
N_SESSIONS = 6000
BASE_CTR = 0.03
COMPANION_LIFT = 8.0      # a companion after its anchor: ~24% CTR
SAME_CATEGORY_LIFT = 2.0
RELATED_LIFT = 1.8
PURCHASE_GIVEN_CLICK = 0.2

RELATED = {
    ("Fashion", "Beauty"), ("Beauty", "Fashion"),
    ("DIY", "Homeware"), ("Homeware", "DIY"),
    ("Groceries", "Household"), ("Household", "Groceries"),
    ("Electronics", "Homeware"),
}
SEGMENT_BIAS = {
    "young-urban": {"Fashion": 1.4, "Beauty": 1.5, "Electronics": 1.3},
    "family": {"Groceries": 1.5, "Household": 1.4, "Homeware": 1.3},
    "professional": {"Electronics": 1.4, "DIY": 1.3, "Homeware": 1.1},
}
MONTHS = [f"2025-{m:02d}" for m in range(4, 13)] + [f"2026-{m:02d}" for m in range(1, 4)]


def related_categories(category: str) -> list[str]:
    return sorted(b for a, b in RELATED if a == category)


def companions(sku: str, category: str, by_cat: dict[str, list[str]]) -> list[str]:
    """Three products this one is bought with. Seeded by the SKU alone so
    the eval can recompute them without importing the walk."""
    rng = random.Random(zlib.crc32(f"companions:{sku}".encode()))
    same = [s for s in by_cat[category] if s != sku]
    picks = rng.sample(same, min(2, len(same)))
    others = [s for c in related_categories(category) for s in by_cat.get(c, [])]
    pool = others or [s for s in same if s not in picks]
    if pool:
        picks.append(rng.choice(pool))
    return picks


def generate(tenant: str, products: list[dict]) -> list[dict]:
    rng = random.Random(zlib.crc32(f"{tenant}:impressions".encode()))
    eligible = sorted((p for p in products if p.get("category")), key=lambda p: p["sku"])
    category = {p["sku"]: p["category"] for p in eligible}
    by_cat: dict[str, list[str]] = {}
    for p in eligible:
        by_cat.setdefault(p["category"], []).append(p["sku"])
    skus = [p["sku"] for p in eligible]
    order = skus[:]
    rng.shuffle(order)
    popularity = {sku: 1.0 / (rank + 1) ** 1.1 for rank, sku in enumerate(order)}
    companion = {s: companions(s, category[s], by_cat) for s in skus}

    def popular(pool: list[str]) -> str:
        return rng.choices(pool, weights=[popularity[s] for s in pool], k=1)[0]

    rows = []
    for session in range(N_SESSIONS):
        segment = rng.choice(sorted(SEGMENT_BIAS))
        bias = SEGMENT_BIAS[segment]
        month = rng.choice(MONTHS)
        current = popular(skus)
        prev = None
        for _ in range(rng.randint(3, 6)):
            if prev is not None:
                roll = rng.random()
                cat = category[prev]
                if roll < 0.35:
                    current = rng.choice(companion[prev])
                elif roll < 0.70:
                    current = popular(by_cat[cat])
                elif roll < 0.85 and related_categories(cat):
                    current = popular(by_cat[rng.choice(related_categories(cat))])
                else:
                    current = popular(skus)
            lift = 1.0
            if prev is not None:
                if current in companion[prev]:
                    lift = COMPANION_LIFT
                elif category[current] == category[prev]:
                    lift = SAME_CATEGORY_LIFT
                elif (category[prev], category[current]) in RELATED:
                    lift = RELATED_LIFT
            clicked = rng.random() < BASE_CTR * lift * bias.get(category[current], 1.0)
            rows.append({
                "impression_id": f"IMP-{len(rows) + 1:06d}",
                "session_id": f"S-{session + 1:05d}",
                "customer_segment": segment,
                "product_id": current,
                "prev_product_id": prev,
                "clicked": clicked,
                "purchased": clicked and rng.random() < PURCHASE_GIVEN_CLICK,
                "month": month,
            })
            prev = current
    return rows


def main() -> None:
    folder = DATA / "aurora"
    products = json.loads((folder / "products.json").read_text())
    rows = generate("aurora", products)
    (folder / "impressions.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    ctr = sum(r["clicked"] for r in rows) / len(rows)
    pairs = {(r["prev_product_id"], r["product_id"]) for r in rows if r["prev_product_id"]}
    print(f"aurora: impressions {len(rows)}, click-through {ctr:.1%}, distinct pairs {len(pairs)}")


if __name__ == "__main__":
    main()

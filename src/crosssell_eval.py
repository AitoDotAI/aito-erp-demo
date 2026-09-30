"""`./do crosssell-eval` — does "frequently bought together" find what is?

Every product in `baskets` has three COMPANIONS it is bought with far
more often than chance (data/generate_impressions.py; seeded by SKU, so
recomputed here from the generator's own function). For sampled anchors
this asks how many of their companions make the view's top 8, next to
what plain co-occurrence counting finds on the same baskets.

Reported for well-bought and rarely-bought anchors separately, because
they are different problems: with twenty baskets there is evidence to
rank, with three there is almost none, and one blended number would
hide both. Aurora only: it is the one tenant with baskets.

Measured 2026-09-30 on 2.10.3 (this script, the view's own query):

  well-bought (>= 20 baskets)    view 55/90   counting 57/90
  rarely-bought (3-8 baskets)    view  1/90   counting 18/90

While choosing the query, on an earlier sample: `_relate` lift 62/90
against counting 63/90 on well-bought anchors, and a non-exclusive
`_predict products.$feature` 33/90 — it ranks by "how likely in the
basket", so the store's best-sellers top every list.

Parity with counting where history is thick. On thin anchors the
support floor lists few rows rather than guessing, and counting finds
more; the view says so.
"""

from __future__ import annotations

import random
import zlib
from collections import Counter

from src.demand_service import _whole_table
from src.recommendation_service import get_cross_sell

TOP = 8
ANCHORS = 30
BANDS = (("well-bought (>= 20 baskets)", 20, 10**9), ("rarely-bought (3-8 baskets)", 3, 8))


def _companions_fn():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "generate_impressions", Path(__file__).parent.parent / "data" / "generate_impressions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.companions


def evaluate(client) -> list[dict]:
    products = {p["sku"]: p for p in _whole_table(client, "products") if p.get("category")}
    baskets = [b["products"] for b in _whole_table(client, "baskets")]
    by_cat: dict[str, list[str]] = {}
    for p in sorted(products.values(), key=lambda p: p["sku"]):
        by_cat.setdefault(p["category"], []).append(p["sku"])
    companions = _companions_fn()
    freq = Counter(s for b in baskets for s in b)

    def counted(anchor: str) -> list[str]:
        co = Counter(s for b in baskets if anchor in b for s in b if s != anchor)
        return [s for s, _ in co.most_common(TOP)]

    out = []
    for band, lo, hi in BANDS:
        pool = sorted(s for s, n in freq.items() if lo <= n <= hi)
        anchors = random.Random(zlib.crc32(band.encode())).sample(pool, min(ANCHORS, len(pool)))
        view = counting = 0
        for a in anchors:
            truth = set(companions(a, products[a]["category"], by_cat))
            view += len(truth & {i.sku for i in get_cross_sell(client, a, limit=TOP)})
            counting += len(truth & set(counted(a)))
        out.append({"band": band, "anchors": len(anchors), "possible": 3 * len(anchors),
                    "view": view, "counting": counting})
    return out


def main() -> None:
    import src.app as app
    for r in evaluate(app._build_clients()["aurora"]):
        print(f"aurora {r['band']:28} companions in top {TOP}: view {r['view']}/{r['possible']}"
              f"   counting {r['counting']}/{r['possible']}")


if __name__ == "__main__":
    main()

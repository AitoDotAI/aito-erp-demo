"""Cross-sell + similar-products recommendations — Aurora's flagship view.

Two complementary recommendation patterns from the same data:

  1. **Frequently bought together** — `_relate` over `baskets`: which
     products turn up in baskets that contain this one, and how many
     times more often than in baskets at large (lift), with the basket
     counts behind each ratio. See `get_cross_sell` for why it is not
     goal `_recommend` or a non-exclusive `_predict`.

  2. **Similar products** — for a given product, find products with
     overlapping category + supplier signals via Aito's search ranked
     by attribute overlap. Same idea as Spotify's "similar artists" —
     vector similarity over attributes the database already knows.

Both views also surface a **trending** ribbon: the products in the most
baskets over the last six months.

Why this matters for the demo: this is the most-used Aito capability
in retail (and the one missing from the existing demo). Aurora
prospects (Oscar Software, ERPly) ask for it instinctively.
"""

from dataclasses import dataclass, field

from src.aito_client import AitoClient


@dataclass
class CrossSellItem:
    """A product bought in the same baskets as the anchor, from `_relate`.

    `together` of the `anchor_baskets` that contain the anchor also contain
    this product; `lift` is how many times more often than in baskets at
    large. Counts travel with the ratio so a reader can see what a lift
    rests on — 12x on 82 baskets and 12x on 3 are different claims.
    """
    sku: str
    name: str
    category: str | None
    supplier: str | None
    unit_price: float | None
    lift: float
    together: int
    anchor_baskets: int

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "supplier": self.supplier,
            "unit_price": self.unit_price,
            "lift": self.lift,
            "together": self.together,
            "anchor_baskets": self.anchor_baskets,
        }


@dataclass
class SimilarItem:
    sku: str
    name: str
    category: str | None
    supplier: str | None
    unit_price: float | None
    score: float             # Aito _match score

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "supplier": self.supplier,
            "unit_price": self.unit_price,
            "score": self.score,
        }


@dataclass
class TrendingItem:
    sku: str
    name: str
    category: str | None
    baskets: int
    months: int

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "baskets": self.baskets,
            "months": self.months,
        }


@dataclass
class RecommendationOverview:
    products: list[dict]                 # browsable product catalog (lightweight)
    trending: list[TrendingItem]
    # Per-anchor recommendations are computed lazily on-demand;
    # the overview only surfaces enough to populate the picker.

    def to_dict(self) -> dict:
        return {
            "products": self.products,
            "trending": [t.to_dict() for t in self.trending],
        }


# ── Helpers ─────────────────────────────────────────────────────────


def _fetch_product(client: AitoClient, sku: str) -> dict | None:
    hits = _safe_search(client, "products", {"sku": sku}, 1)
    return hits[0] if hits else None


def _safe_search(client: AitoClient, table: str, where: dict, limit: int) -> list[dict]:
    """Search a table; return [] if it isn't loaded on this tenant."""
    from src.aito_client import AitoError
    try:
        return client.search(table, where, limit=limit).get("hits") or []
    except AitoError as exc:
        if exc.status_code == 400 and f"failed to open '{table}'" in str(exc):
            return []
        raise


# ── Public API ──────────────────────────────────────────────────────


def get_overview(client: AitoClient, top_n_products: int = 60) -> RecommendationOverview:
    """Build the recommendations landing data: a browsable product set
    plus a trending ribbon."""
    # The picker offers the products people actually buy — the most
    # frequent in `baskets` — because cross-sell for a product nobody
    # buys is an empty list. It used to be the first 60 catalogue rows
    # in SKU order, and the default anchor had no baskets at all.
    from collections import Counter
    from src.demand_service import _whole_table
    basket_rows = _whole_table(client, "baskets")
    bought = Counter(s for b in basket_rows for s in b["products"])
    catalogue = {p["sku"]: p for p in _whole_table(client, "products")}
    products = []
    for sku, _ in sorted(bought.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n_products]:
        p = catalogue.get(sku)
        if p is None:
            raise RuntimeError(f"{sku} is in baskets but not in products")
        products.append({
            "sku": sku,
            "name": p["name"],
            "category": p.get("category"),
            "supplier": p.get("supplier"),
            "unit_price": p.get("unit_price"),
        })

    # Trending: the products in the most baskets over the last six
    # months — the same baskets cross-sell reads, so every chip opens a
    # list. It was units from `orders`, which is uniform noise, and most
    # of its products had no baskets at all.
    months = sorted({b["month"] for b in basket_rows})[-6:]
    recent = [b for b in basket_rows if b["month"] in months]
    in_baskets = Counter(s for b in recent for s in b["products"])
    months_seen: dict[str, set] = {}
    for b in recent:
        for sku in b["products"]:
            months_seen.setdefault(sku, set()).add(b["month"])
    trending_items: list[TrendingItem] = []
    for sku, n in sorted(in_baskets.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
        p = catalogue.get(sku)
        if p is None:
            raise RuntimeError(f"{sku} is in baskets but not in products")
        trending_items.append(TrendingItem(
            sku=sku, name=p["name"], category=p.get("category"),
            baskets=n, months=len(months_seen[sku]),
        ))

    return RecommendationOverview(products=products, trending=trending_items)


# Fewer shared baskets than this and a lift is one or two coincidences.
MIN_TOGETHER = 3
# `_relate` answers in lift order; ask for enough that the support filter
# still leaves a full list for a well-bought anchor.
RELATE_LIMIT = 60


def get_cross_sell(
    client: AitoClient,
    product_id: str,
    limit: int = 8,
    customer_segment: str | None = None,
) -> list[CrossSellItem]:
    """Products bought together with `product_id`, ranked by lift.

    One `_relate` over `baskets`: the condition is "the basket contains
    the anchor", the related field is the basket's other products. It
    replaced goal `_recommend` over impressions, which ranked products
    seen once or twice anywhere above ones bought with the anchor
    hundreds of times (aito-core#1525), and a non-exclusive `_predict
    products.$feature`, which answers "how likely is X in this basket"
    and so fills every list with the store's best-sellers. Lift asks the
    cross-sell question: how much MORE likely, given the anchor.

    Measured (`./do crosssell-eval`): on well-bought anchors it finds the
    products each is co-bought with as often as counting co-occurrences
    does — parity, not better. On rarely-bought anchors the support floor
    leaves few rows, and the view shows few rather than guessing.
    """
    where: dict = {"products": {"$has": product_id}}
    if customer_segment:
        where["customer_segment"] = customer_segment

    response = client.relate("baskets", where, "products", limit=RELATE_LIMIT)

    ranked = []
    for hit in response.get("hits", []):
        sku = hit["related"]["products"]
        if sku == product_id:
            continue   # the anchor relates to itself perfectly and says nothing
        fs = hit["fs"]
        if fs["fOnCondition"] < MIN_TOGETHER:
            continue
        ranked.append((hit["lift"], sku, int(fs["fOnCondition"]), int(fs["fCondition"])))
    ranked.sort(key=lambda r: (-r[0], r[1]))

    items: list[CrossSellItem] = []
    for lift, sku, together, anchor_baskets in ranked[:limit]:
        rows = client.search("products", {"sku": sku}, limit=1).get("hits") or []
        if not rows:
            raise RuntimeError(f"{sku} is in baskets but not in products")
        p = rows[0]
        items.append(CrossSellItem(
            sku=sku, name=p["name"], category=p.get("category"),
            supplier=p.get("supplier"), unit_price=p.get("unit_price"),
            lift=round(float(lift), 2), together=together,
            anchor_baskets=anchor_baskets,
        ))
    return items


def get_similar(client: AitoClient, product_id: str, limit: int = 8) -> list[SimilarItem]:
    """Find products similar to `product_id` along category + supplier
    + price-band signal. Uses Aito's `_search` ranked by attribute
    overlap — same idea as `_match` but explicit about the signals.
    """
    target = _fetch_product(client, product_id)
    if not target:
        return []

    cat = target.get("category")
    sup = target.get("supplier")
    if not cat:
        return []

    # Same category — primary candidates.
    response = client.search("products", {"category": cat}, limit=40)
    candidates = response.get("hits") or []

    # Score by signal overlap; price proximity adds soft signal.
    target_price = target.get("unit_price") or 0
    items: list[SimilarItem] = []
    for c in candidates:
        if c.get("sku") == product_id:
            continue
        score = 0.5  # same category baseline
        if sup and c.get("supplier") == sup:
            score += 0.3
        cprice = c.get("unit_price")
        if cprice and target_price:
            ratio = min(cprice, target_price) / max(cprice, target_price)
            score += 0.2 * ratio  # price-band proximity
        items.append(SimilarItem(
            sku=c["sku"],
            name=c.get("name") or c["sku"],
            category=c.get("category"),
            supplier=c.get("supplier"),
            unit_price=cprice,
            score=round(score, 3),
        ))
    items.sort(key=lambda i: -i.score)
    return items[:limit]

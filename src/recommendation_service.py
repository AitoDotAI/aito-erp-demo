"""Cross-sell + similar-products recommendations — Aurora's flagship view.

Two complementary recommendation patterns from the same data:

  1. **Frequently bought together** — `_recommend` against the
     `impressions` table with `goal: {clicked: true}`. For each
     candidate `product_id`, Aito ranks by the predicted probability
     that the impression would be clicked given `prev_product_id`
     (and optionally `customer_segment`). This is the same operator
     pattern that powers help-article CTR ranking — see
     `aito-accounting-demo/.ai/guides/07-recommend-with-goal-driven-ranking.md`.

     We use **linked select** (`product_id.name`, `product_id.category`,
     etc.) so one call returns the full product row to render — no
     separate `_search` to fetch names.

  2. **Similar products** — for a given product, find products with
     overlapping category + supplier signals via Aito's search ranked
     by attribute overlap. Same idea as Spotify's "similar artists" —
     vector similarity over attributes the database already knows.

Both views also surface a **trending** ribbon: top products ranked by
recent units sold, derived from the orders table.

Why this matters for the demo: this is the most-used Aito capability
in retail (and the one missing from the existing demo). Aurora
prospects (Oscar Software, ERPly) ask for it instinctively.
"""

from dataclasses import dataclass, field

from src.aito_client import AitoClient


@dataclass
class CrossSellItem:
    sku: str
    name: str
    category: str | None
    supplier: str | None
    unit_price: float | None
    p_click: float           # P(clicked | prev_product_id, ...) from Aito _recommend
    score: float             # alias for p_click — kept for UI back-compat

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "supplier": self.supplier,
            "unit_price": self.unit_price,
            "p_click": self.p_click,
            "score": self.score,
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
    units_sold: int
    months: int

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "units_sold": self.units_sold,
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
    # Pull a slice of the product catalog with category populated — these
    # populate the picker. Skipping incomplete rows keeps the picker
    # tidy; the catalog view already handles those.
    products = [
        {
            "sku": p.get("sku"),
            "name": p.get("name"),
            "category": p.get("category"),
            "supplier": p.get("supplier"),
            "unit_price": p.get("unit_price"),
        }
        for p in _safe_search(client, "products", {}, top_n_products)
        if p.get("category")
    ]

    # Trending: aggregate orders client-side. Aito _search returns rows;
    # we sum units per product. Filter to the most recent ~6 months for
    # a "what's hot now" framing.
    orders = _safe_search(client, "orders", {}, 2000)
    recent_months = sorted({o["month"] for o in orders})[-6:]
    by_sku: dict[str, dict] = {}
    for o in orders:
        if o["month"] not in recent_months:
            continue
        sku = o["product_id"]
        rec = by_sku.setdefault(sku, {"units": 0, "months": set()})
        rec["units"] += int(o.get("units_sold") or 0)
        rec["months"].add(o["month"])

    # Resolve names via the catalog we already have.
    name_lookup = {p["sku"]: p for p in products}
    trending_items: list[TrendingItem] = []
    for sku, rec in sorted(by_sku.items(), key=lambda kv: -kv[1]["units"])[:15]:
        prod = name_lookup.get(sku)
        if not prod:
            # Fallback for SKUs not in the slice we pulled — fetch directly.
            full = _fetch_product(client, sku)
            if not full:
                continue
            prod = {"name": full.get("name"), "category": full.get("category")}
        trending_items.append(TrendingItem(
            sku=sku,
            name=prod.get("name") or sku,
            category=prod.get("category"),
            units_sold=rec["units"],
            months=len(rec["months"]),
        ))

    return RecommendationOverview(products=products, trending=trending_items)


def get_cross_sell(
    client: AitoClient,
    product_id: str,
    limit: int = 8,
    customer_segment: str | None = None,
) -> list[CrossSellItem]:
    """Rank products by P(click | prev_product = `product_id`).

    One `_recommend` call. Linked-`select` returns the full product
    row so we don't need a follow-up `_search`. Optional
    `customer_segment` adds personalisation without changing the
    query shape — same operator, one extra `where` constraint.
    """
    where: dict = {"prev_product_id": product_id}
    if customer_segment:
        where["customer_segment"] = customer_segment

    try:
        # No explicit select: Aito traverses the link automatically and
        # returns every column from the linked `products` row on each
        # hit. One call, full payload — no follow-up `_search` to
        # resolve names. (See aito-accounting-demo guide 01.)
        response = client.recommend(
            table="impressions",
            where=where,
            recommend_field="product_id",
            goal={"clicked": True},
            limit=limit + 4,   # over-fetch in case the anchor itself appears
        )
    except Exception:
        return []

    items: list[CrossSellItem] = []
    for hit in response.get("hits", []):
        sku = hit.get("sku")
        if not sku or sku == product_id:
            # Skip the anchor — recommending a product against itself
            # is a trivially correct but useless answer.
            continue
        items.append(CrossSellItem(
            sku=sku,
            name=hit.get("name") or sku,
            category=hit.get("category"),
            supplier=hit.get("supplier"),
            unit_price=hit.get("unit_price"),
            p_click=round(float(hit.get("$p") or 0), 3),
            score=round(float(hit.get("$p") or 0), 3),
        ))
        if len(items) >= limit:
            break
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

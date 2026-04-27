"""Cross-sell + similar-products recommendations — Aurora's flagship view.

Two complementary recommendation patterns from the same data:

  1. **Frequently bought together** — for a given product, find products
     that are ordered in the same months. Aggregates `_search` over the
     `orders` table; weights by units co-purchased. This is the
     "customers who bought X also bought Y" pattern that drives
     basket-size lift in retail.

  2. **Similar products** — for a given product, find products with
     overlapping category + supplier signals via Aito's `_match` query
     against the `products` table. Same idea as Spotify's "similar
     artists" — vector similarity over attributes the database already
     knows.

Both views also surface a **trending** ribbon: top products ranked by
recent units sold, derived from the same orders table.

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
    co_units: int            # how many units co-occurred across shared months
    months_overlap: int      # how many months the two were ordered together
    lift: float              # co-units / baseline (rough confidence signal)

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "supplier": self.supplier,
            "unit_price": self.unit_price,
            "co_units": self.co_units,
            "months_overlap": self.months_overlap,
            "lift": self.lift,
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


def _fetch_orders_for(client: AitoClient, product_id: str, limit: int = 300) -> list[dict]:
    return _safe_search(client, "orders", {"product_id": product_id}, limit)


def _fetch_orders_in_month(client: AitoClient, month: str, limit: int = 300) -> list[dict]:
    return _safe_search(client, "orders", {"month": month}, limit)


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


def get_cross_sell(client: AitoClient, product_id: str, limit: int = 8) -> list[CrossSellItem]:
    """Find products co-purchased with `product_id` across the order
    history. Co-purchase is approximated by month-level co-occurrence
    (we don't have basket ids in the fixture data — production data
    with a `basket_id` column would slot in directly).
    """
    target_orders = _fetch_orders_for(client, product_id, limit=300)
    if not target_orders:
        return []

    target_months = {o["month"] for o in target_orders}
    target_units = sum(int(o.get("units_sold") or 0) for o in target_orders)

    # Aggregate co-purchases across each shared month.
    co_units: dict[str, int] = {}
    co_months: dict[str, set[str]] = {}
    for month in target_months:
        for o in _fetch_orders_in_month(client, month, limit=300):
            other = o.get("product_id")
            if not other or other == product_id:
                continue
            co_units[other] = co_units.get(other, 0) + int(o.get("units_sold") or 0)
            co_months.setdefault(other, set()).add(month)

    if not co_units:
        return []

    # Lift baseline = how many units this co-product would have sold
    # without the month filter. Approximation: total units / number of
    # candidate products. Crude but explainable.
    baseline_units = max(1, sum(co_units.values()) / len(co_units))

    ranked = sorted(co_units.items(), key=lambda kv: -kv[1])[:limit]
    items: list[CrossSellItem] = []
    for sku, units in ranked:
        prod = _fetch_product(client, sku)
        if not prod:
            continue
        items.append(CrossSellItem(
            sku=sku,
            name=prod.get("name") or sku,
            category=prod.get("category"),
            supplier=prod.get("supplier"),
            unit_price=prod.get("unit_price"),
            co_units=units,
            months_overlap=len(co_months.get(sku, set())),
            lift=units / baseline_units,
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

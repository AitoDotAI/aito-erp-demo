# Use case 14 — Recommendations *(Aurora-only)*

> Cross-sell + similar-products from the same Aito DB. Aito's flagship
> retail capability.

![Recommendations](../../screenshots/13-recommendations.png)

## What it does

For any anchor product in the catalogue, two complementary
recommendation views update side by side:

- **Frequently bought together (cross-sell)** — products that appear
  in the same months as the anchor. Returns lift relative to baseline,
  number of co-occurring units, and the count of months overlap.
  These are *complements* — increase basket size.
- **Similar products** — products that share category, supplier, and
  price band. These are *substitutes* — useful for stockout fallbacks
  and "see also" panels.

A trending ribbon at the top quick-picks anchors based on units sold
across the last 6 months. Clicking any result row promotes that SKU
to the new anchor — recursive browsing.

## Aito queries

### Cross-sell (basket co-occurrence)

```json
POST /api/v1/_search
{
  "from": "orders",
  "where": { "product_id": "SKU-1234" },
  "limit": 300
}
```

The service walks the months returned, fetches all other products
ordered in those same months via more `_search` calls, and aggregates
co-occurrence units client-side. Production data with a `basket_id`
column on orders would slot in directly: a single `_recommend` call
replaces the aggregation.

### Similar products (attribute overlap)

```json
POST /api/v1/_search
{
  "from": "products",
  "where": { "category": "Beauty" },
  "limit": 40
}
```

Filtered by the anchor's category; scored client-side by supplier match
+ price-band proximity. The same idea as `_match` but with explicit
weighting of which signals matter — the demo prefers transparent
scoring over black-box similarity here.

## Schema

Uses `products` and `orders` (linked via `orders.product_id →
products.sku`). No additional schema.

## Tradeoffs / honest notes

- **Month-level co-occurrence ≠ basket co-occurrence**. Without a
  basket id, two products "co-occur" if they were ordered in the same
  calendar month — which is a loose proxy. Real basket data tightens
  the lift signal substantially.
- **Lift baseline is approximate**: we approximate baseline as
  "average sales of any candidate product in the shared months".
  Crude but explainable. Production-grade lift would compare to the
  product's overall monthly sales rate.
- **Aurora-only**: the view is hidden on Metsä and Studio because
  their `orders` and `products` tables are sparse (Studio has 80
  products, 240 orders — too thin for credible recommendations).

## Why retail buyers care

Recommendations are the Aito capability with the most direct revenue
attribution: cross-sell drives basket size, similar-products covers
stockouts. Aito's grocery demo (demo.aito.ai) leans on this. A retail
prospect reading the Predictive ERP demo without a recommendations
view notices the gap.

## Implementation

[`src/recommendation_service.py`](../../src/recommendation_service.py)
— `get_overview()` (catalogue + trending), `get_cross_sell()`
(co-occurrence aggregation), `get_similar()` (attribute scoring).
Each result type degrades gracefully to `[]` when the underlying
table isn't loaded for the active tenant.

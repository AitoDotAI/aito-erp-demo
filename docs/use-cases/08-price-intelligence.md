# Price Intelligence — Fair-price band + PPV

![Price Intelligence](../../screenshots/08-pricing.png)

*Wärtsilä Seal Kit fair price €147 (mean over 24-month history,
±1.5σ band); Parts Direct quotes €189, +28.9% — flagged as
overpriced; Purchase Price Variance dashboard tracks annualized
exposure*

## Overview

Procurement quotes vary 5–40% across suppliers for the same SKU
without anyone tracking why. Price Intelligence builds a fair-price
band per product from `price_history`, scores incoming quotes
against the band, and flags anything more than 20% above the
estimated price.

This view doesn't use `_predict` or `_relate`. It's plain `_search`
with statistical aggregation client-side: mean, standard deviation,
1.5σ confidence band. Over the demo's 2,913 price-history records,
that produces tight bands for high-volume SKUs and wide bands for
low-volume ones — and the confidence score reflects the sample
size honestly.

## How it works

### Traditional vs. AI-powered price validation

**Traditional:**
- "Last paid" price stored on the master record
- Quote validation = compare to last paid
- One outlier purchase poisons the next 12 months
- No σ awareness — €100 ± €5 looks the same as €100 ± €40

**With Aito:**
- Full price history per (product, supplier) pair
- Band is mean ± 1.5σ — 87% of historical prices fall inside
- Confidence scales with sample size (`n ≥ 20 → 0.95`)
- PPV (Purchase Price Variance) is annualized exposure across all
  flagged quotes

### Implementation

The pricing service in `src/pricing_service.py` aggregates history
into a band and scores quotes against it:

```python
def estimate_price(
    client: AitoClient,
    product_id: str,
    supplier: str | None = None,
    volume: int | None = None,
) -> PriceEstimate:
    """Estimate price for a product based on historical price data."""
    where: dict = {"product_id": product_id}
    if supplier:
        where["supplier"] = supplier

    result = client.search("price_history", where, limit=100)
    hits = result.get("hits", [])
    prices = [h.get("unit_price", 0) for h in hits if h.get("unit_price")]

    if not prices:
        return PriceEstimate(...sample_size=0, confidence=0.0, ...)

    mean = sum(prices) / len(prices)
    variance = sum((p - mean) ** 2 for p in prices) / len(prices) if len(prices) > 1 else 0
    std = math.sqrt(variance)

    range_low = max(0, mean - 1.5 * std)
    range_high = mean + 1.5 * std

    return PriceEstimate(
        product_id=product_id,
        estimated_price=round(mean, 2),
        price_min=round(min(prices), 2),
        price_max=round(max(prices), 2),
        range_low=round(range_low, 2),
        range_high=round(range_high, 2),
        sample_size=len(prices),
        confidence=_compute_confidence(len(prices)),
        std_dev=round(std, 2),
    )


def score_quotes(estimate: PriceEstimate, quotes: list[dict]) -> list[QuoteScore]:
    """Compare incoming quotes against the price estimate."""
    scores = []
    for quote in quotes:
        deviation = (quote["quoted_price"] - estimate.estimated_price) / estimate.estimated_price
        flagged = deviation > QUOTE_FLAG_THRESHOLD          # 0.20

        if deviation <= 0:                  verdict = "good"
        elif deviation <= QUOTE_FLAG_THRESHOLD: verdict = "acceptable"
        else:                                verdict = "overpriced"

        scores.append(QuoteScore(
            supplier=quote["supplier"],
            quoted_price=quote["quoted_price"],
            estimated_price=estimate.estimated_price,
            deviation_pct=round(deviation * 100, 1),
            flagged=flagged,
            verdict=verdict,
        ))
    return sorted(scores, key=lambda s: s.deviation_pct)
```

The `_search` query:

```json
{
  "from": "price_history",
  "where": {
    "product_id": "SKU-4421",
    "supplier": "Wärtsilä Components"
  },
  "limit": 100
}
```

Aggregation happens client-side. Aito returns the rows; Python
computes mean, σ, and the band.

## Key features

### 1. Sample-size-aware confidence
`_compute_confidence` is a step function: 20+ samples → 0.95,
10+ → 0.85, 5+ → 0.70, fewer → linear ramp. A SKU with 3 historical
quotes shows a band but the confidence pill stays orange — the
user knows not to bet the farm on it.

### 2. PPV (Purchase Price Variance) dashboard
Per-product PPV = `(avg_quoted − estimate) / estimate × 100`.
Aggregated across the demo set, the PPV summary shows total
overpayment in EUR for flagged quotes, total savings (negative
deviations on accepted quotes), and an annualized projection
assuming ~10 orders per year per flagged item.

### 3. ±1.5σ band, not min/max
The min/max columns are also surfaced (price_min, price_max) but
the visual band is mean ±1.5σ. One historical outlier shouldn't
widen the band to absurdity — 1.5σ covers 87% of normal data.

### 4. 20% flag threshold, opinionated
`QUOTE_FLAG_THRESHOLD = 0.20` is a single tunable. We picked 20%
because below that suppliers genuinely vary; above that, somebody
needs to look. Easy to make per-category later (commodities tighter,
specialised parts looser).

## Data schema

```json
{
  "price_history": {
    "type": "table",
    "columns": {
      "product_id": { "type": "String" },
      "supplier":   { "type": "String" },
      "unit_price": { "type": "Decimal"},
      "quote_date": { "type": "String" },
      "volume":     { "type": "Decimal"}
    },
    "links": [
      { "from": "product_id", "to": "products.sku" }
    ]
  }
}
```

`price_history` links to `products.sku` so a product page can show
its quote history without a join in the application layer.

## Tradeoffs and gotchas

- **No volume curve modelling**: a quote for 1,000 units is rarely
  the same per-unit as a quote for 10. We accept the
  `volume` parameter but don't filter on it — too few records per
  (product, supplier, volume) triple. A real implementation would
  fit a discount curve.
- **`unit_price` is `Decimal` in the schema**; Aito returns it as
  a Python number. We don't convert to `Decimal` for the
  arithmetic — float is fine for ±1.5σ, would matter for cents-level
  invoicing.
- **No outlier rejection**: a single typo'd €1 quote drags the
  mean. We could trim the top/bottom 10% but for the demo size
  (~30 records per SKU on the busy side) trimming costs more than
  it gains.
- **`limit=100` is the per-product hard cap**. SKUs with more
  history than that get a truncated band. Acceptable for the demo;
  in production you'd page or aggregate server-side.
- **Quote scoring is one-sided**: `flagged` is set only on
  *high* deviations, not low ones. A €50 quote against a €147
  fair-price is "good" — but it's also suspicious (dumping?
  counterfeit? typo?). We surface verdict="good" and let the
  reviewer decide.

## What this demo abstracts away

- **Currency normalization**. All prices are EUR. Production
  catalog data crosses currencies — fair-price requires FX-rate
  normalization to a base currency at order date, not query date,
  or the band moves when the EUR/USD rate moves.
- **Volume-band breaks**. Bulk pricing is non-linear: 1, 10, 100,
  1000 units have step-changes in unit price. The demo computes a
  single fair-price band ignoring volume. Production groups
  `price_history` by volume bucket and surfaces a per-bucket band.
- **Contract-price overrides**. Negotiated prices that should *not*
  trigger PPV alerts (master service agreement says €150/unit for
  the year, regardless of market drift). The demo flags any
  deviation; production reads a `supplier_contracts` table and
  excludes contract-priced lines from PPV calculation.

## Try it live

[**Open Price Intelligence**](http://localhost:8400/pricing/) and
toggle between the demo SKUs to see how confidence and band width
move with sample size.

```bash
./do dev   # starts backend + frontend
```

# Demand Forecast — Seasonal patterns from order history

![Demand Forecast](../../screenshots/09-demand.png)

*SKU-2234 Lindström workwear forecast for August: baseline 6
units/month, seasonal lift 2.33× (every prior August spiked), final
forecast 14 units — confidence 0.85 over 3 same-month samples*

## Overview

Demand forecasting in most ERPs is a flat moving average. That
misses the obvious: workwear orders spike in August (back-to-shift),
fuel orders dip in July (factory shutdown), maintenance orders peak
in March and September (changeovers). The data has the seasonality;
the forecast doesn't use it.

This view computes a **same-month historical average** for each
SKU and folds it into the baseline as a seasonal lift factor. It
also tries Aito's `_predict` on `units_sold` for the target month;
if Aito returns a high-confidence answer, we blend the two 50/50.
Confidence is a function of how many same-month samples exist —
2 prior Augusts → 0.70, 3+ → 0.85.

## How it works

### Traditional vs. AI-powered demand forecast

**Traditional:**
- Trailing 6-month moving average
- Misses calendar seasonality entirely
- One number per SKU, no confidence
- "Run the planning report" once a month

**With Aito:**
- Same-month historical average captures yearly patterns
- Optional `_predict` blend when Aito has high confidence
- Sample-size-aware confidence (3+ same-month → 0.85)
- Aggregate impact metric: stockouts prevented + excess avoided

### Implementation

The demand service in `src/demand_service.py` builds the seasonal
estimate first, then optionally blends with Aito:

```python
def forecast_demand(
    client: AitoClient,
    product_id: str,
    month: str,
) -> DemandForecast:
    """Forecast demand for a product in a given month."""
    # 1. Pull history
    result = client.search("orders", {"product_id": product_id}, limit=200)
    hits = result.get("hits", [])

    monthly: dict[str, int] = {}
    for order in hits:
        m = order.get("month", "")
        units = order.get("units_sold", 0)
        monthly[m] = monthly.get(m, 0) + units

    history = [{"month": m, "units": u} for m, u in sorted(monthly.items())]
    history_values = [h["units"] for h in history]
    baseline = sum(history_values) / len(history_values) if history_values else 0

    # 2. Same-month seasonality — captures August spike, July dip, etc.
    target_month_suffix = month.split("-")[1] if "-" in month else ""
    seasonal_values = [
        h["units"] for h in history
        if h["month"].split("-")[1] == target_month_suffix
    ]
    seasonal_avg = sum(seasonal_values) / len(seasonal_values) if seasonal_values else baseline
    seasonal_lift = (seasonal_avg / baseline) if baseline > 0 else 1.0
    forecast_value = baseline * seasonal_lift

    # 3. Confidence based on same-month sample size
    sample_size = len(seasonal_values)
    if sample_size >= 3:   confidence = 0.85
    elif sample_size >= 2: confidence = 0.70
    elif sample_size >= 1: confidence = 0.55
    else:                  confidence = 0.40; forecast_value = baseline

    # 4. Optional Aito _predict blend (only when high confidence)
    try:
        pred_result = client.predict(
            "orders",
            {"product_id": product_id, "month": month},
            "units_sold",
        )
        pred_hits = pred_result.get("hits", [])
        if pred_hits and pred_hits[0].get("$p", 0.0) > 0.30:
            top = pred_hits[0]
            predicted = top.get("feature", 0)
            if isinstance(predicted, (int, float)) and predicted > 0:
                forecast_value = 0.5 * forecast_value + 0.5 * float(predicted)
                confidence = max(confidence, top.get("$p", 0.0))
    except Exception:
        pass

    return DemandForecast(
        product_id=product_id,
        month=month,
        baseline=round(baseline, 1),
        forecast=round(forecast_value, 1),
        trend=trend,
        confidence=round(confidence, 3),
        history=history,
    )
```

The `_predict` query (when Aito has enough signal):

```json
{
  "from": "orders",
  "where": { "product_id": "SKU-2234", "month": "2025-08" },
  "predict": "units_sold",
  "select": [
    "$p",
    "feature",
    { "$why": { "highlight": { "posPreTag": "«", "posPostTag": "»" } } }
  ],
  "limit": 10
}
```

## Key features

### 1. Same-month historical seasonality
The single most useful pattern in real demand data is "what
happened in this same month last year". Workwear in August lifts
2.3×, fuel in July dips to 0.65×, maintenance in March/September
peaks at 1.7×. The data has the pattern — the forecast just has to
look.

### 2. Aito blend, gated by confidence
If `_predict` returns a hit with `$p > 0.30`, we blend it 50/50
with the seasonal estimate. Below 0.30 we ignore Aito — most
`units_sold` predictions are too diffuse to help (orders are
numeric, sparse across the value space). The seasonal estimate
alone wins on accuracy in those cases.

### 3. Aggregate impact in EUR
The view headline includes
`stockouts_prevented_eur + excess_prevented_eur`: each correctly
predicted spike is assumed to prevent one €800 stockout (lost
margin + expedite shipping); each correctly predicted drop
prevents one €400 carrying-cost event. Calibrated for SMB scale;
the assumption is in the code, not buried.

### 4. Trend recomputed from forecast vs. baseline
We compute trend twice: once from history (recent 3 months vs.
prior 3), once from forecast vs. baseline. The forecast-based one
wins because that's what the user cares about — "will next month
be higher or lower than my running average?"

## Data schema

```json
{
  "orders": {
    "type": "table",
    "columns": {
      "order_id":   { "type": "String" },
      "product_id": { "type": "String" },
      "month":      { "type": "String" },
      "units_sold": { "type": "Int"    },
      "channel":    { "type": "String" }
    },
    "links": [
      { "from": "product_id", "to": "products.sku" }
    ]
  }
}
```

`month` is `String` (not `Date`) — Aito's `_predict` works on
categorical strings cleanly, and we slice the suffix in Python for
the seasonal grouping.

## Tradeoffs and gotchas

- **Numeric `_predict` is fragile**: `units_sold` is `Int`, so
  Aito's `_predict` returns *exact integer values* ranked by
  probability. For low-volume SKUs this is fine (top hit "8" at
  31% does mean something); for high-volume it's noise. The
  `$p > 0.30` gate is a heuristic, not a principle.
- **No multi-year detection**: if your history starts in 2024 and
  you're forecasting August 2025, you have **one** prior August.
  Confidence pegs at 0.55. The view says so honestly; some
  competitors silently hide low-sample forecasts.
- **Aito blend weight is fixed at 50/50**: a smarter version
  would weight by relative confidence. We tried it; the math
  worked but the explanation got hard. Picked simplicity.
- **Same-month logic is naive**: it doesn't know that 2024-12-25
  was a Thursday and 2025-12-25 is a Friday. For ERP purposes the
  monthly granularity hides the day-of-week effect, which is
  fine — but if you want weekly forecasts, this approach breaks
  down.
- **Impact estimate is calibration**, not measurement. The €800
  per prevented stockout figure comes from a single conversation
  with one procurement manager. Sensitivity analysis is on the
  TODO list.

## What this demo abstracts away

- **External signal injection**. The demo reasons only from
  internal order history. Real forecasting blends weather, marketing
  calendar (campaign launches drive August workwear), school year,
  bank holidays, even macro indicators (purchasing managers' index).
  Each becomes an additional column on `orders` and `_predict` picks
  up the lift; the architecture is unchanged.
- **Daily / weekly granularity**. The demo's monthly bucket hides
  day-of-week effects (workwear orders on Mondays, fuel cards mid-
  week). Production forecasts at weekly-or-finer granularity; the
  same-month aggregation logic generalizes but the seasonal lift
  computation needs more samples to be stable.
- **Multi-location splits**. One forecast per SKU. Real chain
  retailers want per-store / per-warehouse forecasts; the demo's
  `where: { product_id, month }` becomes
  `where: { product_id, month, location_id }` with sample-size
  guards on the long tail.

## Try it live

[**Open Demand Forecast**](http://localhost:8400/demand/) and step
through the SKUs. The history sparkline shows the recurring
seasonal pattern.

```bash
./do dev   # starts backend + frontend
```

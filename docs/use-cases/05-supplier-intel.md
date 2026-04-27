# Supplier Intel — Risk discovery via _relate

![Supplier Intel](../../screenshots/05-supplier.png)

*Spend leaderboard plus delivery-risk discovery — Neste lifts 1.4×
on Q4 lateness, Elenia 2.6× on winter outages, all from `_relate`*

## Overview

Supplier intelligence is two questions in one view: **how much do we
spend with each supplier**, and **which suppliers are
disproportionately late**. The first is plain aggregation. The
second is exactly what Aito's `_relate` operator was built for:
"given `delivery_late=True`, which supplier values lift the
probability the most?"

`_relate` returns supplier names ranked by lift, with the support
counts (`fs.f`, `fs.fOnCondition`) and conditional probability
(`ps.pOnCondition`) attached. We classify each by lift × late-rate
into high/medium/low risk and render alongside the spend
leaderboard.

## How it works

### Traditional vs. AI-powered supplier risk

**Traditional:**
- Compute on-time delivery rate per supplier in a BI tool
- Set a threshold ("anyone below 85% is on watch")
- Re-run quarterly, attach to a dashboard nobody opens
- No measure of significance — a supplier with 2 late deliveries
  out of 3 looks worse than one with 50 out of 200

**With Aito:**
- One `_relate` call: "find values of `supplier` that correlate
  with `delivery_late=True`"
- Returns lift (multiplicative effect) and support (sample size)
- Ranks by lift, filters by support — small samples don't dominate
- Lift × late-rate produces a defensible risk classification

### Implementation

The supplier service in `src/supplier_service.py` runs `_relate`
and unpacks the statistics:

```python
def get_delivery_risk(client: AitoClient) -> list[DeliveryRisk]:
    """Use _relate to find suppliers with high late delivery rates."""
    result = client.relate(
        "purchases",
        {"delivery_late": True},
        "supplier",
    )
    hits = result.get("hits", [])

    risks = []
    for hit in hits:
        related = hit.get("related", {})
        supplier_info = related.get("supplier", {})
        supplier_name = (supplier_info.get("$has", "")
                         if isinstance(supplier_info, dict)
                         else str(supplier_info))
        if not supplier_name:
            continue

        lift = hit.get("lift", 1.0)
        fs = hit.get("fs", {})           # frequency stats
        ps = hit.get("ps", {})           # probability stats

        total_orders = fs.get("f", 0)
        late_orders = fs.get("fOnCondition", 0)
        late_rate = ps.get("pOnCondition", 0.0)

        risks.append(DeliveryRisk(
            supplier=supplier_name,
            late_rate=round(late_rate, 3),
            lift=round(lift, 2),
            total_orders=total_orders,
            late_orders=late_orders,
            risk_level=_classify_risk(late_rate, lift),
        ))

    risks.sort(key=lambda r: r.lift, reverse=True)
    return risks
```

The classification combines two signals:

```python
def _classify_risk(late_rate: float, lift: float) -> str:
    if late_rate >= 0.30 or lift >= 2.0:
        return "high"
    elif late_rate >= 0.15 or lift >= 1.5:
        return "medium"
    return "low"
```

The `_relate` query shape:

```json
{
  "from": "purchases",
  "where": { "delivery_late": true },
  "relate": "supplier"
}
```

Aito returns hits like:

```json
{
  "related": { "supplier": { "$has": "Neste Oyj" } },
  "lift": 1.42,
  "fs": { "f": 218, "fOnCondition": 72 },
  "ps": { "p": 0.21, "pOnCondition": 0.33 }
}
```

`fs.fOnCondition` is "rows where supplier=Neste AND
delivery_late=true"; `ps.pOnCondition` is "P(late | supplier=Neste)"
= 33%; `lift` is that conditional probability divided by the base
late rate.

## Key features

### 1. Spend overview from `_search`, not `_relate`
Spend is plain aggregation — `_search` with `limit=5000`, group
client-side by supplier, sum `amount_eur`. Aito's strengths
(probability, lift, prediction) are wasted on sums; we use the
right tool.

### 2. Two signals for risk, both required
A high `lift` with low `late_rate` could be a small supplier with
2/3 late deliveries — statistically suggestive but operationally
not the headline. A high `late_rate` with low `lift` could mean
"everyone in this category is late" — a market problem, not a
supplier problem. The classifier requires either to be high.

### 3. Support counts surfaced in the popover
Clicking any risk row opens a popover showing `late_orders /
total_orders` (`72 / 218`). Without that, lift is just a number.
With it, the user can decide whether to call the supplier or
write off the sample as noise.

### 4. Sorted by lift, not by spend
A supplier with €40K spend and 3× late-lift is a bigger problem
than one with €400K spend and 1.1× lift, even though the latter
ships more euros. Sorting by spend would bury the signal under
volume.

## Data schema

```json
{
  "purchases": {
    "type": "table",
    "columns": {
      "supplier":      { "type": "String" },
      "amount_eur":    { "type": "Decimal"},
      "category":      { "type": "String" },
      "delivery_late": { "type": "Boolean"},
      "order_month":   { "type": "String" }
    }
  }
}
```

`delivery_late` is `Boolean` (not "Late" / "On time" strings).
`_relate` works on either, but `Boolean` keeps the `where` clause
small (`{"delivery_late": true}` vs. `{"delivery_late": {"$is": "Late"}}`).

## Tradeoffs and gotchas

- **`_relate` is unbounded by default**: if you want only the top
  N hits, sort and slice client-side. Aito returns every supplier
  with non-trivial lift; for 5K rows this is dozens of hits.
- **Lift = 1.0 is information**: a supplier whose late rate
  matches the baseline is fine. We drop those at render-time
  (`risk_level = "low"`). Don't filter them out of the API
  response — it changes the meaning of "supplier coverage".
- **`fs.fOnCondition` ambiguity**: with `where={delivery_late: true}`
  and `relate=supplier`, Aito's `fOnCondition` is rows matching
  *both* the where and the related condition. Verified empirically;
  the doc string is clear if you read carefully.
- **No category-cross**: we relate by supplier alone. A real
  procurement team would want supplier × category × season. That's
  a `_relate` over a composite condition (`{"$and": [...]}`); the
  query supports it, the UI doesn't yet.
- **No causality**: Elenia spikes in winter because storms knock
  out lines, not because Elenia is bad. Lift surfaces the pattern;
  the human reads the cause.

## Try it live

[**Open Supplier Intel**](http://localhost:8400/supplier/) and
click any risk row for the lift × support breakdown.

```bash
./do dev   # starts backend + frontend
```

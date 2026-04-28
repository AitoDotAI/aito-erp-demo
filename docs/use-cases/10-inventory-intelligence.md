# Inventory Intelligence — Stockout risk with cash impact

![Inventory Intelligence](../../screenshots/10-inventory.png)

*SKU-4421 Wärtsilä Seal Kit — 4 units on hand, ~6 units/month
forecast, 22 days of supply against a 14-day lead time → critical;
SKU-FUEL fleet fuel — 980 units on hand against 42-units/month
forecast → 773 days of supply, €19K in tied capital recoverable*

## Overview

Inventory is where every other prediction lands. The demand
forecast says "you'll sell 6 workwear sets in August"; the supplier
data says "Lindström lead time is 14 days"; the stock count says
"you have 3"; arithmetic says you stock out before the next
delivery. Inventory Intelligence does that arithmetic for every
SKU and surfaces the answers in two flavours: **stockout risk in
EUR margin at risk** and **overstock waste in EUR tied capital**.

This view does not call Aito. It depends on `demand_service.forecast_demand`
for the units-per-month number, and combines that with hardcoded
stock levels, lead times, and unit prices to compute days-of-supply
and dollar impact. That's deliberate — Aito's strengths are
prediction, not arithmetic. Mixing the two would muddle the
explanation.

## How it works

### Traditional vs. AI-powered inventory

**Traditional:**
- Static reorder points set during ERP go-live, never tuned
- "Days of supply" computed from a frozen monthly average
- No EUR translation — managers see "low stock" not "€4K of
  margin at risk this week"
- Overstock invisible until the warehouse runs out of room

**With Aito-fed forecast:**
- Daily demand = `forecast_demand(...) / 30` — seasonal-aware
- Days of supply = `stock / daily_demand`, recomputed each load
- Critical / Low / OK / Overstock classification with safety
  buffer
- EUR impact: stockout risk = 1 week of margin at risk; tied
  capital = excess units × unit price

### Implementation

The inventory service in `src/inventory_service.py` reuses the
demand forecast and applies the arithmetic:

```python
def get_inventory_status(
    client: AitoClient,
    target_month: str = "2025-06",
) -> InventoryOverview:
    """Compute inventory status for all demo products."""
    UNIT_PRICES = {
        "SKU-4421": 148.00, "SKU-FUEL": 94.00, "SKU-2234": 89.00,
        "SKU-HVAC": 82.00, "SKU-5560": 25.00, "SKU-9901": 3.40,
    }
    TARGET_BUFFER_DAYS = 60

    items: list[InventoryItem] = []
    for product_id, product_info in DEMO_PRODUCTS.items():
        stock = STOCK_LEVELS.get(product_id, 0)
        lead_time = LEAD_TIMES.get(product_id, 14)

        # Reuse the demand forecast — Aito is upstream of inventory
        demand = forecast_demand(client, product_id, target_month)
        monthly_forecast = demand.forecast if demand.forecast > 0 else demand.baseline
        daily_demand = monthly_forecast / 30.0

        days_of_supply = round(stock / daily_demand, 1) if daily_demand > 0 else 999.0
        status = _classify_status(days_of_supply, lead_time)

        # Cash impact
        excess_units = 0
        tied_capital = 0.0
        stockout_risk = 0.0
        if status == "overstock" and daily_demand > 0:
            target_stock = daily_demand * TARGET_BUFFER_DAYS
            excess_units = max(0, int(stock - target_stock))
            tied_capital = round(excess_units * UNIT_PRICES.get(product_id, 0), 2)
        elif status == "critical":
            stockout_risk = round(daily_demand * 7 * UNIT_PRICES.get(product_id, 0), 2)

        items.append(InventoryItem(
            product_id=product_id, product_name=product_info["name"],
            stock_on_hand=stock, daily_demand=round(daily_demand, 1),
            days_of_supply=days_of_supply, lead_time_days=lead_time,
            status=status, forecast_units=round(monthly_forecast, 1),
            unit_price=UNIT_PRICES.get(product_id, 0),
            excess_units=excess_units, tied_capital_eur=tied_capital,
            stockout_risk_eur=stockout_risk,
            substitutions=SUBSTITUTIONS.get(product_id, [])
                          if status in ("critical", "low") else [],
        ))

    items.sort(key=lambda i: {"critical": 0, "low": 1, "ok": 2, "overstock": 3}[i.status])
    return InventoryOverview(items=items, ...)
```

The classification is opinionated:

```python
def _classify_status(days_of_supply: float, lead_time: int) -> str:
    SAFETY_BUFFER_DAYS = 7
    critical_threshold = lead_time + SAFETY_BUFFER_DAYS
    low_threshold = lead_time * 2 + SAFETY_BUFFER_DAYS

    if days_of_supply < critical_threshold:        return "critical"
    elif days_of_supply < low_threshold:            return "low"
    elif days_of_supply > OVERSTOCK_MONTHS * 30:    return "overstock"
    return "ok"
```

There's no Aito query in this file. The query that matters happens
upstream in `demand_service` (see view 9).

## Key features

### 1. Reorder Now creates a real PO
The Reorder button POSTs a new draft PO into the workflow. It
appears in the PO Queue (view 1) with predicted account / cost
center / approver, and flows through Approval (view 3) like any
other purchase. End-to-end loop in one click.

### 2. EUR everywhere, not units
Status pills show counts; the headline numbers are EUR. "€19,200
freed by reducing fuel safety stock" lands harder than "removed
720 excess units of SKU-FUEL". Translating early is the point of
this view.

### 3. Substitutions only when relevant
`SUBSTITUTIONS` is keyed by SKU and only surfaced for `critical`
and `low` items. An overstock SKU doesn't need a substitution
suggestion — that would be confusing.

### 4. Seasonal-aware via demand_service
Because `forecast_demand` already folds in same-month
seasonality, the August row for workwear shows 14 units/month
forecast (not the 6-unit baseline), which makes 3 units on hand
properly critical. Without the seasonal lift, the same row would
read OK. This is why the demand and inventory services share
state.

## Data schema

Inventory has no Aito table of its own in this demo. The data
lives in three Python dicts (`STOCK_LEVELS`, `LEAD_TIMES`,
`REORDER_POINTS`) that you'd replace with reads against your
warehouse-management system. The schema-side dependency is
`orders` (consumed by demand_service):

```json
{
  "orders": {
    "type": "table",
    "columns": {
      "product_id": { "type": "String" },
      "month":      { "type": "String" },
      "units_sold": { "type": "Int"    }
    }
  }
}
```

## Tradeoffs and gotchas

- **No Aito call in the file**: this is a deliberate choice. The
  arithmetic is deterministic; pretending Aito was involved would
  obscure the explanation. The Aito side panel for this view
  shows the *upstream* demand query, not a fake inventory query.
- **Hardcoded `UNIT_PRICES`** in the service file — you would not
  do this in production. We did it because the demo's
  `price_history` table has variance per supplier and we needed
  one canonical figure for tied-capital math. Pull from a master
  in real life.
- **`TARGET_BUFFER_DAYS = 60`** is a single tunable for overstock
  classification. Some categories (consumables) want lower; some
  (specialty parts) want higher. Per-category in production.
- **`stockout_risk_eur` = 1 week of margin at risk** is a rough
  proxy. A real model would consider lead-time variance, expedite
  cost, and downstream production stoppage. The point here is to
  put a number on the page; calibrate before you trust it.
- **Sort order is by status bucket**, not by EUR impact. A €19K
  overstock sits below a €600 critical because the *urgency* is
  what the user wants to see first. Reasonable for the demo;
  consider a "by impact" toggle for real volumes.

## What this demo abstracts away

- **Per-SKU lead-time variance**. The demo uses a single lead-time
  number per SKU. Real lead times have variance: Wärtsilä's seal
  kit is "14 days ± 3 days, 95th percentile 22 days". Production
  computes the safety buffer from the lead-time *distribution*, not
  the mean — and surfaces lead-time-variance as its own risk signal.
- **Reorder approval workflow**. Click Reorder here creates a PO
  directly. Production gates that on a buyer's approval (or
  category-specific auto-approve thresholds), with the predicted
  fields surfaced for review. The wiring already exists — the
  generated PO flows through the PO Queue — but the demo skips the
  approval step.
- **Multi-location stock with transfers**. One stock number per
  SKU. Real chains have stock at HQ, regional warehouses, retail
  stores, and the right move when SKU-X is critical at Store-3 is
  often "transfer from Warehouse-EU" not "reorder from supplier".
  Production adds a `stock_locations` table and a transfer-vs-buy
  decision layer.

## Try it live

[**Open Inventory Intelligence**](http://localhost:8400/inventory/)
and click Reorder on the critical row — the new PO appears in the
PO Queue.

```bash
./do dev   # starts backend + frontend
```

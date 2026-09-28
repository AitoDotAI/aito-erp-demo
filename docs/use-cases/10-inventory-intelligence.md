# Inventory Intelligence — will it run out before the next delivery?

![Inventory Intelligence](../../screenshots/10-inventory.png)

## Overview

For the busiest stocked items, the view asks the buyer's question: does
what is on the shelf, plus what is already on its way and lands within
the lead time, cover what will sell before a new order could arrive?

It asks twice — once with Aito's demand forecast, once with the
trailing three-month average a plain ERP min/max rule uses — and then
checks both. The month after the cutoff is held out, so the page shows
which items were short at that month's ACTUAL sales rate — cover at the
real daily rate below the lead time — and how often each forecast's
warning agreed. It is one month's rate projected over the lead time,
not a count of days the shelf was empty, and the page says so.

## The data

- **`stock`** (synthetic, and labelled so on screen): on hand, on
  order, next delivery, lead time, reorder point. It is simulated by
  `data/generate_demand.py` by playing the product's real sales history
  against a trailing-average min/max rule, so stock is depleted by the
  same demand the forecast learns from rather than typed in.
- **Demand** comes from the Demand Forecast's query — `_estimate
  units_sold` over `monthly_demand` — see
  [09-demand-forecast.md](09-demand-forecast.md).

## What it measures

Two things, both on screen with their counts:

1. **Forecast accuracy against the reorder rule** (`./do demand-eval`):
   Aito's demand forecast has 17-20% error against the trailing rule's
   24-29% — 15-42% less, depending on the tenant. That is the comparison that matters for a reorder point,
   because the trailing rule is what the stock here was managed by.
2. **Were the "will run short" warnings right?** Counted per method:
   warnings raised, how many were right, how many shortfalls at the
   actual rate were caught. In the held-out month only 0-2 items per
   tenant were short at their actual rate, so the page says plainly that this is too few to separate the
   two methods rather than letting "1 vs 0" read as a result.

The previous version hard-coded stock per SKU, a supplier map, an
invented "€ stockout risk", substitution suggestions and a reorder
button that did nothing.

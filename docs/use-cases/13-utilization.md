# Use case 13 — Utilization & Capacity *(Studio-only)*

> The canonical services-ERP view. Per-consultant load, at-risk
> allocation, and a "what if" forecast for role + allocation on a
> hypothetical engagement.

![Utilization](../../screenshots/12-utilization.png)

## What it does

For every consultant in the firm the page shows:

- **Current load** — sum of `allocation_pct` across active assignments
- **At-risk load** — allocation tied to projects flagged `at_risk` or
  `delayed`
- **Historical norm** — average allocation across completed projects
  (the structural baseline)
- **Status** auto-classified: overloaded (>110%), available (<60%),
  at-risk (>25% on slipping work), balanced

Click a consultant to unlock the **"What if" forecast**: pick a project
type from the dropdown, see the role and allocation Aito predicts for
that person on a typical engagement of that kind.

## Aito query — what-if forecast

```json
POST /api/v1/_predict
{
  "from": "assignments",
  "where": {
    "person": "A. Lindgren",
    "project_type": "design"
  },
  "predict": "allocation_pct"
}
```

A plain single-table `_predict` — `project_type` is denormalised
onto each `assignments` row at fixture-load time, so we don't need a
cross-table join to filter by it. The query asks "for this person,
on this kind of project, what's the most likely allocation?". A
second call swaps `predict` to `role` to also return their typical
role.

The service surfaces `historical_count` so the UI can flag "no prior
assignments of this type" honestly — predictions on zero history
would just be the population baseline.

## Schema

Uses `assignments` and `projects`. The `assignments` table carries
two denormalised columns (`project_type`, `project_success`) mirrored
from the linked `projects` row at load time; this lets `_predict` and
`_relate` filter by them as ordinary fields. Production ERPs often do
the same denormalisation onto timesheet/assignment rows for query
performance.

## Tradeoffs / honest notes

- **Aggregation, not prediction, for current load**: the load
  percentages are a sum of recorded allocations. Aito doesn't predict
  *what's currently true* — it predicts *what would happen on a new
  engagement*. The two columns answer different questions and the UI
  is explicit about which is which.
- **No timesheet integration**: `allocation_pct` is the planned
  allocation, not actual hours logged. A real ERP would also surface
  the gap between planned and actual; this demo doesn't have a
  timesheet table.
- **Historical sample-size disclosure**: when the prediction has no
  history (zero past assignments of that type for that person), the
  panel shows a red note rather than presenting a confident-looking
  prediction.

## Why services-ERP buyers care

This view is what Severa, Kantata, and Workday Adaptive lead with for
services prospects. Without it, a services firm reads the demo as
commerce-flavoured. The Aito angle: the role × allocation forecast is
a plain `_predict` on the historical assignment table — same query
shape as PO Queue's account-code prediction, just on a different domain.

## Implementation

[`src/utilization_service.py`](../../src/utilization_service.py) —
`get_overview()` aggregates from `_search` (no per-row Aito calls),
`forecast_assignment()` runs the per-person predictive layer.

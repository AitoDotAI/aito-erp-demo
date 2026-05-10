# Cold Start — Accuracy as a function of history

![Cold Start](../../screenshots/coldstart.png)

*Slider-driven view of how prediction quality grows from a fresh tenant
to a mature one — the same Aito DB, queried with a month cutoff that
truncates which history Aito's conditional probabilities can see.*

## Overview

The single hardest objection to "predict from history" is the cold-start
problem: what does the demo do when the tenant has 50 invoices, not
50 000? The Cold Start view answers it directly. A slider walks back
through the database in time, and at each cutoff the page re-runs
Aito's `_evaluate` to show the held-out accuracy at that history size.

CTOs see two truths from the same screen:
- **Accuracy grows with history** — but not linearly. The first few
  hundred rows already produce a useful baseline; the long tail is
  about coverage of rare combinations, not raw accuracy.
- **High-confidence predictions are honest from day one.** Even at
  100 rows, when Aito returns `$p ≥ 0.85` the prediction is right
  ~95% of the time. The model knows what it doesn't know.

## How it works

### The query — `_evaluate` with a month cutoff

`_evaluate` is Aito's hold-out tester: pick `testSource` rows, hide
each one's target field, predict it from `feature_fields`, compare to
ground truth. The trick for cold-start simulation is layering an
extra `where` constraint on the *evaluate* side that says "only
condition probabilities on rows older than this cutoff":

```python
client.evaluate_with_cases(
    table="purchases",
    predict_field="cost_center",
    feature_fields=["supplier", "description", "amount_eur"],
    test_where={"order_month": {"$gte": cutoff}},      # held out
    evaluate_extra_where={"order_month": {"$lt": cutoff}},  # condition only on this slice
    limit=200,
)
```

The slider's value becomes `cutoff`. With cutoff = `"2022-09"`, Aito's
conditional probabilities use ~3 months of history; with cutoff =
`"2025-12"`, they use everything up to the present. Same DB, same
query shape — only one parameter changes.

### What the view renders

For each cutoff position the page shows, per-field:
- **Total accuracy** — share of held-out rows Aito got right.
- **Base accuracy** — what you'd get by always predicting the most
  common value. The gap between these two is *what Aito is buying you*.
- **High-confidence share** — % of test cases Aito returned with
  `$p ≥ 0.85`. Grows fast in the first 500 rows, then plateaus.
- **High-confidence accuracy** — within the high-conf band, how often
  Aito is right. This stays near 95% from the first cutoff onwards;
  Aito is well-calibrated even on tiny histories.

The static snapshot at the top of the page (`captured_at`) is captured
offline by `scripts/capture_coldstart.py` against an Aito DB with
write access — the deployed demo runs with a read-only key, so live
recomputation isn't an option there. The slider underneath is the
*live* version: queries against whatever the current tenant has
loaded, recomputed on every drag.

## Tradeoffs and gotchas

- **`testSource` rows must be a sensible held-out slice.** Using the
  *latest* months as test, and *earlier* months as evaluate-condition,
  mimics how a real tenant accrues history over time. Reversing it
  would test "predict yesterday given tomorrow", which is meaningless.
- **Cold-start ≠ no signal.** The 50-row case isn't useless; it's
  honest. Aito returns wide distributions and lower top-`$p` values,
  and the demo's high-confidence-only auto-coding flow naturally
  routes most of those to manual review. As history grows, more
  predictions cross the auto-code threshold.
- **The slider's network cost is real.** Each drag fires an
  `_evaluate` round-trip. We debounce on the client and cap the
  cutoff range so the slider stays responsive on shared.aito.ai's
  free tier.

## Code

- Page: [`frontend/app/coldstart/page.tsx`](../../frontend/app/coldstart/page.tsx)
- Aito client method: [`AitoClient.evaluate_with_cases`](../../src/aito_client.py)
  (general-purpose; also used by `overview_service`)
- Static snapshot capture: [`scripts/capture_coldstart.py`](../../scripts/capture_coldstart.py)

# Cold-start curve — methodology

The `/coldstart` view shows real `_evaluate` numbers captured at three
data sizes (50 / 500 / 5,000 rows). The capture is offline because the
public demo's API keys are read-only — re-running it requires a
write-enabled Aito DB.

## What the view tries to answer

> *"What does prediction quality look like for a tenant that has only
> one week of data? One month? One year?"*

The CTO's instinct is to assume "no model = no working predictions
until you've trained for a while." The cold-start view is the answer:
Aito's $p is calibrated even at small N. **Specific values vary, but
the shape — accuracy rises, baseline stays flat, the high-confidence
band stays near-perfect while its share of the queue grows — is
load-bearing.**

## How to refresh the snapshot

You need an Aito DB with write access. The shared
`shared.aito.ai/db/aito-erp-demo-*` keys committed to `.env.example`
are read-only.

1. Provision a sandbox DB. Aito console → New DB → name it something
   like `aito-erp-demo-coldstart-<your-handle>`. Copy the URL and the
   write API key.
2. Run the capture script:
   ```bash
   python scripts/capture_coldstart.py \
       --aito-url   https://shared.aito.ai/db/your-coldstart-sandbox \
       --aito-key   <write-key>
   ```
   This will:
   - Subsample `data/metsa/purchases.json` to 50, 500, and 5,000 rows
     (deterministic — `--seed=2026` by default, so reruns produce the
     same snapshot).
   - For each subsample: drop and recreate the `purchases` table in
     your sandbox DB, upload the rows, run `_evaluate` for each of
     `cost_center` / `account_code` / `approver`, capture the cases
     payload.
   - Aggregate accuracy, baseline, and the share + accuracy of the
     ≥ 0.85 confidence band.
   - Write `data/coldstart/results.json`.
3. Commit the updated `data/coldstart/results.json`. The view picks
   it up on the next deployment.

## What the script does

```python
for size in [50, 500, 5000]:
    sample = subsample(metsa_purchases, size, seed=2026)
    drop_and_recreate("purchases", schema)
    bulk_upload("purchases", sample)
    for field in ("cost_center", "account_code", "approver"):
        cases = aito.evaluate_with_cases(
            "purchases", field,
            ["supplier", "description", "amount_eur"],
            limit=200,
        )
        record(size, field, cases)
```

## Reading the snapshot

For each subsample, the JSON records four numbers per field:

| Field | What it tells you |
|---|---|
| `accuracy` | Overall held-out accuracy (top prediction matches truth). |
| `base_accuracy` | Naive baseline — "always pick the most-common value". |
| `high_confidence_share` | Share of test cases whose top $p was ≥ 0.85. |
| `high_confidence_accuracy` | Accuracy *within* that high-confidence band. |

The most useful single number is `high_confidence_accuracy` —
"predictions Aito *says* are confident really are correct, even at
N=50". The `high_confidence_share` then tells you how much of the
operator's queue Aito is willing to auto-approve at this data scale.

## Notes

- The capture is destructive on the target DB — the `purchases`
  table is dropped and recreated three times. Don't aim it at a DB
  you care about.
- The `_evaluate` test source uses `limit: 200` per snapshot, which
  is the same limit `overview_service.get_prediction_quality` uses
  — keeps the numbers comparable across views.
- Subsample seed is fixed at 2026 so reruns give the same snapshot.
  Bump it when you want a new draw.

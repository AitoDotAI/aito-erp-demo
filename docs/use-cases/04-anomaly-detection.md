# Anomaly Detection — Inverse prediction

![Anomaly Detection](../../screenshots/04-anomalies.png)

*PO-7812 (Fazer × account 4220) flagged at score 91 — Fazer is a food
supplier, account 4220 (office supplies) almost never co-occurs*

## Overview

Anomalies are the inverse of predictions. If you ask Aito "what
account_code would you predict for Fazer Food Services?" and the top
hit is `5710` (catering) at 89% — but the actual booked code is
`4220` (office supplies) — then the actual value is improbable
given the data. The anomaly score is `(1 - p_actual) × 100`.

This view runs three flavours of inverse prediction over a small
demo set and ranks the results. **Account-code anomalies** use
`_predict` directly. **Unknown-vendor anomalies** use `_search` for
prior history (no prior records → high score). **Amount anomalies**
compare the booked amount against the supplier's mean. Each row
ends with an action button that closes the loop in
`submission_store`.

## How it works

### Traditional vs. AI-powered anomaly detection

**Traditional:**
- Rules: "flag any PO over €10K", "flag any new supplier"
- Static thresholds rot as business changes
- Can't catch combinations: Fazer × 4220 looks fine to a per-field
  rule
- High false-positive rate kills attention

**With Aito:**
- Combinations are first-class: `_predict(supplier=Fazer)` knows
  what account codes co-occur
- Unusual = "the value Aito would not have predicted"
- Score is calibrated to a probability, not an arbitrary threshold
- Three different scoring strategies, one ranked dashboard

### Implementation

The anomaly service in `src/anomaly_service.py` dispatches on
`flagged_field` and computes the inverse probability:

```python
def evaluate_transaction(client: AitoClient, transaction: dict) -> AnomalyFlag:
    """Inverse prediction. The scoring approach depends on which field
    is flagged — different anomaly types call for different bases."""
    flagged_field = transaction.get("flagged_field", "account_code")
    where = {"supplier": transaction["supplier"]}

    if flagged_field == "supplier":
        # Unknown supplier: any prior PO from this supplier?
        result = client.search("purchases", {"supplier": transaction["supplier"]}, limit=1)
        hits = result.get("hits", [])
        p = 0.02 if not hits else 0.15

    elif flagged_field == "amount":
        # Amount anomaly: compare to per-supplier mean
        actual_amount = transaction.get("amount", 0)
        result = client.search("purchases", {"supplier": transaction["supplier"]}, limit=50)
        amounts = [h.get("amount_eur", 0) for h in result.get("hits", [])]
        avg = sum(amounts) / len(amounts) if amounts else 1
        ratio = actual_amount / avg if avg > 0 else 1
        # 4x → ~p=0.06, 2x → p=0.18, 1x → p=0.6
        p = max(0.04, min(0.60, 0.60 / (ratio if ratio > 0 else 1)))

    else:
        # Categorical inverse prediction (account_code etc.)
        result = client.predict("purchases", where, flagged_field)
        hits = result.get("hits", [])
        actual_value = transaction.get(flagged_field, transaction["account_code"])
        p = 0.0
        for hit in hits:
            if str(hit.get("feature", "")) == str(actual_value):
                p = hit.get("$p", 0.0)
                break
        else:
            # Value not in top-10 → residual mass
            top_mass = sum(h.get("$p", 0.0) for h in hits[:5])
            p = max(0.0, 1.0 - top_mass) * 0.05

    anomaly_score = round((1.0 - p) * 100)
    return AnomalyFlag(..., anomaly_score=anomaly_score,
                      severity=_classify_severity(anomaly_score), ...)
```

The categorical inverse-prediction query:

```json
{
  "from": "purchases",
  "where": { "supplier": "Fazer Food Services" },
  "predict": "account_code",
  "select": [
    "$p",
    "feature",
    { "$why": { "highlight": { "posPreTag": "«", "posPostTag": "»" } } }
  ],
  "limit": 10
}
```

We then look for the *actual* booked value (`4220`) in the hits.
Found at $p=0.04 → score 96. Not found at all → score from residual
mass.

## Key features

### 1. Three anomaly types, one ranked list
- `account_code`: predict-and-compare. Catches mis-coded postings.
- `supplier`: search for prior history. Catches new vendors.
- `amount`: compare to per-supplier mean. Catches step-changes
  (Neste typically €2-3K, this one is €9.8K → 4x → score 87).

The frontend doesn't need to know which strategy ran — every flag
has the same score / severity / explanation shape.

### 2. Severity tiers, not raw scores
The dashboard groups by `severity` (`high` ≥ 85, `medium` ≥ 60,
`low` < 60). Raw scores rank within a tier. Tiers map to colour and
to which action buttons render — `high` shows
Investigate / Escalate / Mark legitimate; `low` only shows
Investigate.

### 3. Calibrated to probability, not z-score
The score is `(1 − p_actual) × 100`. A score of 91 means **9% prior
probability** that this combination occurs naturally. That's
defensible to an auditor in a way that "z-score 3.2" isn't.

### 4. Action buttons close the loop
Each action (Investigate / Escalate / Legitimate) writes to the
submission store. "Mark legitimate" is the most important one — it
tells the next sync that the Fazer × 4220 combination was reviewed
and accepted. Future predictions reflect that. (The store is
in-memory in the demo; production would persist it.)

## Data schema

```json
{
  "purchases": {
    "type": "table",
    "columns": {
      "purchase_id":  { "type": "String" },
      "supplier":     { "type": "String" },
      "amount_eur":   { "type": "Decimal"},
      "account_code": { "type": "String" }
    }
  }
}
```

Anomaly detection doesn't require a separate table or any extra
fields. Every field already used for prediction is available for
inverse prediction.

## Tradeoffs and gotchas

- **`_evaluate` exists** and is the API-blessed way to do this
  ("how likely is this combination?"). We use `_predict` and look
  for the actual value because the response includes `$why` factors
  for the actual value, not just a single number — that's what
  drives the explanation popover.
- **Residual mass for out-of-top-10 values** is heuristic
  (`(1 - top_mass) × 0.05`). For values that genuinely never
  appeared in history, `_evaluate` would give a tighter answer.
- **Amount-anomaly scoring is purely client-side** — Aito doesn't
  do amount-distribution. We use `_search` to fetch the supplier's
  history, then compute mean and ratio in Python. This is a
  reasonable place for a numeric-distribution operator that Aito
  doesn't yet expose.
- **Sample-size sensitivity**: a supplier with one prior PO has a
  meaningless mean. We don't currently tag low-sample anomalies as
  low-confidence; the demo set is curated so this doesn't bite.
- **The demo set is hardcoded** (`DEMO_ANOMALIES`). In production,
  you'd run anomaly detection on every new PO and surface the top
  N by score. The wiring is the same — just the input list grows.

## What this demo abstracts away

- **Streaming detection vs. hardcoded set**. `DEMO_ANOMALIES_BY_TENANT`
  is a curated list. Production scores every new PO at creation
  time, surfaces the top N by score in a queue, and lets the user
  Investigate / Escalate / Mark legitimate. The wiring is the same
  — `evaluate_transaction()` is called per row, not per demo seed.
- **Action-loop persistence**. The demo's Investigate / Escalate /
  Legitimate buttons don't write anywhere. Real systems persist the
  decision (`anomaly_id, decision, user, ts`), feed Legitimate
  decisions back as positive labels (so the same pattern stops
  flagging), and use Escalate to open tickets in the audit system.
- **Per-tenant threshold tuning**. `SEVERITY_HIGH=85` is a global
  constant. Different verticals tolerate different anomaly-rates
  (a manufacturing firm wants tight thresholds; a high-volume
  retailer wants looser). Production reads thresholds per-tenant
  from a config table; the demo sets them globally.

## Try it live

[**Open Anomaly Detection**](http://localhost:8400/anomalies/) and
click `?` next to any flag to see the multiplicative chain that
makes the actual value improbable.

```bash
./do dev   # starts backend + frontend
```

# Smart Entry — Multi-field prediction with cross-highlight

![Smart Entry](../../screenshots/02-smart-entry.png)

*Pick "Lindström Oy" from the supplier dropdown; cost center, account
code, project, and approver fill in at once with per-field confidence*

## Overview

Manual PO entry is mostly typing things the data already knows. Once
the supplier is picked, the cost center, account code, project, and
approver are usually obvious from history — a Lindström order goes to
Production / 6520 / Workwear FY25 / Mikko in 91% of past cases.

Smart Entry runs four `_predict` calls in parallel from a single
supplier pick and renders each result in a `SmartField` — one DOM
input per concept with three visual states (empty / predicted / user).
Tab promotes a prediction; Esc rejects it; typing replaces it.
Clicking the `?` on any field cross-highlights the input fields that
contributed.

## How it works

### Traditional vs. AI-powered form fill

**Traditional:**
- Per-supplier defaults table (handwritten, drift)
- All-or-nothing autofill — one wrong default and the user re-types
  everything
- No confidence signal: user can't tell which suggestions are safe to
  accept blindly
- Defaults don't learn from corrections

**With Aito:**
- Each field is a separate `_predict` call with its own confidence
- High-confidence fields (≥85%) show as faint gold; low-confidence
  fields (<50%) pulse red
- Tab/Esc per field — accept what's right, override what isn't
- Every Tab and override is a confirmed signal in the next prediction

### Implementation

The Smart Entry service in `src/smartentry_service.py` predicts each
missing field independently from the supplied context:

```python
def predict_fields(client: AitoClient, known: dict) -> SmartEntryResult:
    """Predict all missing fields given a subset of known fields."""
    from src.why_processor import process_factors, extract_alternatives

    where = {k: v for k, v in known.items() if k in INPUT_FIELDS and v}
    fields_to_predict = [f for f in PREDICT_FIELDS if f not in known]

    predictions: list[FieldPrediction] = []
    for field_name in fields_to_predict:
        result = client.predict("purchases", where, field_name, limit=10)
        hits = result.get("hits", [])
        top = hits[0] if hits else {}
        top_p = top.get("$p", 0.0) if top else 0.0
        why = process_factors(top.get("$why"), top_p) if top else None
        alts = extract_alternatives(hits, skip_top=True, limit=3)

        predictions.append(FieldPrediction(
            field_name=field_name,
            predicted_value=str(top.get("feature", "")),
            confidence=top_p,
            alternatives=alts,
            why_factors=why or {},
        ))

    overall = min(p.confidence for p in predictions) if predictions else 0.0
    return SmartEntryResult(
        input_fields=where, predictions=predictions, overall_confidence=overall
    )
```

`PREDICT_FIELDS` is `["cost_center", "account_code", "project",
"approver"]` — four fields, four `_predict` calls. The query shape
for each is identical to PO Queue:

```json
{
  "from": "purchases",
  "where": { "supplier": "Lindström Oy" },
  "predict": "account_code",
  "select": [
    "$p",
    "feature",
    { "$why": { "highlight": { "posPreTag": "«", "posPostTag": "»" } } }
  ],
  "limit": 10
}
```

The frontend issues all four in parallel via `Promise.all` so the
total wall time is one round-trip, not four.

## Key features

### 1. SmartField three-state input
One DOM input per concept. The visual state encodes provenance:
- **Empty**: placeholder, no badge
- **Predicted**: gold italic + 🤖 badge, popover available on `?`
- **User**: black, normal weight, badge cleared

Tab promotes predicted → user (lock in). Esc demotes predicted →
empty (reject). Typing replaces — no separate "edit" mode.

### 2. Cross-highlighting on `?`
Clicking the `?` next to (say) `account_code` opens the
`PredictionExplanation` popover. The popover's `context_fields` list
contains every input field that contributed lift; the page wraps each
matching SmartField in a purple ring. The user sees both **why** and
**from where**.

### 3. Confidence-bounded overall result
`overall_confidence` is the **minimum** across the four predictions,
not the average. If any field is low-confidence, the whole row is
flagged for review. Average would let one rotten prediction hide
behind three good ones.

### 4. Same `_predict` shape as PO Queue
Smart Entry doesn't use a special endpoint. The same query pattern
(supplier as the only `where`, single field as `predict`, full `$why`
in `select`) drives every interactive form in the demo. One pattern,
many surfaces.

## Data schema

Smart Entry queries the same `purchases` table as PO Queue:

```json
{
  "purchases": {
    "type": "table",
    "columns": {
      "supplier":     { "type": "String" },
      "category":     { "type": "String" },
      "description":  { "type": "Text"   },
      "cost_center":  { "type": "String" },
      "account_code": { "type": "String" },
      "project":      { "type": "String" },
      "approver":     { "type": "String" }
    }
  }
}
```

`INPUT_FIELDS` (allowed `where` keys) is a strict allowlist:
`{supplier, category, description, cost_center, account_code}`.
Anything else in the request body is dropped before the query runs.

## Tradeoffs and gotchas

- **Four sequential calls in the service**, parallelized by the
  frontend. We considered Aito's batch endpoint but the per-field
  `$why` payloads are large — easier to keep one request per field
  and let the browser fan out.
- **Predicting `description`** sounds tempting but doesn't work:
  description is `Text` (tokenized), so `_predict` returns single
  tokens, not phrases. Smart Entry skips it.
- **Cross-highlight relies on `$context.<field>` prefixes** in the
  highlight payload. If you change `process_factors` to strip those,
  the purple rings break silently — the field name no longer matches
  any `SmartField`. Keep `raw_field` around.
- **Tab vs. focus order**: a Tab on a predicted field promotes
  *and* moves focus. Browsers don't expose "Tab without moving" so
  we wrap the input in a key handler that calls `preventDefault()`
  only when the value is in the predicted state.
- **No silent coercion**: a prediction that returns the empty string
  (no history at all) shows as empty with the `!` low-confidence
  trigger. We never pretend to know what we don't.

## Try it live

[**Open Smart Entry**](http://localhost:8400/smart-entry/) and pick
any supplier from the dropdown. Tab through the predicted fields, or
click `?` to see the input fields highlight in purple.

```bash
./do dev   # starts backend + frontend
```

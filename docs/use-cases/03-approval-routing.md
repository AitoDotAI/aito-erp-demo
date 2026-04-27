# Approval Routing — Suggestions for governance review

![Approval Routing](../../screenshots/03-approval.png)

*PO-7845 (Abloy Oy, €6,100, security category) escalated to CFO via
the security-spend pattern — explicit rule, not an Aito guess*

## Overview

Approval routing is where ERP and policy meet. Procurement says
"who approves this PO?"; Finance says "anything over €5K in the
security category goes to the CFO." If you let predictions write
that policy, you've built an opaque approval matrix the auditor
can't sign off on.

This view splits the work cleanly. **Aito predicts the routine
case** (`approval_level` and `approver` from supplier history)
with the same `_predict` shape as PO Queue. **Hard-coded escalation
rules override** the prediction whenever a governance threshold
applies. Patterns that look like governance candidates aren't
promoted automatically — they're surfaced in Rule Mining (view 6)
where someone has to sign off before they become rules here.

## How it works

### Traditional vs. AI-powered approval routing

**Traditional:**
- Approval matrix rebuilt every time policy changes
- "Who covers Mikko while he's on holiday?" requires a code change
- Policy and prediction live in the same table — no separation
- Audit trail is the matrix itself

**With Aito:**
- Three governance escalation rules in `ESCALATION_RULES`, plain
  Python
- Aito fills in the routine case (75% of POs touch a delegate, not
  a threshold)
- Patterns Aito discovers stay candidates until promoted via Rule
  Mining
- Audit trail is rules + promotion log + prediction history

### Implementation

The approval service in `src/approval_service.py` runs Aito first,
then overlays escalation rules:

```python
def predict_approval(client: AitoClient, item: dict) -> ApprovalPrediction:
    """Predict approval routing for a single purchase order."""
    from src.why_processor import process_factors, extract_alternatives

    where = {"supplier": item["supplier"]}
    if item.get("category"):
        where["category"] = item["category"]

    # Predict approval level and approver in two _predict calls
    level_result = client.predict("purchases", where, "approval_level", limit=10)
    approver_result = client.predict("purchases", where, "approver", limit=10)

    level_top = (level_result.get("hits") or [{}])[0]
    approver_top = (approver_result.get("hits") or [{}])[0]

    predicted_approver = str(approver_top.get("feature", ""))
    predicted_level = str(level_top.get("feature", ""))
    confidence = approver_top.get("$p", 0.0)

    # Governance overlay — explicit rules override Aito when triggered
    escalation_reason = None
    for rule in ESCALATION_RULES:
        if rule["match"](item):
            escalation_reason = rule["reason"]
            predicted_level = rule["level"]
            confidence = 0.99
            break

    return ApprovalPrediction(
        purchase_id=item["purchase_id"],
        predicted_approver=predicted_approver,
        confidence=confidence,
        predicted_level=predicted_level,
        escalation_reason=escalation_reason,
        why=process_factors(approver_top.get("$why"), confidence) if approver_top else {},
        ...
    )
```

The escalation rules are intentionally short and obvious:

```python
ESCALATION_RULES = [
    {"match": lambda i: i["amount"] > 5000 and i.get("category") == "security",
     "level": "CFO",   "reason": "Security spend over €5,000 requires CFO approval"},
    {"match": lambda i: i["amount"] > 20000 and i.get("category") == "capex",
     "level": "Board", "reason": "Capital expenditure over €20,000 requires Board approval"},
    {"match": lambda i: i["amount"] > 50000,
     "level": "Board", "reason": "Any purchase over €50,000 requires Board approval"},
]
```

The `_predict` query for the approver:

```json
{
  "from": "purchases",
  "where": { "supplier": "Abloy Oy", "category": "security" },
  "predict": "approver",
  "select": [
    "$p",
    "feature",
    { "$why": { "highlight": { "posPreTag": "«", "posPostTag": "»" } } }
  ],
  "limit": 10
}
```

## Key features

### 1. Suggestion vs. policy separation
Aito's prediction is a **suggestion**. The `escalation_reason` field
is what makes a row policy. The UI distinguishes the two visually:
escalations get a gold banner, predictions get the standard `?`
trigger. No row mixes both signals.

### 2. Two `_predict` calls, one for level and one for approver
`approval_level` is the categorical bucket (Manager / Director /
CFO / Board); `approver` is the named individual. They can disagree
— for instance, Mikko's name on a "Director" PO when he's covering
for the actual Director — and the popover shows both confidences so
the user knows which is the weak link.

### 3. Confidence pinned at 0.99 for rule-routed POs
When a rule fires we set confidence to `0.99`, not `1.00`. There's
no such thing as 100% in this system; the rule could be wrong, the
amount could be miscoded, the category could be off. Pinning at
0.99 reminds the reviewer that the upstream data could be wrong
even when the rule fired.

### 4. Patterns flow to Rule Mining, not directly to policy
If Aito notices that Wärtsilä spend over €4,500 always routes to
the CFO, it surfaces that as a candidate in Rule Mining (view 6),
not as an escalation rule here. Promotion requires explicit signoff,
which writes to an audit log. This is the governance loop.

## Data schema

```json
{
  "purchases": {
    "type": "table",
    "columns": {
      "supplier":       { "type": "String" },
      "category":       { "type": "String" },
      "amount_eur":     { "type": "Decimal"},
      "approval_level": { "type": "String" },
      "approver":       { "type": "String" }
    }
  }
}
```

`approval_level` and `approver` are both `String` (categorical) so
Aito's `_predict` returns ranked discrete values rather than a
distribution.

## Tradeoffs and gotchas

- **Order matters**: rules run *after* Aito but *override* it. We
  considered short-circuiting (skip Aito if a rule fires) but the
  popover wants Aito's `$why` either way — auditors ask "what would
  Aito have said?" and the answer is in the response.
- **`amount_eur` is `Decimal`** in the schema but Python rules
  compare against a Python `float`. Both Aito and Python treat the
  comparison as numeric — verified, but worth noting if you change
  schema types.
- **No rule for "category=consulting > €5K"**: that pattern emerged
  in the data and was discussed, but never promoted. It lives in
  Rule Mining as a candidate. Demo on purpose: the gap between
  "Aito found it" and "policy says it" is the governance loop.
- **Latency is two `_predict` calls per row** ≈ 60 ms warm-cache.
  Batch processing in `predict_batch()` is sequential — fine for
  the demo's 3-PO queue, would need parallelism for real volumes.

## Try it live

[**Open Approval Routing**](http://localhost:8400/approval/) and
hover over any escalation banner to see whether the level came from
a rule or from Aito.

```bash
./do dev   # starts backend + frontend
```

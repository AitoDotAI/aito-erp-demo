# Rule Mining — Candidates for governance review

![Rule Mining](../../screenshots/06-rules.png)

*Discovered patterns ranked by confidence; "telecom → IT" at 100%
over 17 cases is a Promote candidate, "consulting → Operations" at
78% is a Review candidate*

## Overview

Mature ERP installations accumulate hundreds of routing rules over
years. Most were written for a single edge case, never re-tested,
and now nobody dares touch them. Rule Mining inverts that flow:
**Aito reads the data and proposes the rules**.

For each candidate condition (supplier, category), we use `_relate`
to find which `account_code` it implies. Each candidate has a
confidence (`pOnCondition`), a support count (`fOnCondition`), and
a lift. Strong candidates (≥95% confidence over ≥3 cases) are
flagged as Promote-ready; weaker ones go to a Review queue. **Nothing
becomes a rule until a human clicks Promote**, which writes to an
audit log.

## How it works

### Traditional vs. AI-powered rule discovery

**Traditional:**
- Rules written reactively after a miscoding incident
- No measure of how often the pattern actually holds
- No guard against contradicting an older rule
- Removal requires confidence nobody has

**With Aito:**
- One `_relate` per condition value, ranked by `pOnCondition`
- Support count makes "rare-but-strong" patterns visible
- The data is the evidence; the audit trail is the promotion
- Dismiss writes to the same log so the same pattern doesn't
  resurface

### Implementation

The rule mining service in `src/rulemining_service.py` walks each
condition field, queries distinct values, and runs `_relate` per
value:

```python
def mine_rules(client: AitoClient) -> list[RuleCandidate]:
    """Discover account code assignment rules from purchase history."""
    candidates: list[RuleCandidate] = []

    for cond_field in CONDITION_FIELDS:           # ["supplier", "category"]
        distinct_values = _get_distinct_values(client, cond_field)

        for value in distinct_values:
            result = client.relate(
                "purchases",
                {cond_field: value},
                "account_code",
            )
            for hit in result.get("hits", []):
                related = hit.get("related", {})
                account_info = related.get("account_code", {})
                account_code = (account_info.get("$has", "")
                                if isinstance(account_info, dict)
                                else str(account_info))
                if not account_code:
                    continue

                fs = hit.get("fs", {})
                ps = hit.get("ps", {})
                support = fs.get("fOnCondition", 0)
                confidence = ps.get("pOnCondition", 0.0)

                if support < MIN_SUPPORT:         # MIN_SUPPORT = 3
                    continue

                candidates.append(RuleCandidate(
                    condition_field=cond_field,
                    condition_value=value,
                    predicted_field="account_code",
                    predicted_value=account_code,
                    confidence=round(confidence, 3),
                    support=support,
                    lift=round(hit.get("lift", 1.0), 2),
                    strength=_classify_strength(confidence),
                ))

    candidates.sort(key=lambda r: r.confidence, reverse=True)
    return candidates
```

The strength classification:

```python
STRONG_THRESHOLD = 0.95
REVIEW_THRESHOLD = 0.75

def _classify_strength(confidence: float) -> str:
    if confidence >= STRONG_THRESHOLD: return "strong"
    elif confidence >= REVIEW_THRESHOLD: return "review"
    return "weak"
```

The `_relate` query for each value:

```json
{
  "from": "purchases",
  "where": { "category": "telecom" },
  "relate": "account_code"
}
```

Aito returns hits like:

```json
{
  "related": { "account_code": { "$has": "5510" } },
  "lift": 5.12,
  "fs": { "f": 17, "fOnCondition": 17 },
  "ps": { "p": 0.20, "pOnCondition": 1.00 }
}
```

`pOnCondition = 1.00` over 17 cases ⇒ "every single telecom
purchase in 17 records was coded to 5510". That's a strong promote
candidate.

## Key features

### 1. Three strength tiers, three actions
- **Strong** (≥ 95%): Promote button is gold and primary
- **Review** (75–95%): Promote is secondary, Review queue is the
  default action
- **Weak** (< 75%): not shown unless filter is on; never promoted

### 2. Support floor at 3
A pattern with `pOnCondition=1.0` over 1 case is meaningless.
`MIN_SUPPORT = 3` is low for a real ERP (you'd want 10+) but
right-sized for a demo with 2.8K purchase records. Tunable in one
place.

### 3. Promote writes to an audit log
The frontend's Promote button POSTs to `/api/rules/promote` which
appends to `submission_store`. The log captures rule, who
promoted it, when, and the supporting confidence/support at
promote time. Dismiss writes the same way — both decisions are
durable.

### 4. Two condition fields, more on demand
`CONDITION_FIELDS = ["supplier", "category"]`. Adding a third
(say, `description` keyword) is one line. We don't because two is
enough to demonstrate the pattern; mining 800 distinct
descriptions would surface noise.

## Data schema

```json
{
  "purchases": {
    "type": "table",
    "columns": {
      "supplier":     { "type": "String" },
      "category":     { "type": "String" },
      "account_code": { "type": "String" }
    }
  }
}
```

Same `purchases` table as everywhere else. Rule Mining doesn't
need its own schema; the rules it discovers describe relationships
already present in the data.

## Tradeoffs and gotchas

- **N+1 queries**: distinct values × `_relate` per value. With
  ~60 distinct suppliers and ~12 categories, that's ~70 calls. Fine
  warm-cache; visibly slow cold. The cache table catches it.
- **`_relate` returns lift across all distinct related values**:
  for `where={category: telecom}` and `relate=account_code`, Aito
  returns multiple account codes, each with its own lift. We keep
  all of them, ranked. The frontend filters to top-3 per condition.
- **`pOnCondition` includes the related value in the where**: if
  you compare against an unconditional `_relate`, you'll get
  different numbers. Verified against the `_relate` doc page;
  consistency requires reading carefully.
- **Multi-condition rules aren't mined**: `category=security AND
  amount > 5000 → CFO` is exactly the escalation rule we already
  have, and Aito *would* find it via composite `where`. We don't
  do that here; the search space explodes and the demo gets
  unfocused.
- **Promote / Dismiss aren't reversible** in the demo. Production
  would want an "Unpromote" path that closes the original audit
  entry rather than appending a new one.

## What this demo abstracts away

- **Promote → policy-export**. The demo's Promote button records an
  audit entry but doesn't export the rule anywhere. Production wires
  Promote into your real rules engine (Drools, ERP rule table, the
  hardcoded `RULES` list in `po_service.py`) so the next prediction
  call short-circuits on the promoted pattern. The audit log is the
  source of truth; the rules engine is the runtime.
- **Reversible un-promote with lineage**. Promotion in the demo is
  one-way. Production un-promote needs to close the original audit
  entry (not delete it), capture the reason, and re-emit the
  candidate the next time mining runs.
- **Multi-condition mining**. The demo mines single-field → field
  patterns. Real procurement rules often look like
  `category=security AND amount > 5000 → CFO`. Aito's `_relate`
  supports composite `where` conditions; the search space explodes
  combinatorially, so production wants a *seeded* miner that mines
  combinations ranked by user-curated priors rather than blindly.

## Try it live

[**Open Rule Mining**](http://localhost:8400/rules/) and Promote
the strongest candidate; the audit entry shows up in the side
panel.

```bash
./do dev   # starts backend + frontend
```

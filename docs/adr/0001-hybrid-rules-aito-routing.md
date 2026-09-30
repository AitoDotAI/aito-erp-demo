# ADR 0001: Hybrid rules + Aito routing for PO Queue

**Status:** Accepted, amended 2026-09-30 (see "Amendment" at the end)
**Date:** 2026-04
**Deciders:** Demo team

## Context

Every predictive ERP demo has to answer: should *every* prediction go
through Aito, or should hardcoded rules cover the deterministic cases?

The temptation is "Aito for everything" because it makes the marketing
story cleaner ("no rules, no maintenance"). But three of the demo's
canonical suppliers are 100% deterministic: Elenia is *always*
Facilities/6110, Telia is *always* IT/5510, Elisa is *always*
IT/5510. Routing them through Aito means:

- Spending a `_predict` call on a decision a one-line dict could make
- Showing 99% confidence numbers that look manufactured
- Inviting "but this is just a lookup" objections

## Decision

We use a **hybrid approach** in `po_service.predict_single`:

1. Check a small `RULES` list of hardcoded patterns first
2. Fall back to `_predict` for the long tail
3. Tag each prediction with `source` ∈ {`rule`, `aito`, `review`}

The frontend renders rule matches with a green `📋` badge and Aito
predictions with a gold `🤖` badge. Low-confidence Aito predictions
(`p < 0.50`) get a red `?` badge and are flagged for review.

## Consequences

**Good:**
- Demo story is honest: "rules cover what rules can; Aito covers the gap"
- The Rule Mining view becomes the natural narrative bridge — "candidates
  graduate to rules over time, reducing Aito's load"
- Testing is simpler — rule paths are deterministic
- Performance is better — 3 predict calls saved per rule-matched PO

**Bad:**
- Two code paths to maintain
- Adding a new rule requires a code deploy (a real implementation
  would store rules in a DB table)
- Reviewers ask "why hardcode rules instead of letting Aito learn?"
  The answer — Aito *did* learn them, but a 99% pattern with infinite
  support is worth promoting to a rule for cost and explicitness — is
  visible in the Rule Mining view but takes a beat to explain

## Alternatives considered

- **All Aito**: rejected (above)
- **All rules**: rejected — defeats the purpose of the demo
- **Aito with a confidence-based bypass cache**: too clever; the
  hybrid model maps to how real ERPs evolve (rule policy + ML fill-in)

## Amendment (2026-09-30): a rule decides only what it measurably decides

The premise above did not survive measurement against the loaded
history. Elenia and Telia code to 6110 / 5510 on 94-97% of their POs,
but "Facilities" and "IT" are not cost centres in the data at all, the
approvers the rules named were right 0 times in N for most suppliers,
and Metsä's Elisa rule matched no purchases. Every rule row nevertheless
showed a constant 0.99 on all three fields.

So a rule now names only the fields its supplier's history bears out
at `RULE_MIN_PRECISION` (0.90) or better; `measure_rule` counts that
precision from the history and refuses a rule below it, and the row
shows the count ("right on 140 of 145 POs") instead of 0.99. Every
field a rule does not set is Aito's, and the row is judged by the same
review bar as any other — which is why most rule rows read
"Rule, check approver". The accounting demo's ADR 0028 made the same
decision. The text above is kept as written; the numbers in it are the
part that was wrong.

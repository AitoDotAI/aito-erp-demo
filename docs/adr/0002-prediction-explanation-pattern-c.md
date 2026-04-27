# ADR 0002: Pattern C (anchored popover) for prediction explanations in ledger views

**Status:** Accepted
**Date:** 2026-04
**Deciders:** Demo team

## Context

The [prediction explanations guide](https://aito.ai/docs/guides/prediction-explanations)
identifies three valid placements for a `$why` UI:

- **Pattern A**: inline expanded panel below the row
- **Pattern B**: side panel paired with the form
- **Pattern C**: hover/click popover anchored to the predicted field

The ERP demo has 11 views with very different shapes — single-record
forms, ledger-style tables with 6-50 rows, and dashboards.

## Decision

We use **Pattern C** as the default for ledger views (PO Queue,
Approval, Catalog, Anomalies) and **Pattern B** for the single-record
form (Smart Entry).

Both are powered by the same `PredictionExplanation` pure component;
only the wrapper differs:

- `WhyPopover` → portal-mounted, anchored to a `?`/`!` button next to a
  predicted value
- Smart Entry side panel → renders `PredictionExplanation` inline, no
  portal

This is the recommendation in the guide ("C as the default and A as a
drill-down; B for forms"); we considered all three and the workflow fit
is clearest this way.

## Consequences

**Good:**
- Same `PredictionExplanation` component renders in both contexts
  (DRY; no duplicate "why" UI to maintain)
- Ledger users get peek-on-hover without losing scroll position
- The `!` button at low confidence is impossible to miss — pulses red,
  alerts the eye
- Cross-highlight (input fields outline in purple when their popover
  is open) works in both wrappers

**Bad:**
- Portal-mounted popover requires manual click-outside / scroll /
  Escape handling — about 30 lines of imperative code in `WhyPopover`
- Mobile experience is awkward; the popover doesn't scale to small
  viewports without redesign
- Z-index ordering is a sharp edge (the popover lives in
  `document.body`, so any subsequent `position: fixed` element with
  higher z-index can occlude it)

## Alternatives considered

- **Pattern A everywhere**: rejected — forces single-row review, breaks
  the scroll position in ledger views
- **Tooltip library**: rejected — none of the popular ones (Tippy,
  Floating UI) handle the cross-highlight feedback to input fields
  cleanly without prop drilling

# Architecture Decision Records

Short writeups of non-obvious choices made during the Predictive ERP
demo build. Each ADR explains the context, the decision, and what was
considered before settling.

| ADR | Title |
|-----|-------|
| [0001](0001-hybrid-rules-aito-routing.md) | Hybrid rules + Aito routing for PO Queue |
| [0002](0002-prediction-explanation-pattern-c.md) | Pattern C (anchored popover) for prediction explanations in ledger views |
| [0003](0003-sentinel-tag-highlights.md) | Sentinel-tag highlights instead of `dangerouslySetInnerHTML` |
| [0004](0004-three-state-smartfield.md) | Three-state SmartField (one field per concept) |

ADRs are append-only — if a decision is reversed, write a new ADR that
references the original. They are *not* a substitute for living
documentation in the code; they explain why the code looks the way it
does, not what it does.

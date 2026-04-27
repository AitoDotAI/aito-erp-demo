# Predictive ERP — Demo Script

A 2-minute walkthrough for live demos, screen recordings, and sales calls.
Each scene maps to one of the 11 views and the specific Aito feature it
demonstrates.

---

## Setup (one-time)

```bash
cp .env.example .env                    # Add Aito credentials
./do setup                              # Install deps
python3 data/generate_fixtures.py        # Generate ~12K records (deterministic)
./do load-data                          # Upload to Aito
./do dev                                # Start servers
# Open http://localhost:8400
```

The dataset is **2 819 purchases × 1 500 products × 5 000 orders × 2 900
prices** spanning 24 months. Big enough to feel like a real ERP, small
enough that the Aito free tier handles it.

---

## Scene 1 — PO Queue (45s)

**Open:** `/po-queue/`

**Say:** "47 POs received today, 14 still unrouted. Two are handled by a
hardcoded rule — Elenia is always Facilities, Telia is always IT. The
others go to Aito.

> Click `?` next to *Production* on the Wärtsilä row (PO-7842).

The popover shows base rate (23%), the matching pattern *supplier:
Wärtsilä Components × description: hydraulic seals* with lift × 3.1, the
math chain `23.3% × 3.14 × 2.92 × 0.43 = 91%`, and three alternatives.
That's auditable — not a black box.

> Click the red `!` on the Berner row.

This one's flagged: confidence under 50%, the `!` pulses red. The
popover shows the model has signal, but it's split across alternatives.
Worth a human's 10 seconds; either choice trains the system."

**Aito feature shown:** `_predict`, hybrid rule + Aito routing, confidence
gating

---

## Scene 2 — Smart Entry (30s)

**Open:** `/smart-entry/`

**Say:** "New PO form. Watch the predicted fields when I select a supplier.

> Select 'Lindström Oy' from the dropdown.

Four fields filled in one query — *Production*, *4810*, *OPEX-2023*,
*T. Virtanen*. This is a single multi-field `_predict` call against
purchase history. The user can override any field, and that override
becomes training data automatically — no separate ML pipeline."

**Aito feature shown:** Multi-field `_predict` (one query, N predictions)

**Key talking point:** "5 fields, ~18ms, no model training"

---

## Scene 3 — Approval Routing (30s)

**Open:** `/approval/`

**Say:** "Three POs awaiting escalation.

> Click `?` next to the predicted approver on Abloy Oy €6,100.

The popover shows the math: 12.2% base rate for R. Leinonen × 5.2 lift
from `category: security` × 1.57 from `supplier: Abloy Oy` = 99%. That
99% comes from 19 historical security-spend escalations. The system
*surfaces* this as a routing suggestion; it stays a suggestion until
governance promotes it via Rule Mining with explicit signoff and an
audit-trail entry. Traditional ERP makes you write the rule from
scratch; this lets the data propose it and humans ratify it.

> Click Siemens Finland €22,400.

Same flow for the capex >€20K → Board pattern."

**Aito feature shown:** `_predict` for approval levels with $why; rule
candidates surface for governance, not auto-applied

---

## Scene 4 — Anomaly Detection (45s)

**Open:** `/anomalies/`

**Say:** "Three transactions flagged with anomaly scores.

> Click PO-7812 Fazer €14,200.

Fazer is always coded to 5710 — catering. This invoice was coded to 4220 —
raw materials. Anomaly score 100, severity high. This is *inverse prediction*:
we asked Aito 'what account would you predict for Fazer?' and the actual
value had near-zero probability.

> Click PO-7799 Harjula Consulting.

Unknown vendor, no transaction history — also high score. Could be a new
legitimate supplier or a ghost vendor. Either way: review before paying."

**Aito feature shown:** Inverse prediction for anomaly scoring (low p =
high anomaly)

---

## Scene 5 — Supplier Intelligence (30s)

**Open:** `/supplier/`

**Say:** "Spend table on the left, delivery risk on the right. The risk
column comes from `_relate` — we asked Aito 'what predicts late delivery?'
without specifying any rules.

The answer: Elenia in winter months has 16.8% late rate, lift 2.6×. Neste
in Q4 is 33.8%, lift 1.4×. These patterns aren't in any spreadsheet — they
were discovered from the data."

**Aito feature shown:** `_relate` for risk discovery

---

## Scene 6 — Rule Mining (30s)

**Open:** `/rules/`

**Say:** "21 candidate rules surfaced this week. Each has a condition, a
predicted target, support count, and lift score.

The first one — `category=telecom → IT cost center, 5.1× lift, 100%
support` — could be promoted to a hardcoded rule, freeing Aito to focus on
the harder cases. This is the lifecycle: Aito handles ambiguous decisions,
and as patterns solidify, they migrate to rules."

**Aito feature shown:** `_relate` with strength thresholds

---

## Scene 7 — Catalog Intelligence (45s)

**Open:** `/catalog/`

**Say:** "1 500 products in the catalog. 69 are workflow-blocking —
missing the fields that prevent invoicing, quoting, or customs export.
Services with null shipping data don't count; only real blockers do.

> Click 'Auto-apply >85% confidence' at the top.

One click ran 69 predictions; the system applied the high-confidence
ones across the whole catalog. The confirmation says these become
training data — every correction makes future predictions better, no
retraining required.

> Click any single product row, then 'Apply predictions'.

Same flow per row when a category lead wants to review one product
manually. Each predicted field has a `?` showing why it was chosen."

**Aito feature shown:** Multi-field `_predict` + bulk apply + training
loop closure

---

## Scene 8 — Price Intelligence (30s)

**Open:** `/pricing/`

**Say:** "Wärtsilä Seal Kit, fair price €147, range €135-158. The chart
shows historical orders, similar items, and a flagged quote at €189 from
Parts Direct — 28.9% above the predicted range.

> Point to the flagged quote.

That's real money: €41 over the fair price. At 10 units a month, that
supplier is costing us €4,920 a year on this one item. The system catches
it without anyone writing pricing rules."

**Aito feature shown:** Statistical price estimation, quote scoring

---

## Scene 9 — Demand Forecast (30s)

**Open:** `/demand/`

**Say:** "Six products, 30-day forecast each. Same data as the pricing
view, different question — *how many will we need?* instead of *what's the
fair price?*

The seasonality is discovered automatically. Workwear August spike, fuel
July dip, maintenance March/September peaks — never manually configured.
The system found these patterns in three years of order history."

**Aito feature shown:** `_predict` on numerical fields + seasonal patterns

---

## Scene 10 — Inventory Intelligence (30s)

**Open:** `/inventory/`

**Say:** "Stock levels meet demand forecast. Two items low, three
overstock.

> Point to SKU-4421 Wärtsilä Seal Kit.

22.5 days of supply, 14-day lead time. Tight margin — reorder soon or risk
a production stoppage.

> Point to SKU-FUEL.

980 units in stock, 700 days of supply. €19K of working capital tied up.
That's a policy recommendation, not just a data point — reduce safety
stock to free cash."

**Aito feature shown:** Demand forecast + stock arithmetic, substitution
suggestions

---

## Scene 11 — Automation Overview (30s)

**Open:** `/overview/`

**Say:** "The CFO view. €220 K saved YTD: 29 hours of labor reclaimed
plus mis-postings prevented before they hit the close.

> Read the 'How to read this' band.

72% of POs ship without anyone touching them — 22% via deterministic
rules, 50% via aito.. high-confidence predictions. The remaining 28%
goes to a human, not because aito.. failed, but because those are
the cases worth a second look — new vendors, ambiguous descriptions,
amounts that break the supplier's pattern.

> Point to the learning curve.

29 months of `routed_by` data, computed live. Early months ran lower
because Aito needed history; the latest months are over 75%."

**Aito feature shown:** Automation breakdown, real learning curve from
purchases table

---

## Closing line

> "What you just saw runs against your transaction history directly. No
> data scientist, no model training, no MLOps. Aito turns the database
> itself into a prediction engine — and every override teaches it
> something."

---

## Sales engineering notes

- **Don't apologize for low confidence numbers.** Honest uncertainty is
  the feature. Rule-only systems can't tell you when they're guessing.
- **Highlight the closed loop.** The Apply button in Catalog and the
  override flow in Smart Entry are how the system learns from production
  use without retraining.
- **The 21% number is real.** Rules-based ERP plateaus there because
  someone has to write each rule. Aito doesn't.
- **Schema matters.** Each table represents a real ERP entity. Aito learns
  cross-table relationships through link declarations in the schema.

---

## Troubleshooting during the demo

| Symptom | Fix |
|---------|-----|
| Empty data | `./do load-data` to re-upload fixtures |
| Stale predictions | `./do clear-cache && ./do restart` |
| Slow first load | Cache warming runs on startup; second visit is instant |
| Network errors | Check `.env` has valid `AITO_API_URL` and `AITO_API_KEY` |

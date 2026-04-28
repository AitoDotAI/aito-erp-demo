// Aito Predictive ERP — Product Sheet
// Compile: typst compile docs/product-sheet/product-sheet.typ docs/product-sheet/product-sheet.pdf

#set page(
  paper: "a4",
  margin: (x: 2cm, y: 2.5cm),
  footer: context [
    #set text(8pt, fill: luma(150))
    #h(1fr) Aito Predictive ERP · ERP that learns from your transactions #h(1fr)
    #counter(page).display()
  ],
)

#set text(size: 10pt, fill: luma(30))
#show heading.where(level: 1): set text(size: 18pt, weight: 700)
#show heading.where(level: 2): set text(size: 14pt, weight: 600)
#show heading.where(level: 3): set text(size: 11pt, weight: 600)

#let gold = rgb("#d4a030")
#let teal = rgb("#12B5AD")
#let purple = rgb("#9B69FF")
#let nav = rgb("#0c0f0a")
#let aitobg = rgb("#0c0f41")
#let muted = luma(120)

#let feature(title, description, icon: none) = {
  box(
    width: 100%,
    inset: 12pt,
    radius: 6pt,
    stroke: luma(220),
    [
      #if icon != none { text(size: 14pt, icon + " ") }
      #text(weight: 600, size: 11pt, title) \
      #text(size: 9.5pt, fill: luma(80), description)
    ]
  )
}

// ────────────────────────────────────────────────────────────
// Cover
// ────────────────────────────────────────────────────────────

#v(3cm)

#align(center)[
  #text(size: 13pt, fill: muted, weight: 500)[Aito.ai · Predictive Database for ERP]

  #v(0.3cm)

  #text(size: 30pt, weight: 700, fill: luma(20))[The ERP That Learns]

  #v(0.2cm)

  #text(size: 16pt, fill: luma(60), weight: 500)[
    From transaction history. Without training. Without rules.
  ]

  #v(0.6cm)

  #text(size: 11pt, fill: luma(80))[
    14 production-ready ERP features built on a single predictive database. \
    PO coding · approver routing · anomaly detection · demand forecast · inventory \
    replenishment · project success · price intelligence — all from one query API.
  ]

  #v(2cm)

  #image("screenshots/01-po-queue.png", width: 95%)
]

#pagebreak()

// ────────────────────────────────────────────────────────────
// The Challenge
// ────────────────────────────────────────────────────────────

= The Challenge

ERP automation traditionally means writing rules. A coding rule per supplier. A routing rule per category. A threshold rule per approval level. Each rule starts useful, drifts as the business changes, and rots when nobody owns it. The 21% automation ceiling on rule-only systems is real — and the long tail beyond it is where time gets spent.

#v(0.3cm)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 12pt,
  feature("Coding rules don't scale", "A finance team coding €€€-thousands of POs monthly hits 2K supplier-account pairs in year one. The rules table becomes the bottleneck.", icon: "❓"),
  feature("Approvals drift from policy", "Hand-coded thresholds (security > €5K → CFO) get patched, exceptions, deprecations. Auditors ask 'why was this approved?' and nobody's sure.", icon: "⚠️"),
  feature("Anomalies are invisible", "Static thresholds miss context-dependent oddities: Fazer × account 4220 looks fine until you know Fazer is catering, not parts.", icon: "🔍"),
)

#v(0.8cm)

= The Solution

Aito is a predictive database. Load your transaction history; query for predictions, recommendations, and statistics through SQL-like calls. No model training. No retraining schedule. No MLOps. Every prediction comes with a `\$why` decomposition — base rate × pattern lift × pattern lift = final probability — that auditors can read.

#v(0.3cm)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 12pt,
  feature("Zero training", "Upload transactions, query immediately. The data is the model; new history improves predictions automatically.", icon: "⚡"),
  feature("Explainable by design", "Every prediction returns the multiplicative chain that produced it. No black box. Click the ? to see why.", icon: "📋"),
  feature("Multi-tenant native", "One DB per customer (or pooled by cohort). Switch a setting, get a different vertical's flavour. Three personas in one demo prove it.", icon: "🏢"),
)

#pagebreak()

// ────────────────────────────────────────────────────────────
// PO Queue
// ────────────────────────────────────────────────────────────

= Predictive PO Coding

Pending POs land in the queue with cost center, account code, and approver predicted from history. Hardcoded rules cover the deterministic patterns (Telia → IT/5510); Aito's `_predict` covers the long tail. Confidence-tier visualisation flags low-confidence rows for review before they post.

#image("screenshots/01-po-queue.png", width: 100%)

#v(0.3cm)

*What it answers:*
- _"Which account does this Wärtsilä PO post to?"_ — Aito returns "Production / 4220 / 91% confidence" with the supplier-and-description multiplicative chain
- _"Should I trust this prediction?"_ — Confidence ≥85% gets a faint `?`, 50-85% gets a gold `?`, under 50% gets a pulsing red `!` that demands review
- _"Why this approver and not that one?"_ — Click any predicted value to see the `\$why` factors and ranked alternatives

Bulk-approve all rule-matched rows or all high-confidence Aito predictions in one click. Each approval becomes a confirmed training signal for the next prediction.

#pagebreak()

// ────────────────────────────────────────────────────────────
// Smart Entry
// ────────────────────────────────────────────────────────────

= Smart Entry — Multi-Field Prediction

Picking a supplier from the dropdown triggers four `_predict` calls in parallel. Cost center, account code, project, and approver fill in at once with per-field confidence. Tab promotes a prediction; Esc rejects it; typing replaces it. Click `?` on any field to see the input fields that contributed — they highlight in purple.

#image("screenshots/02-smart-entry.png", width: 100%)

#v(0.3cm)

*Three visual states per field:*

#box(
  width: 100%,
  inset: 14pt,
  radius: 6pt,
  fill: luma(248),
  stroke: luma(230),
  [
    #text(size: 10pt, fill: luma(60))[
      *Empty* — neutral placeholder, no prediction yet \
      *Predicted* — gold-italic value with 🤖 badge, confidence indicator, ? trigger \
      *User* — black text, no badge, treated as ground truth on submit
    ]
  ]
)

#v(0.2cm)

The pattern matches Aito's smart-forms guide: the user sees one DOM input per concept, regardless of whether the value came from history or from typing. No "would you like to fill this in?" modal — the prediction *is* the value, just with a different look.

#pagebreak()

// ────────────────────────────────────────────────────────────
// Anomaly Detection
// ────────────────────────────────────────────────────────────

= Anomaly Detection — Inverse Prediction

Every transaction scored by how likely its actual values are, given the rest. Score = `(1 - p_actual) × 100`. Three flag types: mis-coded account, unknown vendor, amount spike. No rules to configure; no thresholds to maintain.

#image("screenshots/04-anomalies.png", width: 100%)

#v(0.3cm)

*What it catches:*
- *Mis-coded accounts* — Fazer (catering) on account 4220 (production parts) flags at 91. Aito *expected* 5710 with 89% confidence
- *Unknown vendors* — Harjula Consulting has no purchase history; the supplier-itself is the anomaly
- *Amount spikes* — Neste fuel order at €9,800 against a €2,400 average flags at 82

Click any flag to see the multiplicative chain that makes the actual value improbable. Action buttons (Investigate / Escalate / Mark legitimate) close the loop — Legitimate decisions feed back into the next score so the same pattern stops flagging.

#pagebreak()

// ────────────────────────────────────────────────────────────
// Intelligence layer (Supplier + Rules) — 2-up
// ────────────────────────────────────────────────────────────

= Intelligence Layer

#grid(
  columns: (1fr, 1fr),
  gutter: 16pt,
  [
    == Supplier Intel

    Spend leaderboard plus delivery-risk discovery via `_relate`. Aito surfaces patterns like "Neste lifts 1.4× on Q4 lateness" or "Elenia 2.6× on winter outages" without anyone writing the rule.

    #image("screenshots/05-supplier.png", width: 100%)
  ],
  [
    == Rule Mining

    Discovered patterns ranked by confidence and support. "category=telecom → IT, lift 5.1×, 100% over 17 cases" becomes a Promote candidate; weaker patterns wait for more data.

    #image("screenshots/06-rules.png", width: 100%)
  ],
)

#v(0.5cm)

Intelligence is not magic. `_relate` returns lift × support; the human reads the cause. Promote a pattern with explicit governance signoff and it joins the hardcoded rules in the routing layer. Dismiss it and the same pattern doesn't resurface. The audit trail is the source of truth.

#pagebreak()

// ────────────────────────────────────────────────────────────
// Forecasting (Demand + Inventory) — 2-up
// ────────────────────────────────────────────────────────────

= Forecasting & Replenishment

#grid(
  columns: (1fr, 1fr),
  gutter: 16pt,
  [
    == Demand Forecast

    Historical consumption combined with seasonal factors. Workwear August lifts 2.3×; fuel July dips to 0.65×. Forecasts blend Aito's `_predict` with same-month aggregates — confidence scales with sample size.

    #image("screenshots/09-demand.png", width: 100%)
  ],
  [
    == Inventory Intelligence

    Stockout risk × cash impact. Critical / Low / OK / Overstock with €€€ tied capital and weekly margin at risk. "Reorder now" creates a real PO that flows to the PO Queue and Approval.

    #image("screenshots/10-inventory.png", width: 100%)
  ],
)

#v(0.5cm)

Demand drives reorder; reorder routes through PO Queue's prediction layer; the new PO's outcome feeds back into next cycle's demand forecast. The whole replenishment loop runs on a single Aito table — no ML pipeline, no nightly batch, no separate forecasting service.

#pagebreak()

// ────────────────────────────────────────────────────────────
// Vertical-flexibility story — three personas
// ────────────────────────────────────────────────────────────

= One Codebase. Three Verticals.

The same code drives three industry profiles, each with its own Aito DB and persona-appropriate fixtures. Switch in the TopBar — the right-rail Aito panel re-tones with persona-specific examples; the side nav filters which views appear; the data behind each prediction comes from that tenant's history.

#v(0.3cm)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 12pt,
  feature(
    "Metsä Machinery",
    "Industrial maintenance / construction. Wärtsilä, ABB, Caverion, NCC. 3.2K POs · 320 spare-part SKUs · 285 maintenance/construction projects.",
    icon: "🏭"
  ),
  feature(
    "Aurora Retail",
    "Multi-channel commerce. Valio, Marimekko, L'Oréal. 5.3K POs · 3.2K SKUs · 18K orders · 6.5K price points · cross-sell + similar-products.",
    icon: "🛍"
  ),
  feature(
    "Helsinki Studio",
    "Professional services. Adobe, AWS, Figma. 3.2K POs · 435 client engagements · 2.1K assignments · project portfolio + utilization views.",
    icon: "💻"
  ),
)

#v(0.6cm)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 8pt,
  image("screenshots/00-landing-metsa.png", width: 100%),
  image("screenshots/00-landing-aurora.png", width: 100%),
  image("screenshots/00-landing-studio.png", width: 100%),
)

#v(0.3cm)

#text(size: 9.5pt, fill: muted)[
  Metsä's panel quotes Wärtsilä → account 4220. Aurora's quotes Valio → account 4010. Studio's quotes Adobe → account 5530. Same component; persona-specific content drives credibility per-vertical without rebuilding the UI.
]

#pagebreak()

// ────────────────────────────────────────────────────────────
// How It Works
// ────────────────────────────────────────────────────────────

= How It Works

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 12pt,
  feature(
    "1. Connect your data",
    "GL / ERP exports → Aito instance. JSON or CSV; schema auto-detected. ~12K rows uploads in under a minute.",
    icon: "📤"
  ),
  feature(
    "2. Query for predictions",
    "Five operators cover all 14 use cases:\n• _predict: classify\n• _relate: discover patterns\n• _evaluate: anomaly score\n• _search + _match: retrieval",
    icon: "🔮"
  ),
  feature(
    "3. Integrate",
    "REST API. ~30ms response time. Sub-1ms on warm-cache. Three-tier rate limit + per-tenant cache built in. Drop into your existing ERP or build standalone.",
    icon: "🔗"
  ),
)

#v(0.6cm)

== Architecture at a glance

#box(
  width: 100%,
  inset: 14pt,
  radius: 6pt,
  fill: luma(248),
  stroke: luma(230),
  [
    #text(size: 10pt, fill: luma(60))[
      *Backend* — Python FastAPI · one service module per business capability \
      *Frontend* — Next.js 16 (App Router) · TypeScript strict · per-tenant routing via X-Tenant header \
      *Aito* — REST API · `_predict` / `_relate` / `_evaluate` / `_search` / `_match` \
      *Cache* — Two-layer (in-memory + Aito-backed); per-tenant scoped keys \
      *Scaling* — Per-tenant DBs at 1K customers; pooled at 10K; pre-computed at 100K \
      *Public-demo mode* — `PUBLIC_DEMO=1` toggles CORS lockdown, three-tier rate limit, memory-only cache
    ]
  ]
)

#pagebreak()

// ────────────────────────────────────────────────────────────
// Project + Recommendations + Overview teasers
// ────────────────────────────────────────────────────────────

= Beyond Procurement

The same query patterns reach further than the AP department. Three views ship in the demo for verticals where procurement isn't the centre of gravity.

#v(0.4cm)

#grid(
  columns: (1fr, 1fr),
  gutter: 12pt,
  [
    == Project Portfolio

    Predicted P(success) per active project + staffing simulator. `_predict success=true` per project; `_relate` over assignments surfaces which people boost which project types. Swap a team member, watch the probability move.

    #image("screenshots/11-projects.png", width: 100%)
  ],
  [
    == Recommendations *(Aurora)*

    Cross-sell + similar products from a single Aito DB. Anchor a SKU, see "frequently bought together" (basket co-occurrence with lift) and "similar products" (attribute-overlap match). Recursive — click any result to make it the new anchor.

    #image("screenshots/13-recommendations.png", width: 100%)
  ],
)

#v(0.5cm)

== Automation Overview

A real learning curve, not a slope-fitting trick. Every PO is tagged `routed_by` (rule / aito / human); the curve plots automation rate over `order_month` filtered to months with ≥5 POs. €220K savings YTD with a collapsible methodology footnote pointing back at the constants.

#image("screenshots/14-overview.png", width: 100%)

#pagebreak()

// ────────────────────────────────────────────────────────────
// What this demo deliberately does not show
// ────────────────────────────────────────────────────────────

= What This Demo Doesn't Try to Be

This is a *predictive-database reference*, not a complete ERP. The capabilities the demo deliberately omits — and what production would add — are documented openly. A non-exhaustive list:

#v(0.3cm)

#grid(
  columns: (1fr, 1fr),
  gutter: 12pt,
  [
    *Three-way matching* — PO ↔ goods receipt ↔ invoice. The demo stops at PO routing; production wires invoice line-items against the predicted account_code at receipt time.

    *GL period control* — predicted accounts don't check whether the period is open. Production gates posting on `period_open=true` for the posting date.

    *Multi-country chart of accounts* — single Finnish CoA hardcoded. Production adds a per-customer mapping table; predictions return account in the source CoA, integration remaps to the destination tenant's accounts.
  ],
  [
    *Multi-entity / multi-currency* — single legal entity, all EUR. Production adds `entity_id` and FX rates in side tables; same multi-tenant routing pattern shown in `aito-accounting-demo`.

    *Audit-trail persistence* — override events aren't persisted across restarts. Production wants `prediction_log(prediction_id, user, accepted, overridden_to, \$why_snapshot, ts)`.

    *e-Invoice / verkkolasku / ALV* — Finnish invoice formats aren't generated. Wire to Maventa / Apix; predictions feed line-item coding before serialisation.
  ],
)

#v(0.5cm)

#text(size: 9.5pt, fill: muted)[
  Owning the gaps is more credible than papering over them. Each row above is a real objection raised by ERP-SaaS CTOs reviewing the demo. Production checklist + scaling guidance lives in `docs/scaling.md` in the repo.
]

#pagebreak()

// ────────────────────────────────────────────────────────────
// CTA
// ────────────────────────────────────────────────────────────

= Ready to Try It?

#v(0.4cm)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 12pt,
  feature(
    "Read the code",
    "Apache 2.0 on GitHub. 14 use-case guides. 39 pytest tests. Production-quality reference — fork it for your vertical.",
    icon: "📖"
  ),
  feature(
    "Run it locally",
    "./do setup && ./do load-data && ./do dev. Three-persona switcher in the TopBar. Bring your own Aito API key (free tier covers 10K rows).",
    icon: "🚀"
  ),
  feature(
    "Talk to us",
    "If your ERP-SaaS roadmap has predictive automation on it, we should talk. We've done multi-tenant onboarding before — see the accounting demo (256 customers, ~250K invoices).",
    icon: "💬"
  ),
)

#v(1.2cm)

#box(
  width: 100%,
  inset: 20pt,
  radius: 8pt,
  fill: aitobg,
  [
    #text(fill: white, size: 11pt)[
      #text(weight: 600, size: 13pt)[Predictive intelligence for your ERP — without the ML pipeline]

      #v(0.3cm)

      Aito.ai is a predictive database. Upload transactions, query for predictions, ship features. The 14 capabilities in this demo are the same query API you'd use in production — sub-100ms `_predict` calls, full `\$why` explanations, and override-as-training-signal built in.

      #v(0.3cm)

      #text(fill: teal, weight: 500)[hello\@aito.ai · aito.ai · github.com/AitoDotAI/aito-erp-demo]
    ]
  ]
)

#v(0.5cm)

#align(center)[
  #text(size: 9pt, fill: muted)[
    Aito.ai builds predictive infrastructure for product teams who want statistical intelligence \
    without standing up an ML team. Open-source demos: aito-demo · aito-accounting-demo · aito-erp-demo.
  ]
]

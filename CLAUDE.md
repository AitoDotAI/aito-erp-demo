# CLAUDE.md — Predictive ERP Demo

## What this project is

This is a public, open-source reference project demonstrating Aito.ai's
predictive database applied to ERP workflows. It shows how transaction
history alone — no model training, no configuration — can automate the
decisions ERP users make manually every day: account codes, approvers,
reorder points, price validation, anomaly detection.

It serves three purposes simultaneously:

1. **Sales demo** — self-explanatory with no narrator; the Aito side panel
   does the explaining. Target audience: ERP-SaaS CTOs evaluating
   predictive automation in industrial / retail / professional-services
   verticals.
2. **Product vision** — shows what an ERP becomes when predictions are
   native, not bolted on
3. **Reference implementation** — production-quality code that developers
   evaluate when considering Aito integration

The code IS the sales collateral. Every file, interaction, and explanation
contributes to or detracts from that impression.

---

## Prime directives

These never relax.

1. **Diagnose before you fix.** If you don't understand why something is
   broken, stop and say so. Don't stack workarounds.

2. **Never silently filter, coerce, or discard unexpected data.** Assert
   and fail loudly. Silent handling hides bugs and teaches wrong patterns
   to developers reading this code.

3. **Aito queries are not in your training data.** Never invent query
   shapes, endpoints, or field semantics. Consult `docs/aito-cheatsheet.md`,
   the existing service modules under `src/`, and the Aito API
   documentation for query patterns. When unsure: write the query,
   verify the response structure, and confirm it matches expectations
   before building on it.

4. **Write for the reader, not the machine.** Every file will be read by a
   developer evaluating whether to adopt Aito. Name things clearly. Keep
   files focused. Let structure tell the story.

5. **Preserve the design system.** The palette, typography, and component
   styles documented in this CLAUDE.md (under "Design system") are final.
   Do not deviate.

---

## Project structure

```
├── CLAUDE.md                          # You are here
├── README.md                          # Public-facing demo description
├── pyproject.toml                     # Python dependencies
├── .env.example                       # Aito credentials template
├── do                                 # Task runner
├── shell.nix                          # Nix dev environment
│
├── src/                               # Python FastAPI backend
│   ├── app.py                         # FastAPI main, all endpoints
│   ├── config.py                      # Env loading
│   ├── aito_client.py                 # Thin Aito REST wrapper
│   ├── cache.py                       # Two-layer cache (memory + Aito)
│   ├── rate_limit.py                  # IP-based rate limiting
│   ├── data_loader.py                 # Schema + fixture upload
│   ├── po_service.py                  # PO Queue (_predict)
│   ├── smartentry_service.py          # Smart Entry (multi-field _predict)
│   ├── approval_service.py            # Approval Routing (_predict)
│   ├── anomaly_service.py             # Anomaly Detection (_evaluate)
│   ├── supplier_service.py            # Supplier Intel (_relate)
│   ├── rulemining_service.py          # Rule Mining (_relate)
│   ├── catalog_service.py             # Catalog Intelligence (_predict)
│   ├── pricing_service.py             # Price Intelligence (_estimate)
│   ├── demand_service.py              # Demand Forecast (_estimate)
│   ├── inventory_service.py           # Inventory Intelligence
│   └── overview_service.py            # Automation Overview
│
├── frontend/                          # Next.js 16 (App Router)
│   ├── app/
│   │   ├── layout.tsx                 # Root layout + Google Fonts
│   │   ├── globals.css                # Full design system
│   │   ├── po-queue/page.tsx
│   │   ├── smart-entry/page.tsx
│   │   ├── approval/page.tsx
│   │   ├── anomalies/page.tsx
│   │   ├── supplier/page.tsx
│   │   ├── rules/page.tsx
│   │   ├── catalog/page.tsx
│   │   ├── pricing/page.tsx
│   │   ├── demand/page.tsx
│   │   ├── inventory/page.tsx
│   │   └── overview/page.tsx
│   ├── components/
│   │   ├── shell/                     # Nav, TopBar, AitoPanel, ErrorState
│   │   └── prediction/               # PredictionBadge, ConfidenceBar,
│   │                                  # WhyTooltip, PredictedField
│   └── lib/
│       ├── api.ts                     # apiFetch, fmtAmount, confClass
│       └── types.ts                   # TypeScript interfaces
│
├── data/                              # JSON fixtures
│   ├── purchases.json                 # ~200 PO records
│   ├── products.json                  # ~50 product catalog
│   ├── orders.json                    # ~300 historical orders
│   └── price_history.json             # ~200 pricing records
│
├── tests/                             # pytest
└── docs/
    ├── adr/                           # Architecture Decision Records
    └── aito-cheatsheet.md             # Verified query patterns
```

---

## Architecture

- **Backend**: Python FastAPI on port 8200
- **Frontend**: Next.js (App Router), dev on port 3000 with API proxy
- **Aito**: Thin HTTP client (`src/aito_client.py`) wrapping REST endpoints
- **Services**: One Python module per view, each calling Aito directly
- **Cache**: Two-layer (in-memory + Aito table) with startup warming
- **Data**: JSON fixtures uploaded to Aito via `./do load-data`
- **Demo profiles**: A TopBar switcher selects between three tenant
  personas (Metsä Machinery / Aurora Retail / Helsinki Studio).
  Frontend config lives in `frontend/lib/tenants.ts`; persisted in
  `localStorage` under `demoTenant`. Each profile filters the side
  nav so only the views relevant to that audience appear.

- **Multi-tenant Aito routing**: When `AITO_METSA_*` /
  `AITO_AURORA_*` / `AITO_STUDIO_*` are set in `.env`, the backend
  builds one `AitoClient` per persona. `apiFetch` stamps every
  request with `X-Tenant: <id>` (read from `localStorage`); the
  backend resolves the right client per request and scopes cache
  keys per tenant via `cache.tenant_key()`. When per-tenant pairs
  are not set, all three personas fall through to the default
  `AITO_API_URL` / `AITO_API_KEY` — single-DB demos still work
  unchanged. Runtime endpoint: `GET /api/tenants` reports what the
  backend resolved (handy for ops sanity).

- **Per-tenant fixture universes**: `data/generate_personas.py`
  produces three industry-distinct datasets — different supplier
  rosters (Metsä: Wärtsilä/ABB/Caverion; Aurora: Valio/Marimekko;
  Studio: Adobe/AWS), different cost-centre vocabularies, different
  category mixes, and different scales (Aurora: 3.2k purchases +
  1.8k SKUs + 9.5k orders for a retail vibe; Studio: 970 purchases
  + 235 client-engagement projects for a services vibe). Each tenant
  also gets its own `projects` + `assignments` tables with persona-
  appropriate project types (Metsä: maintenance/construction;
  Aurora: store-fitout/ecom-launch; Studio: design/strategy/retainer).
  `data_loader.py` reads `data/<tenant>/<table>.json` first and
  falls back to the flat `data/<table>.json` so partially-migrated
  setups still work. Run `./do generate-personas` then
  `./do load-data --tenant=all`.

### Data flow

```
Browser → Next.js page → fetch("/api/...") → FastAPI → AitoClient → Aito REST API
                                                 ↕
                                              cache (memory + Aito table)
```

---

## The `./do` script

```bash
./do dev              # Start FastAPI on :8200
./do frontend-dev     # Start Next.js on :3000 (proxy to :8200)
./do frontend-build   # Build static export
./do load-data        # Upload fixtures to Aito
./do reset-data       # Drop and reload all Aito tables
./do clear-cache      # Clear prediction cache
./do test             # Run pytest
./do setup            # Sync Python + npm dependencies
./do check            # Pre-merge gate (test + fmt)
```

---

## The 14 views

### Procurement
1. **PO Queue** — pending POs with predicted cost center, account, approver
2. **Smart Entry** — supplier dropdown triggers 5-field prediction
3. **Approval Routing** — escalation queue with predicted approval level

### Intelligence
4. **Anomaly Detection** — transactions scored by anomaly (_evaluate)
5. **Supplier Intel** — spend + delivery risk (_relate)
6. **Rule Mining** — patterns discovered from data (_relate)

### Product
7. **Catalog Intelligence** — missing product attributes predicted
8. **Price Intelligence** — fair price estimation + quote scoring
9. **Demand Forecast** — consumption prediction with seasonality
10. **Inventory Intelligence** — stockout alerts + reorder recommendations
11. **Recommendations** — cross-sell (`_search` co-occurrence) + similar
    products (`_match` over attributes). Aurora-only; Aito's flagship
    retail capability.

### Operations
12. **Project Portfolio** — predicted success for each active project
13. **Utilization & Capacity** — per-person current load + at-risk
    allocation + historical norm; "what if" forecast uses
    `_predict assignments.role|allocation_pct` filtered by the
    denormalised `project_type` column. Studio-only.
    (`_predict success=true`) + people-as-staffing-factors discovered
    by `_relate` over completed-project history. Backed by two new
    tables: `projects` (one row per project, with `team_members` as a
    tokenized Text field so Aito learns per-person effects) and
    `assignments` (canonical project_id × person × role).

### Overview
14. **Automation Overview** — coverage stats + learning curve

---

## Aito query patterns

| Service | Endpoint | Purpose |
|---------|----------|---------|
| po_service | `_predict` | Account code, cost center, approver |
| smartentry_service | `_predict` (multi) | 5 fields in one session |
| approval_service | `_predict` | Approval level |
| anomaly_service | `_evaluate` | Combination probability |
| supplier_service | `_relate` | Late delivery predictors |
| rulemining_service | `_relate` | High-confidence patterns |
| catalog_service | `_predict` (multi) | Missing product attributes |
| pricing_service | search + stats | Price range from history |
| demand_service | `_predict` + search | Units forecast |
| inventory_service | demand + stock | Days of supply + reorder |
| project_service | `_predict` + `_relate` | Project success forecast + staffing factors |

---

## Mock data principles

- Finnish supplier names: Elenia, Wärtsilä, Telia, Neste, Lindström, Abloy,
  Caverion, Fazer, Berner, Siemens Finland, Harjula Consulting
- SKU numbers: SKU-4421, SKU-8812, SKU-2234, SKU-9901, SKU-5560, SKU-FUEL,
  SKU-HVAC
- PO numbers: PO-7841 through PO-7846
- All numbers internally consistent across views

---

## Design system

Fonts: DM Serif Display, DM Mono, DM Sans (Google Fonts)

| Element | Value |
|---------|-------|
| Nav background | `#0c0f0a` |
| Main background | `#f8f6f0` |
| Card background | `#ffffff` |
| Gold accent | `#d4a030` / `#f5e9c8` / `#6b4f0e` |
| Aito panel bg | `#0c0f41` |
| Aito teal | `#12B5AD` |
| Aito purple | `#9B69FF` |

---

## Public-demo deployment

Set `PUBLIC_DEMO=1` in the deployed environment to enable:
- **CORS lockdown** to origins in `CORS_ORIGINS` (comma-separated).
- **Three-tier rate limiting** (per-IP, per-tenant, global) — caps
  configurable via `RATE_LIMIT_PER_IP` / `RATE_LIMIT_PER_TENANT` /
  `RATE_LIMIT_GLOBAL`. Localhost bypasses the per-IP tier so
  screenshot/booktest tooling still runs.
- **`/api/tenants`** returns just ids (no raw Aito URLs).
- **`/api/schema`** returns 404 (don't leak Aito table layout).
- **Submission sanitisation**: TTL-bounded queue (1h), 50-entry FIFO
  cap, per-field length clipping, control-char stripping, EUR
  amount clamped to [0, 1M].
- **Memory-only cache**: `init_persistent_cache` becomes a no-op.
  The Aito `prediction_cache` table isn't touched, so the demo
  works with read-only API keys. Trade-off: cold cache after every
  restart; warmup pays the predict cost again. Acceptable.

The landing page (`/`) is the public entry point: a three-tile
persona picker that sets the tenant in localStorage and routes to
its `defaultRoute`. Visitors can deep-link to `/po-queue/...` etc.
which bypasses the landing — that's intentional for sales links
that want to drop a CTO straight into a specific view.

Per-tenant Aito-panel content lives in `frontend/lib/panel-content.ts`.
Pages that all three personas see (PO Queue, Supplier Intel,
Anomalies — the universal-traffic surfaces) call `useTenant()` and
pull the persona-tailored config: Metsä's panel mentions Wärtsilä
and account 4220, Aurora's mentions Valio and account 4010, Studio's
mentions Adobe and account 5530. Switching personas in the TopBar
re-tones the panel without a route change.

## Autonomy rules

### Do autonomously
- Bug fixes that don't change interaction behaviour
- CSS adjustments within the design system
- Data consistency fixes across views
- Code formatting

### Propose before implementing
- Any new view or navigation item
- Changes to Aito query patterns shown in panels
- New colours, fonts, or component styles
- Adding external dependencies

### Stop and escalate
- Two failed attempts at the same bug
- Aito query syntax questions you can't resolve from the spec
- Changes that would alter the sales narrative
- Anything that breaks mobile collapsible panel behaviour

---

## Code style

- Python: PEP 8, dataclasses with `to_dict()`, functions take AitoClient first
- TypeScript: strict mode, `"use client"` on all interactive components
- CSS: custom properties for all design tokens, no hardcoded colours
- No external JS dependencies beyond React/Next.js
- Comments explain WHY, not WHAT

---

## What this project does NOT want

- **Speculative abstraction.** No interfaces or factories until the second use
- **Framework maximalism.** Vanilla CSS, minimal dependencies
- **Clever code.** Obvious > clever. Boring > smart
- **Coverage theater.** Tests that teach Aito usage, not boilerplate tests
- **Broken cross-view consistency.** SKU-4421 is a seal kit everywhere

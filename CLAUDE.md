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
│   ├── forecast_service.py            # Revenue Outlook (_predict on_time)
│   ├── planner_service.py             # Engagement Planner (staffing + quote risk)
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
├── data/                              # JSON fixtures (gitignored;
│                                      #   `./do generate-personas`)
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

- **Backend**: Python FastAPI on port 8401 (internal)
- **Frontend**: Next.js (App Router), dev on port 8400 with API proxy
- **Aito**: Thin HTTP client (`src/aito_client.py`) wrapping REST endpoints
- **Services**: One Python module per view, each calling Aito directly
- **Cache**: Two-layer (in-memory + Aito table) with startup warming
- **Data**: JSON fixtures uploaded to Aito via `./do load-data`
- **Demo profiles**: A TopBar switcher selects between three tenant
  personas (Metsä Machinery / Aurora Retail / Vire Consulting).
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
  Aurora: store-fitout/ecom-launch; Vire: implementation/strategy/
  discovery/design/retainer).
  `data_loader.py` reads `data/<tenant>/<table>.json` first and
  falls back to the flat `data/<table>.json` so partially-migrated
  setups still work. Run `./do generate-personas` then
  `./do load-data --tenant=all`.

- **Aito API v1 / v2**: `AITO_API_VERSION` picks the REST surface.
  v1 (rep1 tables) is the production default and serves the live demo
  from each tenant DB's `master` env. v2 (rep2 collections) runs
  against a separate `v2` env per tenant, loaded by `./do
  load-data-v2`. `AitoClient` normalises the handful of shapes that
  differ so the service modules speak one dialect — v2's — and the v1
  branches are deletable in one pass when v1 goes away. Every view
  passes on both (`./do v2-check`). The full break list, the
  behavioural deltas, and what's still open live in
  `docs/v2-migration.md`. Read that before touching a query shape.

### Data flow

```
Browser → Next.js page → fetch("/api/...") → FastAPI → AitoClient → Aito REST API
                                                 ↕
                                              cache (memory + Aito table)
```

---

## The `./do` script

```bash
./do dev              # Start both: Next.js on :8400, FastAPI on :8401
./do backend-dev      # Just FastAPI on :8401
./do frontend-dev     # Just Next.js on :8400 (proxy to :8401)
./do frontend-build   # Build static export
./do load-data        # Upload fixtures to Aito
./do reset-data       # Drop and reload all Aito tables
./do clear-cache      # Clear prediction cache
./do test             # Run pytest
./do setup            # Sync Python + npm dependencies
./do check            # Pre-merge gate (test + fmt)

./do env-init-v2      # Branch a `v2` env from master on each tenant DB
./do load-data-v2     # Load fixtures into the v2 envs as collections
./do v2-check         # Run every view's query shape against v2
./do dev-v2           # Run the demo against /api/v2
```

---

## The 16 views

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
    (`_predict success=true` over `projects`, no `team_members` in the
    where clause) plus a broad **Success factors** panel discovered by
    `_relate`: people from `assignments.person` (String — one row per
    assignment, no Text tokenisation) and project-level categoricals
    (`manager`, `project_type`, `priority`) from `projects`. Backed by
    two tables: `projects` (one row per project; `team_members` is a
    display-only String) and `assignments` (canonical project_id ×
    person × role, with `project_type` and `project_success`
    denormalised for direct `_predict` / `_relate` filters).
13. **Utilization & Capacity** — per-person current load + at-risk
    allocation + historical norm; "what if" forecast uses
    `_predict assignments.role|allocation_pct` filtered by the
    denormalised `project_type` column. Studio-only.
14. **Engagement Planner** — a proposal (customer, scope, quote,
    duration, team size, site) in; a staffed team, a price check,
    delivery risk and a predicted customer objection out. Roles from
    `_predict assignments.role` — the role vocabulary is DISCIPLINES
    (`frontend`, `ux design`, `site manager`), not seniority bands.
    People from `_predict person` per role; `assignments.person` links
    to `people`, so one call returns the ranking **and** the matched
    person's title, skills, site and seniority, which is what the
    match chips show. Delivery from `_predict success | on_time`, and
    the sales read from `_predict quotes.won` + `loss_reason`. Team
    size is itself predicted (`_predict projects.team_size`). Each seat
    shows one assignee with a picker listing every candidate, score and
    reason. Metsä + Studio.

    **Delivery risk is Futurice's 3+3, not time-and-budget.** The core
    three — makes money, team stays happy, customer stays happy — are
    what decide whether an engagement was worth doing; the qualifying
    three are predictability, whether the thing worked, and whether it
    opened a door. Six `_predict` calls, six `$why` trees, because a
    schedule risk and a morale risk have different drivers. `success`
    is a composite of the core three, so "on time and on budget while
    burning the team and losing the account" scores as the failure it
    is. Fits a Nordic consultancy far better than a margin-and-schedule
    scorecard.

    **Role counts are capped by history.** `_predict role` returns a
    share, and scaling a share to a big team asks for two project
    managers on eight people. `_role_caps` reads the most of each role
    that ever appeared on ONE project, so a singleton stays a
    singleton — without anyone hard-coding which roles are management.

    **The candidate number is not a quality score.** It is
    `P(person | role, site, stack, sector)` — how often they are the
    one who does work like this. The column says "Usual pick" and the
    picker says so in words, because "Fit 43%" invited the reading
    that Aito rates how well someone does their job. It does not, and
    a demo that implies it would be selling something the database
    cannot do. A separate assignment-quality rating is a real
    follow-up; it is not this number.

    **Chips carry provenance.** Each reason next to a candidate is
    tagged `aito` (Aito's `$why` named that field as evidence — teal),
    `match` (coincides with the proposal, computed here — gold) or
    `fact` (context, argued nothing — grey). Painting all three alike
    implied the database had endorsed someone's certifications.

    **Two kinds of clause, and the difference is the lesson.**
    `project_type` / `role` / `site` describe the JOB and are
    *evidence* — they let Aito rank on how such work was staffed
    before. The `person.*` clauses are linked-field *filters* on the
    candidate: `person.site` (where someone is based, not where the job
    is), `person.seniority`, and `$match` over `person.skills`. Aito
    applies them in the query, so a filtered-out person never reaches
    the shortlist. Requirements are held PER ROLE — a proposal-wide
    "must have Next.js" staffed the QA and project-manager seats with
    frontend developers, because the filter is enforced while `role` is
    only weighed.

    **The role list is editable.** ± seats per role, `+ add role`, a
    per-seat requirement, and `reset to predicted mix`. The prediction
    is a starting point, not a verdict.

    **Availability is a window, not a number.** `assignments` carries
    the months each booking occupies, and `absences` carries planned
    leave; `availability_service` combines them into per-person load
    across the *project's own* months. Same proposal starting in
    September and in March staffs differently — the best frontend fit
    is on annual leave in December, so September's seat goes to someone
    else and March's goes to him. This is plain aggregation, not
    prediction: a calendar is a fact, and dressing arithmetic up as
    inference is the sort of thing this demo must not teach.

    **Two columns, two questions.** "Usual pick" is
    `P(person | role, site, stack, sector)` — who does this. "Did well"
    is `_recommend person goal={went_well: true}` — who did well when
    they did. They diverge, and the gap is the conversation: the second
    most usual project manager scores 16% usual and 28% did-well.
    `assignments.went_well` is deliberately not a restatement of
    `project_success`: a good person on a doomed project still did
    their bit.

    **Seats are phased.** A designer is wanted at the start and a QA
    engineer at the end, so each seat books only the months its role
    historically occupies and availability is asked about THOSE months.
    The phases are measured from `assignments` × `projects` rather than
    declared in the service — a constant copied across that boundary
    would drift, the way the booktest's roster did.

    **Bid / Delivery.** Two jobs on one screen were crowding each
    other; the objection ranking is a sales artefact and the capacity
    table is a delivery one.

    **Levers answer "so what".** Six probabilities describe a risk;
    none says what to do about it. `_levers` re-runs the same outcome
    `_predict` against a context that differs in one field — three
    weeks longer, one fewer person, one more — and reports the delta.
    "Three weeks buys 17 points of on-time and costs 26 of margin" is a
    decision; "on-time is 51%" is a fact. No new query shape, just the
    same question asked about a slightly different project.

    **Where Aito stops.** Aito ranks candidates per role; it does not
    allocate a team. "Who fits this role" is an inference; "who gets
    which seat given everyone else's" is an assignment problem, and
    pretending the second falls out of the first books one person into
    three roles. `_fill_seats` is a deliberate, documented greedy pass
    over Aito's ranking (no double-booking, skip the overloaded) and
    every seat stays overridable.
15. **Revenue Outlook** — the order book spread over the coming months
    by percentage-of-completion, then risk-adjusted by
    `_predict on_time` / `on_budget` per in-flight project. Answers
    "when does sold work turn into cash, and how much of that date do
    we believe". Metsä + Studio (Aurora hides it with `/projects`).

### Overview
16. **Automation Overview** — coverage stats + learning curve

---

## Aito query patterns

| Service | Endpoint | Purpose |
|---------|----------|---------|
| po_service | `_predict` | Account code, cost center, approver |
| smartentry_service | `_predict` (multi) | 5 fields in one session |
| approval_service | `_predict` | Approval level |
| anomaly_service | `_predict` (inverse) + `_search` | Categorical anomalies via `1 − p(actual)`; amount/vendor anomalies via search |
| supplier_service | `_relate` | Late delivery predictors |
| rulemining_service | `_relate` | High-confidence patterns |
| catalog_service | `_predict` (multi) | Missing product attributes |
| pricing_service | search + stats | Price range from history |
| demand_service | `_predict` + search | Units forecast |
| inventory_service | demand + stock | Days of supply + reorder |
| project_service | `_predict` + `_relate` | Project success forecast + broad success factors (people from `assignments`, categoricals from `projects`) |
| forecast_service | `_predict` ×2 | `on_time` / `on_budget` per in-flight project → risk-adjusted revenue by month |
| planner_service | `_predict` ×N + `_search` | Role mix + people per role; delivery risk; `quotes.won` / `loss_reason` for the predicted objection |

---

### The outcome drivers, and why there are five of them

From a real software-project post-mortem, and the reason they earn
their place is that their effects **diverge** across the 3+3. A single
success score averages exactly that away.

| driver | what it does |
|---|---|
| `contract_type` × `scope_clarity` | fixed price on an unclear scope: money 33% vs 71% on a clear one |
| `novelty` | a new stack: money **38%**, team **90%** — the clearest case for scoring more than one thing |
| `team_seniority` | the one factor that moves all six the same way (71/89/73 vs 44/63/52) |
| `customer_size` | small clients: customer-happy 48% vs 59%, doors opened 11% vs 26% |

`team_seniority` is derived from who is actually on the crew rather
than drawn separately, so "senior team → everything goes better" is a
relationship between two columns and not two independent dice.

These are also what make the levers worth having: on a fixed-price,
unclear-scope, new-stack, small-client proposal the planner reports
money at 16% and team happiness at 76%, and says nailing the scope
buys +29 points of on-time while three more weeks buys nothing —
because the problem was never duration.

### Why `proposals` is its own table

Booked work is not the whole claim on a person's time. Two or three
open bids have the same architect pencilled in, and the first delivery
lead to press go wins — which is why a plan reads as feasible right up
until it isn't. `proposals` holds provisional teams for bids that have
not closed.

Counted **separately**, never folded into booked load: treating a
40%-likely bid as booked time makes everyone look busy and the planner
useless, while ignoring it lets three leads each plan the same person.
It surfaces as "2 bids want them" and breaks ties in seat-filling —
a warning, not a subtraction.

### Role mixes are per project type, and that is the point

`assignments.role` used to be drawn uniformly across every discipline,
which staffed a **design** project with backend developers and QA, and
made `_predict role` return the same near-flat mix for every service
line — because that is genuinely what the data said. Each project type
now declares the disciplines it uses (`project_types[t]["roles"]`), so
strategy is architect-led, retainers carry devops, and design is
designers. If the planner ever proposes an incoherent team again, this
is the first place to look: the prediction is only as good as the
correlation in the fixture.

Note the residual: asking for eight seats where comparable work used
three spreads the long tail of the mix onto the team. The mix is right,
the size is not, and the form says so in red rather than silently
producing a strange team.

### Why `absences` is its own table

Booked work says where someone's hours went. It cannot say they are on
parental leave from November — an empty calendar and parental leave
look identical from `assignments`, and only one of them means the
person is available. That fact lives in an HR calendar, is derivable
from nothing else here, and is what invalidates a staffing plan two
weeks after it is made.

### Why `people` is its own table

`assignments` records who worked on what. It cannot say *why* they were
the right choice — that is their discipline, title, skills and site,
which in a real company lives in an HR system the scheduler never
queries. `people` holds it and `assignments.person` links to it, so a
`_predict person` returns the ranking and the profile together and a
staffing suggestion can be argued with in the terms a delivery lead
uses ("React, based in Tampere") rather than a bare score.

Note the projection gotcha: with **no** `select`, Aito returns the
whole linked row by default. The moment you name a `select` — which
this client must, for `$why` — that default is replaced, so linked
columns have to be named explicitly. That is what
`AitoClient.predict(select_extra=…)` is for.

### Why there is a `quotes` table

`projects` records work that was **won**. Nothing else in the schema
can answer "will this proposal land, and if not what will they say",
because every row in every other table is a survivor. `quotes` carries
the losses and a nullable `loss_reason`, and it is what the Engagement
Planner's sales read is built on. `price_band` is bucketed on purpose:
Aito reads "we quoted well over" far more reliably than it reads a raw
Decimal it has never seen, and the bucket is what a salesperson argues
about anyway.

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

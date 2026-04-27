# Data model

Six tables drive the demo. Five are universal (every persona has them);
one (`assignments`) is paired with `projects` and matters for the
Operations views. The shape is the same across all three tenant DBs —
the *content* is what differs (Wärtsilä for Metsä; Valio for Aurora;
Adobe for Studio).

```
purchases ──┐
            ├── (PO-coding, Approval, Anomalies, Supplier Intel,
            │   Rule Mining, Automation Overview)
            │
products ───┐
            ├── orders (linked: orders.product_id → products.sku)
            └── price_history (linked: price_history.product_id → products.sku)

projects ───┐
            └── assignments (linked: assignments.project_id → projects.project_id)
```

The two link types Aito uses live in
[`src/data_loader.py`](../src/data_loader.py) under each schema's
`columns` dict.

---

## `purchases` — the universal AP / PO history

The biggest table in every persona. Drives the seven universal-traffic
views (PO Queue, Smart Entry, Approval, Anomalies, Supplier Intel,
Rule Mining, Automation Overview) and feeds the Aito panel's example
queries on those pages.

| Column | Type | Notes |
|---|---|---|
| `purchase_id` | String (PK) | `PO-7841` |
| `supplier` | String | Persona-specific roster (Metsä: Wärtsilä, ABB, …; Aurora: Valio, Marimekko, …; Studio: Adobe, AWS, …) |
| `description` | Text | Tokenised — drives the Smart Entry & PO Queue text-similarity signal |
| `category` | String | `production`, `groceries`, `software`, etc. |
| `amount_eur` | Decimal | Range varies wildly by persona (€50 office to €280K construction) |
| `cost_center` | String | What `_predict` learns to assign |
| `account_code` | String | What `_predict` learns to assign |
| `approver` | String | What `_predict` learns to assign |
| `approval_level` | String | `manager` / `cfo` / `board` |
| `delivery_late` | Boolean | What `_relate` keys off for Supplier Intel |
| `order_month` | String | `2025-09` — drives the Automation Overview learning curve |
| `project` | String | GL project code |
| `routed_by` | String | `rule` / `aito_high` / `aito_reviewed` / `manual` — drives the Overview KPIs |

Volume: **3.2k rows (Metsä) · 5.3k (Aurora) · 3.2k (Studio)** across
46 months of history.

---

## `products` — the SKU catalogue

Universal but heavily Aurora-flavoured: that persona's 3.2k retail SKUs
(groceries, fashion, beauty, electronics) drive Catalog Intelligence,
Price Intelligence, Demand Forecast, Inventory Intelligence, and
Recommendations. Metsä gets a 320-SKU spare-parts subset; Studio gets
a 240-SKU software-licences-and-office-stock subset.

| Column | Type | Notes |
|---|---|---|
| `sku` | String (PK) | `SKU-4421` |
| `name` | String | Drives `_match` similarity in Recommendations |
| `supplier` | String? | Nullable to drive Catalog Intelligence's "missing fields" workflow |
| `category` | String? | Same |
| `unit_price` | Decimal? | |
| `hs_code` | String? | |
| `unit_of_measure` | String? | `ea`, `set`, `kg`, `seat`, `hr`, … |
| `weight_kg` | Decimal? | |
| `account_code` | String? | |
| `tax_class` | String? | |

Roughly 5% of rows have 2-4 fields nulled to populate the Catalog
Intelligence demo flow.

---

## `orders` — historical consumption

Drives Demand Forecast (per-SKU seasonality) and Recommendations
(month-level co-occurrence approximating basket co-purchase).

| Column | Type | Notes |
|---|---|---|
| `order_id` | String (PK) | `ORD-00123` |
| `product_id` | String → `products.sku` | Aito link |
| `month` | String | `2025-09` |
| `units_sold` | Int | |

Volume: 1.4k (Metsä) · 18k (Aurora) · 900 (Studio).

Production data with a `basket_id` column would make the
"frequently bought together" cross-sell collapse to a single
`_recommend` query — see
[Recommendations use case](use-cases/14-recommendations.md).

---

## `price_history` — supplier × volume × time prices

Drives Price Intelligence's fair-price band, quote scoring, and PPV.

| Column | Type | Notes |
|---|---|---|
| `price_id` | String (PK) | |
| `product_id` | String → `products.sku` | Aito link |
| `supplier` | String | |
| `unit_price` | Decimal | |
| `volume` | Int | |
| `order_date` | String | `2025-08-15` |

Volume: 900 (Metsä) · 6.5k (Aurora) · 700 (Studio).

---

## `projects` — work-in-progress portfolio

Drives Project Portfolio (Metsä, Studio) and feeds Utilization (Studio
only) via the join from `assignments`.

| Column | Type | Notes |
|---|---|---|
| `project_id` | String (PK) | `PRJ-1042` |
| `name` | String | |
| `project_type` | String | Persona-specific: `maintenance`/`construction`/`rollout`/`audit`/`rd` (Metsä), `store-fitout`/`ecom-launch`/`marketing-camp`/`audit` (Aurora), `design`/`implementation`/`strategy`/`discovery`/`retainer` (Studio) |
| `customer` | String | |
| `manager` | String | What the success forecast keys off (manager × type fit) |
| `team_lead` | String | |
| `team_size` | Int | |
| `team_members` | **Text** | Space-separated names — Aito tokenises, which is what makes "presence of person X predicts success" learnable as a single field |
| `budget_eur` | Decimal | Budget × duration drives the at-risk signal |
| `duration_days` | Int | |
| `priority` | String | `low` / `medium` / `high` |
| `status` | String | `active` / `at_risk` / `delayed` / `complete` |
| `start_month` | String | |
| `on_time` | Boolean? | Null until `status = complete` |
| `on_budget` | Boolean? | |
| `success` | Boolean? | **The prediction target** |

Volume: 285 (Metsä) · 92 (Aurora) · 435 (Studio).

The `team_members` Text field is the trick. Storing assignees as
space-separated names lets Aito learn per-person effects (`A.
Lindgren` boosts; `V. Jokinen` drags) from a flat field, without
needing array semantics. The booktest validates that this signal
survives across persona boundaries.

---

## `assignments` — canonical project × person × role

The relational record that mirrors `projects.team_members`. Used by
Utilization (sum allocation per person), the Project Portfolio's
staffing-factors `_relate`, and the per-person "what if" forecast.

| Column | Type | Notes |
|---|---|---|
| `assignment_id` | String (PK) | |
| `project_id` | String → `projects.project_id` | Aito link |
| `person` | String | |
| `role` | String | `lead` / `senior` / `engineer` |
| `allocation_pct` | Int | 0-100 |
| `project_type` | String | Denormalised mirror of `projects.project_type` (set at load time) |
| `project_success` | Boolean? | Denormalised mirror of `projects.success`; null on active projects |

Volume: 1.6k (Metsä) · 543 (Aurora) · 2.1k (Studio).

The two denormalised columns let `_predict` and `_relate` on the
assignments table filter by `project_type` / `project_success` as
ordinary fields — no cross-table join needed. Production ERPs do the
same on timesheet / assignment tables for query performance. See the
[Project Portfolio use case](use-cases/12-project-portfolio.md)
and [Utilization use case](use-cases/13-utilization.md).

---

## What each operator does on this model

| Operator | Tables | What it answers |
|---|---|---|
| `_predict` | `purchases` | "What account/cost-centre/approver?" |
| `_predict` | `projects` | "Will this project succeed?" |
| `_predict` | `assignments` (filtered by denormalised `project_type`) | "What role / allocation does this person take?" |
| `_relate` | `purchases` | "What predicts late delivery?" / "What's a candidate rule?" |
| `_relate` | `projects` over `team_members` (Text, tokenised) | "Whose presence on a team correlates with success?" |
| `_search` | any | Aggregations (PPV, learning curve, recommendations co-occurrence) |
| `_match` | `products` | Similar items for Recommendations |
| `_evaluate` | `purchases` (Project Portfolio booktest) | LOO cross-validated accuracy |

---

## Multi-tenant: same schema, different DBs

Each persona's Aito DB has the same six tables with the same column
types. The fixture *content* differs — different supplier rosters,
different category mixes, different scales. The
[Multi-tenant section in the README](../README.md#multi-tenant-one-demo-three-audiences)
covers the env-var routing; the per-persona generators live in
[`data/generate_personas.py`](../data/generate_personas.py).

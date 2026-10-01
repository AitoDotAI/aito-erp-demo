# Pre-registration: dragon hunt on the ERP demo's own query path

**Registered:** 2026-10-01 08:30 Helsinki, before the first run, together
with `scripts/dragon_hunt_demo_path.py`. Read-only on shared (the three
tenant DBs, engine 2.11.0 at registration), never 08:00–10:00. Same method
as the accounting demo's hunt (`aito-accounting-demo`, branch
`dragon/demo-path`, 107/109).

**A dragon** is a plausible wrong answer: a result that runs and looks
fine but is wrong. Crashes are not the target. A dragon in the DEMO's code
counts as much as one in the engine — what matters is the wrong number on
screen — but each finding says which it is, and an engine ticket is filed
only after the demo's code and data are ruled out.

## Oracle

The local fixtures `data/<tenant>/<table>.json` are what the tenant DBs
hold. Checked by the script before anything else (C1): `_search` `total`
for every table used below equals the fixture row count. A table whose
count does not match is reported, and every exact-count property on it is
**not scored** for that tenant — a mismatch is a data finding, not an
engine one.

## Cells

Every body is the demo's own, produced by calling the same client method
with the same arguments as the service (cited per cell). `query_log`
records the body actually sent, and it is saved next to each answer.

Inputs are fixed by rule, not picked by looking at answers:

- **PO rows:** each tenant's `purchases` sorted by `purchase_id`; rows at
  index 0 and `len // 2`.
- **Rule suppliers:** each tenant's two suppliers with the most purchases.
- **Basket anchors (aurora):** the three SKUs in the most baskets.
- **Matching lines (aurora):** `invoice_lines_holdout` sorted by
  `line_id`; indices 0, 500, 1000. The vendor row comes from `vendors`.
- **Planner (metsa, studio):** the most common (`project_type`, `role`) pair
  in `assignments`. One cell with `person.seniority: "senior"`, one with
  `person.site` = the most common `site` in `people`.
- **Demand (metsa, aurora):** `monthly_demand_holdout` sorted by
  `demand_id`; rows 0 and `len // 2`, with `FEATURES` as the where.

| id | cell (service) | property | pass rule |
|---|---|---|---|
| C1 | every table used | `_search` total equals the fixture count | exact |
| P1 | all `_predict` | every `$p` in [0, 1]; hits sorted by `$p` descending | always |
| P2 | PO fields, approval level (`po_service`, `approval_service`) | the sum of `$p` at `limit: 50`, scored only where the tenant has ≤ 50 distinct values of the field | \|sum − 1\| ≤ 0.01 |
| P3 | all `_predict`, all `_relate` | the top 3 at `limit: 3` equal the first 3 at the larger limit | values equal; `$p` / lift within 1e-9 |
| P4 | all | the same body twice gives the same answer | identical |
| P5 | PO fields, approval, demand | reversed `where` key order gives the same answer | identical |
| P6 | PO fields, approval | the top value occurs in that tenant's fixture column | always |
| P7 | PO fields `$why` | the factor chain multiplies back to `$p` | abs(log10(product / `$p`)) < 0.1 |
| P8 | PO fields `$why` | the `baseP` of the top value equals its share in the tenant's purchases | within 0.001 |
| R1 | supplier risk `_relate` (`supplier_service`: where `delivery_late: true`, relate `supplier`) | `fs.n`, `fs.fCondition`, `fs.f`, `fs.fOnCondition` equal the fixture counts | exact |
| R2 | rule mining `_relate` (`rulemining_service`: where `supplier`, relate `account_code`) | as R1 | exact |
| R3 | cross-sell `_relate` (`recommendation_service`: `baskets`, where `products $has`, limit 60) | as R1, with set membership | exact |
| M0 | matching through `rank_line` itself | the demo's own path returns candidates for a line the fixtures can answer | non-empty |
| M1 | matching `_predict sku` (`matching_service.rank_line`'s body) | every hit's linked catalogue columns equal that SKU's `products` row | exact |
| M2 | matching | every hit's `sku` exists in `products` | always |
| L1 | planner `_predict person` (`planner_service`'s where, limit 6, `PERSON_FIELDS`) | every candidate satisfies the `person.*` filter according to `people` | always |
| L2 | planner | every candidate's returned profile columns equal their `people` row | exact |
| E1 | demand `_estimate` (`demand_service`) | the estimate lies within [min, max] of `units_sold` in `monthly_demand` | always |
| E2 | demand `_estimate` `why` | the weighted mean of the `why` components equals the estimate | relative error ≤ 1e-6 |

**Recorded, not scored.**

- **Relate ordering and lift.** The order of `_relate` hits is reported
  but not scored: the default order is not documented, and the demo
  orders explicitly where it relies on one. Each reported lift goes next
  to the exact empirical lift; Aito's lift is smoothed toward 1 by
  design, so a gap is not a dragon by itself.
- **Known P7 history.** Factor chains have a known history of being
  incomplete (td-20260909133103405502). A P7 failure is reported with
  that reference; a new failure pattern is a dragon.
- **E2 field names.** The names of the `why` component fields (weight
  and value) are confirmed on the first response, before any E2 is
  scored. If they are not what the script reads, that is recorded as an
  amendment here, not fitted to the data afterwards.

## Demo-code findings made while registering

Recorded before the run, because they are the same kind of dragon and they
shaped the cells:

1. **Truncated whole-table reads.** These read a fixed page as if it were
   the whole table:
   - Supplier spend and both Overview aggregates read 5000 of Aurora's
     5259 purchases.
   - Rule Mining read 2000 purchases on every tenant.
   - Catalog read 2000 of 3200 products.

   All are fixed in #58, with a guard test.
2. **Matching swallows errors.** `matching_service.rank_line` catches
   `AitoError` and returns an empty shortlist, so an engine failure
   renders as "no candidates". This is the same pattern the planner was
   fixed for. It is not fixed yet; it is reported with the results.
3. **Matching drops hits silently.** `rank_line` also drops any hit
   whose `$value` is `None`, without a word. M2 and M1 read the raw hits,
   so a dropped hit is still seen.

## Runs

- **Baseline:** after 10:00 on 2026-10-01, on shared 2.11.0. Every
  answer and every body sent is saved as JSON next to the pass or fail of
  every property.
- **After shared moves to ≥ 2.11.3:** the same script, unchanged, with
  `--compare`. Any property that passed and now fails is a dragon
  candidate. Any changed answer (a top-1 value, or `$p` differing by more
  than 1e-6) is reported with its explanation, or as a dragon if there
  is none.

## Amendment 1 (2026-10-01 10:05, the first baseline attempts)

1. **The 10:05 scheduled run did not run.** The working tree was on
   another branch at the time, so no query was sent.

2. **The second attempt was not read-only.** It built its clients by
   importing `src.app`, and that import runs the cache warm-up at module
   level (`src/app.py`, `_warm_cache()`). So it computed views for metsa
   and aurora and wrote their results to each tenant's
   `prediction_cache` table. No demo data table was touched; these are
   the same writes a local backend makes on startup. The script now
   builds its clients from config directly.
   - The import side effect is itself a demo-code finding. Every CLI
     script that imports `src.app` does the same, including
     `crosssell_eval` and `match_eval`.

3. **E2 field names.** The attempt crashed at E2: a `why` component's
   `value` is an object, `{type: "neighborContext", value: n, ...}`, not
   a number. Confirmed on one metsa estimate, MD holdout row 0.
   - E2 now reads `value.value`. The pass rule is unchanged.
   - That probe already showed a mismatch: the estimate is 55.41, while
     the `why`'s own top-level `weightedAverage` value is 57.57. This is
     recorded here because it was seen before the scored run. The rule
     was not changed after seeing it.

## Baseline results (2026-10-01 10:07, shared 2.11.2, rev 59fc6420)

Shared moved from 2.11.0 to 2.11.2 between registration and the run;
the run is the 2.11.2 baseline. Every answer and every body sent is in
`docs/notes/dragon-hunt/baseline-2.11.2.json`.

**509/519 checks pass.** By property:

| property | pass |
|---|---|
| C1 oracle counts | 13/13 |
| P1 bounds and order | 31/31 |
| P2 sum of `$p` | 24/24 |
| P3 limit independence | 36/36 |
| P4 determinism | 38/38 |
| P5 key order | 22/28 |
| P6 / P7 / P8 | 24/24, 18/18, 18/18 |
| R1 / R2 / R3 exact `fs` counts | 30/30, 54/54, 180/180 |
| M0 / M1 / M2 matching | 3/3, 3/3, 3/3 |
| L1 / L2 planner | 4/4, 4/4 |
| E1 / E2 demand estimate | 4/4, 0/4 |

### Engine dragon: `_estimate` (aito-core#1558)

- **P5, demand:** 4 of 4 cells fail. The estimate depends on the
  `where` key order: 55.41 vs 57.60 on metsa, and 12.52 vs 13.28 on
  aurora, for otherwise identical bodies.
- **E2:** 0 of 4 cells pass. In every response, `why.value` is exactly
  the mean of its components, but it is not the `estimate` the same
  response returns: 57.57 vs 55.41, and 8.57 vs 12.52.
- **What this means for the demo:**
  - The Demand and Inventory views show neighbours that explain a number
    different from the one on screen.
  - The forecast depends on the order of `FEATURES`.
  - Filed with exact repro bodies, after ruling out the demo's code and
    data (C1 13/13; the bodies were recorded at the send).

### Fails by rule, not a dragon

- **P5, approver:** 2 cells fail (metsa and aurora, `PO-1001`). They
  have the same values in the same order; one `$p` differs by 1.4e-17,
  which is float rounding.
- The rule said "identical", and the failure is reported as registered.
  The rule is not loosened after seeing the data.

### Recorded, not scored: relate lifts

- The reported lifts are pulled toward 1 against the exact empirical
  lift. For example, NCC Suomi late deliveries: lift 1.52 vs exact
  2.07; Siemens Finland: 0.63 vs 0.26.
- This smoothing is by design. Supplier Intel reports the smoothed
  figure as the supplier's risk; that is worth saying on screen, but it
  is not a wrong answer.
- All 264 relate counts behind those lifts are exact.

### Demo-code dragons (found while registering and running)

1. Five truncated whole-table reads. Fixed in #58.
2. & 3. Matching swallowed `AitoError` into an empty shortlist and
   silently dropped hits with no `$value`. Fixed on
   `fix/matching-errors-visible`, awaiting review.
4. **New:** importing `src.app` runs the cache warm-up for every tenant
   and writes to `prediction_cache` (amendment 1). Every CLI script that
   imports it pays a full warm-up and writes to shared Aito. Not fixed
   yet.

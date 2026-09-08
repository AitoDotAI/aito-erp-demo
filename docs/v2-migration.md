# Migrating the demo to Aito API v2

Status: **the demo runs on v2**, on a separate environment, with the v1
production demo untouched. This document is what was done, how to run
it, and — the part that matters upstream — every place where v2 behaves
differently from v1.

Reference: <https://aito.ai/docs/v2/>

**Most of what follows was already known.** The agent demo migrated first
and filed aito-core #1061–#1068; this demo hit the same contract-level
issues independently. Where a finding below has an issue, it is named.

**Verified against core `38a234a6` (built 2026-08-31T08:17).** Two
earlier passes measured `7d5c48a9` (08-15) and `3de8f4f7` (08-27); the
deployment moved under both, so everything below has been re-run three
times. The current build closes four of the nine findings — see the
table — and the accuracy delta that was this migration's one open
question **no longer reproduces**.

### Which of these were bugs, and which were the contract

A break is not a defect. Sorting them this way is the useful cut,
because only the first column is ever coming back:

| # | Finding | Verdict on `38a234a6` |
|---|---|---|
| 1 | `select: ["feature"]` rejected | **fixed** — accepted again on `_predict`, alongside `$value` |
| 2 | `relate` needs a field list | **by design**; error message now names the fix |
| 3 | `_relate` drops `ps` | **fixed** — `ps` is back, as empirical ratios |
| 4 | `_evaluate`/`_estimate` envelope | **by design** — `core/docs/v2-response-format.md` §3 |
| 5 | `PUT /schema` doesn't replace | **by design** — schema change is `_plan`/`_apply` |
| 6 | Missing table is a typed 404 | **by design**, and now consistent across every v2 endpoint |
| 7 | `$why` emits `$group` | **by design on v2** — v1 emitting it was the bug (v2.3.0 fix) |
| 8 | No `x-aitoai-response-time` | **fixed** — v2 is wrapped by the same directive as v1 |
| 9 | Cold-start exceeds the timeout | did not reproduce |

The "by design" rows are all documented decisions in
`aito-core/core/docs/v2-response-format.md`, with the reasoning — bare
equality in relate hits because `{"plan":"Free"}` is what you paste back
into a `where`; `kind`/`data` because a scalar has no honest home in a
page-of-hits; `$`-prefixed keys because a customer collection may have a
column called `value`. Those are wire-contract freezes, not oversights,
and this client was wrong to treat them as gaps. What was genuinely
worth reporting was narrower than it looked: `ps` (silent zeros), the
missing latency header (a wrong number on screen), and the accuracy
delta. All three are now fixed upstream.

---

## The shape of the migration

v2 runs the **rep2** engine over `collection` tables. The live demo's
tables are rep1 `table`s, and a rep1 table reached through `/api/v2`
supports only basic filtering and predict — `$match` / `$search` are
rejected, by design, because v1 is being retired rather than bridged.
So this is not a "change the base URL" migration: v2 needs its own copy
of the data, shaped as collections.

Aito environments make that cheap. Each tenant database now has a `v2`
environment — a copy-on-write branch of `master` — holding the same
fixtures as collections:

```
shared.aito.ai/db/aito-erp-demo-2  ├── env.master   rep1 tables  ← the public demo, untouched
                                   ├── dev          rep1 tables  ← local iteration
                                   └── v2           collections  ← new
```

Same database, same API key (keys are database-level and read every
env), different `/env/` path segment. `master` never sees a write from
any of this.

## Running it

```bash
./do env-init-v2                  # branch `v2` from master on each tenant DB
./do load-data-v2 --tenant=all    # load the fixtures as collections
./do v2-check --tenant=all        # every view's query shape, against v2
./do dev-v2                       # run the demo against /api/v2
```

`AITO_API_VERSION=v2` is the underlying switch; `.env` carries both
credential sets side by side (`AITO_<TENANT>_API_*` for v1,
`AITO_<TENANT>_V2_API_*` for v2). Production sets neither and stays on
v1.

**One safety rule, enforced in code.** On v2 the unscoped URL resolves
to `master`, and one key writes every env — so a dropped `/env/v2/`
segment silently rewrites production and returns `200 OK`. The v2
loader drops and recreates every table, so it refuses to run against a
URL with no `/env/` segment (`data_loader._assert_env_scoped`).

## Current state — readiness review, 2026-09-08, core 2.8.0

`./do v2-check --tenant=all` → **49 ok · 0 partial · 0 empty · 0
broken**, and the v1 sweep is identical. All seventeen views work on
all three personas, using every query type the demo exercises.

**But the sweep only proves query SHAPE.** It reported green throughout
the week in which rep2 lost 10 points of matching accuracy and got it
back again, so it cannot answer "can we deploy". Three things were
measured that it does not cover.

**Answers agree.** `_evaluate` over 200 held-out rows per tenant, the
three fields the demo leads with:

| tenant | field | v1 | v2 | Δ |
|---|---|---|---|---|
| metsä | cost_center / approver / account_code | 93.5 / 91.5 / 92.0 | 93.5 / 91.5 / 91.0 | ≤1pt |
| aurora | cost_center / approver / account_code | 95.5 / 69.5 / 95.0 | 95.5 / 69.0 / 95.0 | ≤0.5pt |
| studio | cost_center | 96.0 | **91.0** | **−5.0** |
| studio | approver | 77.5 | **81.5** | **+4.0** |

Seven of nine within two points. Both studio deltas are ten rows at
n=200 on the smallest corpus in the demo (970 purchases), and they
point in opposite directions, so this reads as sample noise rather than
a regression — but it is the one thing to re-check before promoting,
because studio is the persona a consultancy prospect sees.

**Warm latency is a non-issue.** Every view, every tenant, both
engines: **v2 totals 0.87× of v1**, per-view median 0.95×. Two first-run
outliers (planner/studio 4.33×, approval/aurora 3.48×) disappear on a
warm repeat — 1.11× and 1.15×.

**Cold start is the real risk, and it is §9 again.** That planner/studio
first touch was **29.6 s** against 5.4 s warm. Non-master envs are
evictable, so a quiet demo on `/env/v2` pays that on the first click of
a session. This is the argument for not lingering between steps 1 and 2
below; it is not a v2 defect, it is where the data is parked.

**One new operational hazard: core #1303.** 2.8.0 could not read rep2
collections written by `38a234a6` — a plain `_search` answered 500 with
a garbage index, empty collections included, and the only fix was to
drop and reload. Every v2 env here has been rebuilt since, so the demo
is clean. The lesson to carry: **a core upgrade may orphan a deployed
v2 env with no warning**, and the recovery is a full reload. On
`master` that is not a thing you want to discover live.

**Where the two engines genuinely differ: Invoice Matching.** rep1 79.3%
top-1 overall against rep2's 69.8%, and 60.5% vs 40.5% cold — but rep2
wins the pure-history regime, 89.7% against rep1's 82.1% where no name
text survives at all. `MEASURED_BY_ENGINE` holds both sets and the view
labels which it is quoting, so this does not block a deploy; it just
means the screenshot changes.

### Verdict

Functionally ready. `AITO_API_VERSION=v2` against the existing `/env/v2`
URLs would work today on all three personas. Before promoting to
`master`: re-check the studio `cost_center` delta on a larger sample,
and be aware that #1303 makes a future core upgrade a reload event.

---

## Differences found, and what we did about them

These are the concrete v1→v2 breaks this migration hit, in the order it
hit them. The ones marked **absorbed** are handled in
`src/aito_client.py` so the eleven service modules see one shape; see
the verdict table above for which were defects and which were the
contract working as designed.

### 1. `select: "feature"` is rejected — the value key is `$value` — core #1063

*absorbed — and since FIXED upstream*

v1 returns a predicted value under `feature`; v2 under `$value`. On
`3de8f4f7` v2 rejected `feature` in `select` outright:

```
400 request.invalid: unsupported select expression: no such field 'feature'
```

Hard break, and the highest-volume one — the demo read `hit["feature"]`
in ~25 places. Resolved by canonicalising on the **v2** vocabulary:
services read `$value`, and `AitoClient` renames v1's `feature` on the
way out.

On `38a234a6` the alias is back — `select: ["$p","feature"]` returns a
hit carrying **both** `$value` and `feature`, the same value under two
keys. `_match` got these back-compat aliases first (#1063); they now
reach `_predict` too. The demo does **not** revert: `$value` is the
canonical spelling to write new clients against, `feature` is a
compatibility affordance for v1 clients being ported, and the whole
point of canonicalising here was that retiring v1 deletes code rather
than touching eleven services.

### 1b. v1 rejects `select: ["feature"]` for a LINK target

*found while building the planner; the shim is now gone entirely*

The mirror image of #1, and the reason that finding is now moot in
both directions. `feature` is v1's name for the predicted value, but
only when the target is a plain column. Predict a **link** column and
v1 fails the whole query:

```
400 field 'feature' not found
  {"from":"assignments", "predict":"person",
   "select":["$p","feature", …]}       ← person links to people.person
```

`$value` is accepted on v1 for String, Boolean **and** link targets —
verified on all three. So the client now selects `$value` on both API
versions and the v1 `feature` shim is deleted, which removes the
single largest piece of v1/v2 divergence in `aito_client.py`. The
canonicaliser survives only for v2's `_match`, which returns both keys
as aliases.

*Upstream note:* worth documenting that `feature` is not a general
alias for the predicted value. A client that only ever predicts plain
columns will use it happily for months and then break the first time
someone predicts across a link.

### 2. `relate` takes a field list, not a field name

*by design; the error message is fixed*

```
v1: { "relate": "supplier"   }
v2: { "relate": ["supplier"] }   // the string form is a 400
```

The old message named the accepted types and not the fix. It now says
what to do:

```
400 query.invalid: field 'relate' must be an array of field names
    (e.g. ["product.name", "product.category"]) or an object condition
    (e.g. {"product.name": "Pirkka banana"})
```

Which is the entire remedy this finding ever wanted.

### 3. `_relate` drops the `ps` block — core #1064, #1065; todo td-20260816050623202559

*absorbed — and since FIXED upstream. The one finding that was worth
filing, and the one that got fixed.*

**`38a234a6` returns `ps` on v2**, with `p`, `pOnCondition`,
`pOnNotCondition` **and** `pCondition`. The values are the plain
empirical ratios — bit-identical to what the client had been
recomputing (Lemminkäinen: `f 8 / fCondition 186` = `pOnCondition
0.043011`, exactly the derived number). The derivation stays as a
fallback guarded by `if "ps" in hit`, so older builds still can't render
silent zeros, and a regression test now pins that the server's own block
— including the `pCondition` the fallback never computed — survives
untouched.

The rest of this section is the original finding, kept because it is
what the shim exists for.

---

v1 returns smoothed probabilities next to the raw frequencies:

```json
"fs": {"f": 55.0, "fOnCondition": 8.0, "fCondition": 186.0, "n": 3252.0},
"ps": {"p": 0.0172, "pOnCondition": 0.0301, "pOnNotCondition": 0.0163, "pCondition": 0.0573},
"info": {"h": 0.125, "mi": 0.0058, "miTrue": 0.0242, "miFalse": -0.0184},
"relation": {"n": 3252.0, "varFs": [186, 55], "stateFs": [3019, 178, 47, 8], "mi": 3.68e-4}
```

v2 returns `fs`, `lift`, a scalar `info`, `n`, `condition` — no `ps`,
no `relation`, and `info` is a number rather than the four-part object.

This is the migration's one genuinely dangerous difference: Supplier
Intel and Rule Mining read `ps.pOnCondition` for the headline
percentage, and a missing key reads as `0.0` — a plausible-looking
number, silently wrong. The client now recomputes `p` and
`pOnCondition` from `fs` rather than defaulting, so the failure can't
be silent. The recomputed values are plain empirical ratios and differ
slightly from v1's smoothed ones (Lemminkäinen's late rate:
0.030 → 0.043).

*Upstream note:* this is the item most worth filing. Either return `ps`
on v2, or document its absence and the intended derivation — a client
that keeps reading `ps` gets zeros, not an error, which is exactly the
silent-degradation failure v2's "fail loud" principle is meant to
prevent.

*Related, and an improvement:* v1's `fs.f` comes back **fractional**
(`317.86763372620123` purchases from Caverion); v2 returns the true
integer count (`330.0`). The demo has been rendering v1's fractional
order counts as-is. v2's number is the correct one.

### 4. `_evaluate` and `_estimate` wrap their payload — todo td-20260829111229412011

*absorbed — and specified behaviour, not a gap*

`core/docs/v2-response-format.md` §3 is the decision: `rows` keeps the
Elastic-shaped `{offset, total, hits}` for v1 compatibility and carries
no `kind`; every non-rows result gets `{kind, data}`, where `data` is
the key the whole surface converges to in v3. A client discriminates
with `kind ?? "rows"`. The demo does exactly that, via the SDK.

```json
v1: {"accuracy": 0.94, "baseAccuracy": 0.21, "cases": [...]}
v2: {"kind": "evaluation", "data": {"accuracy": 0.94, ...}}
```

Unwrapped in the client, which asserts `kind` matches what was asked
for rather than unwrapping whatever came back. Per-case `top` /
`correct` carry `$value` (see #1).

### 5. `PUT /schema/{table}` creates but does not replace

*absorbed — by design; still reproduces, and should*

Both versions refuse, and they refuse differently — which is the part
this section originally got wrong. v1 replaces an *empty* table and
refuses one holding rows; v2 refuses on existence alone:

```
v1: 400 Cannot replace table `purchases` schema. The table contains
         data, please delete the data first.
v2: 400 schema.create_failed: Table 'purchases' already exists
```

So "v1's PUT replaces an existing table", as this document previously
claimed, is only true before the first load. Caught by running
`./do load-data` without `--reset` against a populated v1 tenant.

Since a `v2` env branched from master inherits rep1 tables that must
become collections, the v2 load path always deletes first. Reasonable
behaviour on v2's part — the accidental-replace it prevents is worse —
but it's a load-script break for anyone porting, and the v2 alternative
(`_plan` / `_apply`) isn't referenced from the error.

### 6. The missing-table error is differently typed — todo td-20260829111304061579

*absorbed*

```
v1: 400  failed to open 'ghost'
v2: 404  {"code": "not_found", "message": "ghost not found"}
```

The demo tolerates missing tables per tenant (a persona with no
`impressions` fixture should render an empty view, not a 500), so
`_is_missing_table_error` now matches both. v2's typed code is the
better contract.

The real gap behind that todo was *inconsistency*, not typing: `_query`
returned the `error` kind while the v2 schema and data endpoints still
answered in the flat v1 `{message, status}` — two halves of one API
disagreeing. On `38a234a6` both are typed (`GET /api/v2/schema/ghost`
→ `{"kind":"error","data":{"code":"not_found",…}}`). Fixed.

### 7. `$why` propositions use `$group`, which v1 never emitted

*absorbed — and correct behaviour on v2; the client owed the renderer*

The factor tree is otherwise identical, but v2 combines correlated
evidence into a `$group` — "these signals vote as one theme", not as
independent conjuncts:

```json
v1: {"$and":   [{"description": {"$has": "chemicals"}}, {"supplier": {"$has": "Berner Oy"}}]}
v2: {"$group": [{"description": "Cleaning"}, {"description": "chemicals"}, {"supplier": "Berner Oy"}]}
```

`why_processor` renders propositions for the WhyTooltip and knew
`$and` / `$or` / `$not`. An unknown operator fell through to
`str(prop)`, so the demo's explanation popover displayed a raw Python
dict — a working query producing broken-looking output, and the reason
this migration needed a UI-level check and not just a "did it 200?"
one. Now rendered with `+` rather than `AND`, since the two mean
different things and the panel is teaching the reader what Aito did.

Group formation is v2's default learner, so a `$group` factor is the
honest output there — and aito-core v2.3.0 confirms it from the other
side, fixing "an accidental group-formation leak into the **v1** API
(the v2-scoped default flip in v2.2 also hit v1), which put
un-renderable `$group` factors into the v1 `$why`". v1 emitting it was
the defect. v2 emitting it is the contract, and a client with a `$why`
renderer owes it a case — which is what this demo now has.

Still worth a doc line: `$group` is documented as a `where` operator,
not as something a `$why` tree contains. Anyone porting a `$why`
renderer hits it, and an unknown operator that falls through to
`str(prop)` produces a working query with broken-looking output.

### 8. v2 omits `x-aitoai-response-time` — todo td-20260829121140677301

*FIXED upstream — this was the one that was visible on screen*

`AitoClient._request` prefers Aito's own server-side timing header over
the httpx wall-clock, precisely so the demo's latency pill shows what a
query *costs* rather than what the network added. `/api/v2` was not
wrapped by the `aroundRequest` directive that emits it, so every v2 pill
silently fell back to wall-clock and overstated Aito's latency — on the
page whose job is to make latency look good. (The accounting demo's
badge read 4695.6 ms for a query answered in a fraction of that.)

`38a234a6` wraps `/api/v2` with the same directive — which also brings
v2 traffic into request logging and the metrics reporters it was
likewise missing. Confirmed: a v2 `_predict` now answers with
`x-aitoai-response-time: 209.61` against v1's `183.58`. Guarded
upstream by `V2WireContractParityTest/responseTimeHeader`.

### 9. Cold-start exceeds the client timeout — and non-master envs are why

*mechanism identified; it decides the deployment plan*

The first sweep after the 08-27 redeploy had three views time out at
the client's 30 s limit; the same sweep run again was 14/14. On
`38a234a6` the first sweep after a redeploy was 42/42 cold. Treated as
"did not reproduce" — until the reason surfaced.

**`master` is memoized; every other env lives in an evictable cache.**
`Aito.envCache` carries `evictInactive(threshold)`,
`evictLRU(count, protectAccessedWithinMs)` and
`evictByMemory(target)`, and `LinkedEnv` refers throughout to the
"memoized master" as the source. So a branch env that has been idle is
dropped and the next query pays the full rebuild, while master is held.

That is very likely the whole of the accounting demo's
16 s–276 s cold views (todo td-20260829124802850866), and it is not a
bug — it is a cache doing its job on an env nobody was using.

**Consequence for the cutover.** Running production against
`/env/v2` works and is the safe way to go live, but it is a poor
steady state: a demo that is quiet between prospect visits is exactly
the access pattern that gets evicted, so the first click of every
session pays cold-start. The env indirection is a deployment
mechanism, not a place to live.

### 9b. `_estimate` cannot read a nullable numeric column

*found building the effort estimator; not v2-specific — v1 does it too*

`_estimate` on a nullable `Decimal` fails with an unhandled Option:

```
400  "error": "None (of class scala.None$)"
     {"from":"projects","where":{"project_type":"implementation"},
      "estimate":"actual_cost_eur"}        ← Decimal, nullable: true
```

Adding `status: "complete"` to the `where` so that **no null reaches
the candidate set** does not help; the identical query against the
non-nullable `budget_eur` on the same table answers normally. So it is
the column's declared nullability, not the data.

Two things make it worth filing. The message is a Scala type name
rather than anything a client can act on — `predict` and `relate` on
the same nullable columns work fine, so a caller has no reason to
suspect the column. And nullable numerics are the natural shape for
exactly this: an actual cost exists only once work is finished.

Worked around by moving actuals into a `deliveries` table whose columns
are all non-nullable — which is better modelling anyway (the costing
record is not the sales record), but the workaround should not be
necessary.

### 10. Things that did *not* break

Worth recording, because it's most of the surface:

- Column schema vocabulary is unchanged — same type names, `nullable`,
  `link`. Only the table `type` differs (`table` → `collection`).
- `where` accepts a bare string against a `Text` column, and
  bare-string, `$match` **and v1** now return the same distribution:
  `Production` 0.9825 / `Admin` 0.0029 / `Logistics` 0.0029, all three.
  Core #1062 reports bare and `$match` diverging silently on v2; that
  did not reproduce on `3de8f4f7` and does not on `38a234a6`, and the
  cross-engine agreement is new — worth saying so on #1062, and it
  points at todo td-20260816110336994753 (route `$match`/bare through
  the member-prior path) having landed.
- `$why` works, including the parameterised
  `{"$why": {"highlight": {"posPreTag": …}}}` form the frontend's
  sentinel-tag rendering depends on (ADR 0003).
- `_evaluate` accepts `testSource` + `$get` bindings unchanged.
- `_search` accepts the v1 `from`/`where`/`limit` body.
- `_recommend` with `goal` and linked-`select` is unchanged.
- Batch insert is the same endpoint and body.

---

## Behavioural deltas — the accuracy gap closed

Same fixtures, same queries. On Metsä, `_evaluate` over 200 held-out
purchases (the query the Automation Overview runs):

| Field | v1 | v2 on `3de8f4f7` | v2 on `38a234a6` |
|---|---|---|---|
| cost_center accuracy | 0.935 | 0.880 | **0.935** |
| account_code accuracy | 0.920 | 0.910 | 0.910 |
| approver accuracy | 0.925 | 0.915 | 0.915 |
| cost_center cases below p<0.5 | 0 | 16 | **3** |

`cost_center` — the field that carried the whole delta — is now
identical to v1, and its "needs review" band is back down from 16 cases
to 3. What's left is ±0.01 on two fields, which at n=200 is two rows.
The open question this document carried into the merge is answered: the
demo's accuracy claim does not change on v2.

Per-PO, every value agreed on both engines before and still does;
confidence moves by a point or two in **both** directions:

| PO | field | v1 | v2 |
|---|---|---|---|
| PO-7842 | approver | 0.834 | 0.840 |
| PO-7842 | account_code | 0.984 | 0.953 |
| PO-7844 | cost_center | 0.627 | 0.678 |
| PO-7846 | cost_center | 0.982 | 0.951 |

Rule Mining surfaces the same rules with the same supports; confidence
and lift shift by ~1% and the ordering of near-ties changes
(Konecranes sorts above Schneider on v2).

### The gap is back on high-cardinality targets — core #1281

The closed gap above was measured on 5-to-14-value categoricals. It does
not hold once the target gets wide. The invoice-line matching case
predicts `invoice_lines.sku`, a **3200-value** link into `products`,
and on the same build the two engines come apart:

| 400 paired held-out lines | v1 | v2 |
|---|---|---|
| top-1 | 26.8% | **16.8%** |
| top-5 | 54.2% | **31.2%** |
| top-1 `$p`, median | 0.2612 | **0.0179** |
| the two engines pick the same top-1 | — | **27.8%** |

The disagreement scales with how many values the target has — same
table, same `where`, three targets:

| predict target | distinct values | engines agree |
|---|---|---|
| `unit_of_measure` | ~5 | 59/60 |
| `billing_supplier` | 14 | 41/60 |
| `sku` (link → `products`) | 3200 | **25/60** |

Which is why the section above reads clean: at five values there is
nowhere for a ranking to go, so a scoring difference does not become a
wrong answer. `$p` diverges at every cardinality — only 7-34 of 60 land
within 0.01 even where the answer agrees.

**Ruled out before filing**, because the interesting part of a report is
what it is not:

- Not #1062. Bare string and `$match` on the `Text` column are identical
  *within* each engine, to the digit. Spelling changes nothing.
- Not #1245. `optimize` was called by the loader; re-running it
  explicitly and re-measuring gives the same numbers. This build carries
  #1245 already.
- Not the corpus. Both envs hold 10000 lines and 3200 products with
  2094 distinct names, the same stored schema (`description` `Text` +
  `analyzer: standard`, `sku` → `products.sku`), and the client sends
  the same `where` / `predict` / `select` / `limit` on both branches.

**What this means for the demo.** Invoice Matching's published numbers
are the v1 ones, and they are the ones the view quotes. Run it on v2
today and it shows roughly half the accuracy with confidences that
never clear the pre-fill bar — 22% coverage on v1, **0.2%** on v2. The
view is not wrong on v2, it is just much worse, and silently: 200 OK,
five candidates, no signal that anything differs. That is the general
hazard for any rep2 caller predicting something wide from text, and the
only way to see it is to hold out a labelled split and score it, which
is what `./do match-eval` is for.

### `optimize` still moves the confidence band (fresh evidence)

R&D's note of 2026-08-31 (`rep2: optimize CHANGES predictions`) reports
that rep2 compaction alters answers for **plain-String** targets while
every link target stays bit-identical — a suspected sibling of the
#1245 segment-structure defect. `./do load-data-v2` calls `optimize` on
every collection, so the demo's v2 numbers are post-compaction, and all
three of its targets are plain Strings. So this demo is a clean A/B for
it: a third env (`v2raw`) holds the same 3,252 purchases with no
`optimize` call.

| Field | v1 | v2 optimized | v2 raw |
|---|---|---|---|
| cost_center | 0.935 / 0 under p<0.5 | 0.935 / **3** | 0.935 / **0** |
| account_code | 0.920 / 0 | 0.910 / **1** | 0.910 / **0** |
| approver | 0.925 / 4 | 0.915 / 0 | 0.915 / 0 |

Top-1 accuracy is invariant under optimize at this scale — the reported
defect does not reach the number the demo publishes. But the confidence
distribution is not invariant: compaction alone pushes 4 cases across
the `p < 0.5` boundary on the two String targets, and nothing else
differs between those two environments. That is the same shape R&D
describes, visible at 3.2k rows rather than 10M, and it corroborates
"an answer that moves under optimize is an answer that depends on
layout" without needing the big corpus.

Reproduce with `uv run python -m src.v2_optimize_ab --load`, which
creates the `v2raw` copy-on-write branch and loads it without calling
`optimize`. Master is never touched.

---

## Deploying it

Three worries, and only the third is real:

* *"Promote the env first and the running app breaks."* It doesn't
  arise — the app names the env in the URL
  (`AITO_<T>_V2_API_URL=…/env/v2`), so `AITO_API_VERSION=v2` reads the
  branch while `master` keeps serving v1. Nothing is swapped, so
  nothing has to be ordered.
* *"Deploy the app first and it fails until the DB is promoted."*
  Same answer: the app is already pointed at a live env.
* *"Promote without a backup and I cannot roll back."* True, and the
  fix is one call. `promoteEnv` is `setBranch(master ← name, force)`:
  the source env survives but **the previous master content does
  not**. Branch it first — copy-on-write, instant — and rollback is
  the same operation in reverse.

```bash
# 0. the v2 envs are only as current as the last load
./do load-data-v2 --tenant=all
./do v2-check --tenant=all            # must be all-ok before anything else

# 1. go live on the branch. master untouched, rollback is an env var
AITO_API_VERSION=v2   # in the deployed environment, then redeploy

# 2. once it has been watched: make it master, keeping a way back
POST /api/v2/_envs           {"name": "v1-backup", "basedOn": "master"}
POST /api/v2/_envs/v2/promote
#    then drop `/env/v2` from the URLs and redeploy

# rollback at any point
POST /api/v2/_envs/v1-backup/promote
```

Do not linger between (1) and (2). Non-master envs are evictable
(§9), so a quiet demo running on a branch pays cold-start on the first
click of every session — the one number this demo cannot afford to be
bad. Promotion is what buys the retention, not just a tidier URL.

`./do load-data-v2` drops and recreates every table, and
`data_loader._assert_env_scoped` refuses a URL with no `/env/`
segment: on v2 an unscoped URL resolves to `master` and returns
`200 OK`, so the guard is the only thing between a reload and
production.

## What's left

- ~~**Decide on the accuracy delta.**~~ Closed by core `38a234a6`:
  `cost_center` matches v1 exactly and the "needs review" band is back
  to 3 cases. Nothing left to decide — but re-measure after a deploy
  before the default flips, since this is the number the Overview page
  publishes.
- **Report the `optimize` A/B upstream.** The confidence band still
  moves under compaction on two plain-String targets (§ above). It
  corroborates an open R&D finding with a 3.2k-row repro, and
  `src/v2_optimize_ab.py` is the runner.
- **The Aito side panels still print v1 queries.** They're hardcoded
  strings, and on v2 at least `frontend/app/smart-entry/page.tsx`
  (`POST /api/v1/_predict` … `"feature"`) shows a query that v2 would
  reject. Panel copy is sales narrative, so it's left alone here
  rather than changed unilaterally — but it has to move with the
  default, and every panel wants an audit at that point, not just this
  one.
- **Promote v2 to the default** once that's settled: flip
  `AITO_API_VERSION`, then delete the `if self._api_version == "v1"`
  branches in `aito_client.py` and the v1 credential set.
- **Use what v2 adds.** Nothing here exploits multi-hop links,
  `$patterns` itemset mining, `Date` component predicates, or the
  `quantity` flag on numeric columns — all of which the demo's data
  model has obvious uses for. Porting was the goal; taking advantage
  is the follow-up.

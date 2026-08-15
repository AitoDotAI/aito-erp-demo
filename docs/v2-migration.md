# Migrating the demo to Aito API v2

Status: **the demo runs on v2**, on a separate environment, with the v1
production demo untouched. This document is what was done, how to run
it, and — the part that matters upstream — every place where v2 behaves
differently from v1.

Reference: <https://aito.ai/docs/v2/>

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

## Current state

`./do v2-check --tenant=all` → **42 ok · 0 empty · 0 broken**. All
fourteen views work on all three personas, using every query type the
demo exercises: `_predict`, `_evaluate`, `_relate`, `_search`,
`_recommend`, `_query`.

The v1 sweep (`./do v2-check --api-version=v1`) is green too, so the
shared service code runs on both surfaces.

---

## Differences found, and what we did about them

These are the concrete v1→v2 breaks this migration hit. Each is a
candidate to file upstream as a core gap; the ones marked **absorbed**
are handled in `src/aito_client.py` so the eleven service modules see
one shape.

### 1. `select: "feature"` is rejected — the value key is `$value`

*absorbed*

v1 returns a predicted value under `feature`; v2 under `$value`, and it
rejects `feature` in `select` outright:

```
400 request.invalid: unsupported select expression: no such field 'feature'
```

Hard break, and the highest-volume one — the demo read `hit["feature"]`
in ~25 places. Resolved by canonicalising on the **v2** vocabulary:
services read `$value`, and `AitoClient` renames v1's `feature` on the
way out. When v1 support is dropped, the shim goes with it and no
service changes.

*Upstream note:* worth documenting explicitly in the v1→v2 migration
notes. It's the single most likely first error for a porting client,
and the error message doesn't hint at the replacement.

### 2. `relate` takes a field list, not a field name

*absorbed*

```
v1: { "relate": "supplier"   }
v2: { "relate": ["supplier"] }   // the string form is a 400
```

```
400 query.invalid: field 'relate' must be of type 'Null|<object — see the field's documentation>'
```

*Upstream note:* the error names the accepted types but not the fix.
"expected an array of field names, got a string" would land it in one
read.

### 3. `_relate` drops the `ps` block

*absorbed, with a visible numeric difference*

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

### 4. `_evaluate` and `_estimate` wrap their payload

*absorbed*

```json
v1: {"accuracy": 0.94, "baseAccuracy": 0.21, "cases": [...]}
v2: {"kind": "evaluation", "data": {"accuracy": 0.94, ...}}
```

Unwrapped in the client, which asserts `kind` matches what was asked
for rather than unwrapping whatever came back. Per-case `top` /
`correct` carry `$value` (see #1).

### 5. `PUT /schema/{table}` creates but does not replace

*absorbed*

v1's PUT replaces an existing table. v2 rejects it:

```
400 schema.create_failed: Table 'purchases' already exists
```

Since a `v2` env branched from master inherits rep1 tables that must
become collections, the v2 load path always deletes first. Reasonable
behaviour on v2's part — the accidental-replace it prevents is worse —
but it's a load-script break for anyone porting, and the v2 alternative
(`_plan` / `_apply`) isn't referenced from the error.

### 6. The missing-table error is differently typed

*absorbed*

```
v1: 400  failed to open 'ghost'
v2: 404  {"code": "not_found", "message": "ghost not found"}
```

The demo tolerates missing tables per tenant (a persona with no
`impressions` fixture should render an empty view, not a 500), so
`_is_missing_table_error` now matches both. v2's typed code is the
better contract.

### 7. `$why` propositions use `$group`, which v1 never emitted

*absorbed*

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

*Upstream note:* `$group` is documented in the query reference as a
`where` operator, but not called out as something that appears in
`$why` output on v2 where v1 emitted `$and`. Anyone with a `$why`
renderer will hit this.

### 8. Things that did *not* break

Worth recording, because it's most of the surface:

- Column schema vocabulary is unchanged — same type names, `nullable`,
  `link`. Only the table `type` differs (`table` → `collection`).
- `where` accepts a bare string against a `Text` column; `$match` is
  not required (it produces a slightly different probability, being an
  explicit token match).
- `$why` works, including the parameterised
  `{"$why": {"highlight": {"posPreTag": …}}}` form the frontend's
  sentinel-tag rendering depends on (ADR 0003).
- `_evaluate` accepts `testSource` + `$get` bindings unchanged.
- `_search` accepts the v1 `from`/`where`/`limit` body.
- `_recommend` with `goal` and linked-`select` is unchanged.
- Batch insert is the same endpoint and body.

---

## Behavioural deltas (not bugs — but the demo shows numbers)

Same fixtures, same queries, different answers. On Metsä:

| Measure | v1 | v2 |
|---|---|---|
| PO-7842 confidence | 0.834 | 0.840 |
| PO-7844 confidence | 0.627 | 0.675 |
| Overview model accuracy | 0.927 | 0.902 |
| cost_center accuracy | 0.935 | 0.880 |
| account_code accuracy | 0.920 | 0.910 |
| approver accuracy | 0.925 | 0.915 |
| cost_center cases below p<0.5 | 0 | 16 |

Predictions agree — every PO gets the same cost centre, account and
approver on both engines — but v2 is less confident on a tail of rows.
The `_evaluate` sample is 200 cases, so a couple of points is noise;
`0 → 16` cases landing under `p < 0.5` is not, and that band is what
the Automation Overview renders as "needs review". Worth understanding
before v2 becomes the demo's default, since the overview page is where
the accuracy claim is made.

Rule Mining surfaces the same rules with the same supports; confidence
and lift shift by ~1% and the ordering of near-ties changes
(Konecranes sorts above Schneider on v2).

---

## What's left

- **Decide on the accuracy delta above.** It's the one thing that
  changes what the demo *claims*, so it wants a real answer, not a
  shrug.
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

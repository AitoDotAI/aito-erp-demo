# Data upload guide

How to take the demo from a fresh checkout to a fully populated
multi-tenant Aito deployment. Should take ~10 minutes including the
`./do load-data` runtime.

## Prerequisites

1. **Aito instance(s)** — at minimum one DB; ideally three (one per
   persona). Sign up at [aito.ai](https://aito.ai); each free DB is
   instant.
2. **Python via `uv`** + **Node via `npm`** — handled by `./do setup`.
3. **`.env` filled in** — see below.

## Modes

### Single-tenant (one DB shared across all personas)

```bash
# .env
AITO_API_URL=https://shared.aito.ai/db/your-db
AITO_API_KEY=your-api-key
```

All three personas in the TopBar resolve to the same DB. Only the
nav filtering, tenant-aware Aito panels, and the persona-specific
fixture data differ — but since the DB has only one fixture set
loaded, the differentiation is presentational. Use this for local
development; the persona switch still demonstrates the routing.

### Multi-tenant (one DB per persona — recommended for public demo)

```bash
# .env — three separate Aito DBs
AITO_METSA_API_URL=https://shared.aito.ai/db/predictive-erp-metsa
AITO_METSA_API_KEY=...
AITO_AURORA_API_URL=https://shared.aito.ai/db/predictive-erp-aurora
AITO_AURORA_API_KEY=...
AITO_STUDIO_API_URL=https://shared.aito.ai/db/predictive-erp-studio
AITO_STUDIO_API_KEY=...
```

Backend builds one `AitoClient` per persona; each request routes to
the right DB based on the `X-Tenant` header. `AITO_API_URL` /
`AITO_API_KEY` are no longer required when all three pairs are
populated — the loader uses the first per-tenant pair as the
implicit default.

### Partial (one or two per-tenant pairs)

A tenant whose pair isn't set falls through to `AITO_API_URL` (or to
the first available per-tenant pair if `AITO_API_URL` is also
unset). Lets you ramp up one persona at a time during setup.

---

## Generating fixtures

Two generators live in [`data/`](../data/):

```bash
# Per-tenant fixtures into data/<tenant>/
./do generate-personas
```

Produces, deterministic per persona (`random.seed(hash(tenant_id))`):

| File | Metsä | Aurora | Studio |
|---|---|---|---|
| `purchases.json`     | 3.2k | 5.3k | 3.2k |
| `products.json`      | 320  | 3.2k | 240  |
| `orders.json`        | 1.4k | 18k  | 900  |
| `price_history.json` | 900  | 6.5k | 700  |
| `projects.json`      | 285  | 92   | 435  |
| `assignments.json`   | 1.6k | 543  | 2.1k |

Output is industry-distinct: Metsä has Wärtsilä/ABB/Caverion suppliers
with maintenance/construction projects; Aurora has Valio/Marimekko/L'Oréal
with retail SKUs and orders; Studio has Adobe/AWS/Figma with client
engagements.

A flat fallback also exists at `data/*.json` (the original
single-tenant generator at `data/generate_fixtures.py`). The data
loader prefers per-tenant directories when present, falls back to
flat — partially-migrated setups work.

---

## Uploading

```bash
# Default (single tenant)
./do load-data

# One persona only
./do load-data --tenant=metsa

# All three personas at once (multi-tenant)
./do load-data --tenant=all
```

What it does, per tenant:

1. Connect to the tenant's Aito DB (via `creds_for(tenant)`).
2. Optionally drop the existing tables (`--reset`).
3. Create the six table schemas
   ([`src/data_loader.py`](../src/data_loader.py), `SCHEMAS`).
4. Batch-upload the fixture data (100 records per `POST /data/<table>/batch`).

Idempotent — safe to run again. If you want a clean slate:

```bash
./do reset-data --tenant=all      # drop + reload all three DBs
```

When two tenants resolve to the same DB (single-tenant fallback
mode), the loader detects this and skips re-uploading the same data
under multiple tenant names — first writer wins.

---

## Volume reference

| Persona | Records | Span | Density |
|---|---|---|---|
| Metsä   | ~7.7k  | 46 months | maintenance + construction project history |
| Aurora  | ~33.6k | 46 months | retail catalog + order seasonality |
| Studio  | ~7.6k  | 46 months | client engagements + utilization history |
| **All three** | **~48k** | | |

Aurora is the heaviest because retail naturally has the largest
catalog × order matrix. Metsä and Studio are similar at ~7.7k each;
their density is in different tables (Metsä's purchases + projects;
Studio's projects + assignments).

---

## Verification

After upload, sanity-check the tenant routing:

```bash
# Three different DBs → multi-tenant mode is on
curl http://localhost:8401/api/tenants | jq

# Each tenant routes to its own URL
curl -H "X-Tenant: metsa"  http://localhost:8401/api/health | jq .aito_url
curl -H "X-Tenant: aurora" http://localhost:8401/api/health | jq .aito_url
curl -H "X-Tenant: studio" http://localhost:8401/api/health | jq .aito_url
```

Run the booktest suite — once data is loaded the live tests stop
skipping:

```bash
./do booktest -v
```

You should see ~14 offline tests pass + 5 live tests run (against
the default tenant). The live tests validate that Aito can predict
project success at >8 percentage points above base rate, that
`_relate` ranks engineered-reliable people as boost factors, and
that the staffing simulator moves P(success) by ≥5 pp when a
chaotic engineer is swapped for a reliable one.

---

## Troubleshooting

**`Aito returned 400 ... failed to open '<table>'`**
- Schema not created. Re-run `./do load-data --tenant=<id>`.
- The table name is case-sensitive.
- The endpoint requires the table to exist *before* querying.

**Empty views in the UI**
- `./do dev` is running but data wasn't loaded for that tenant.
  Check `/api/tenants` to see which DB each persona resolves to.
- `tolerate_missing_tables=True` is on, so missing tables don't
  crash — they show empty states. Run the loader for the affected
  persona.

**Rate-limit 429s during load**
- Aito's public free tier rate-limits batch writes. The loader's
  default 100-record batch is below the threshold; if you tighten
  the rate limit further you may need to add a small sleep between
  batches.

**Different URLs but same data**
- Two `.env` pairs accidentally point at the same DB. The loader
  detects this and skips duplicates; re-check your env vars if
  you expected three distinct datasets.

**Schema mismatch**
- If you change `SCHEMAS` in `data_loader.py` (column type, link
  target, nullability), you must `./do reset-data --tenant=<id>`
  to drop the old table before reload — Aito doesn't migrate
  in place.

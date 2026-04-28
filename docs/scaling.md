# Scaling the Predictive ERP Demo to a Real ERP-SaaS Tenant Base

This demo runs three tenants on three small Aito DBs. A real ERP SaaS
will have hundreds, thousands, or tens of thousands of tenants. This
doc walks through what changes — and what doesn't — at each scale
level, citing the actual code that already does most of the heavy
lifting.

The headline:
- The **per-tenant client + per-tenant cache key** model in the demo
  scales to ~1K tenants without changes
- 1K → 10K tenants: pool DBs, shard by tenant cohort, move the cache
  to Redis
- 10K → 100K tenants: introduce a tenant router, lazy-load clients,
  drive the cache from Aito's own persistence layer

What stays the same across all three tiers: the service modules
(`*_service.py`), the query shapes, the `$why` rendering, the UI.
That's the point — predictive-database queries are stateless;
scaling concerns live in the routing and caching tier above them.

---

## What the demo already does

### One AitoClient per tenant

`src/app.py:63-79`:

```python
def _build_clients() -> dict[TenantId, AitoClient]:
    return {
        t: AitoClient.from_creds(c.api_url, c.api_key, tolerate_missing=True)
        for t, c in config.tenants.items()
    }

_clients: dict[TenantId, AitoClient] = _build_clients()
```

Each tenant gets its own `AitoClient` resolved at startup. Requests
arriving with `X-Tenant: aurora` get routed to Aurora's client, which
points at Aurora's Aito DB. Cross-tenant data leakage is impossible
at the client level — there is no shared connection pool that knows
about both DBs.

### Per-tenant cache keys

`src/cache.py:95-103`:

```python
def tenant_key(tenant: str | None, key: str) -> str:
    """Build a tenant-scoped cache key.

    `tenant_key(None, "po_pending")`     → "po_pending"     (single-tenant)
    `tenant_key("metsa", "po_pending")` → "metsa:po_pending"
    """
    if not tenant:
        return key
    return f"{tenant}:{key}"
```

Every cache read/write goes through `tenant_key()`. Aurora's PO Queue
result lives at `aurora:po_pending`, Studio's at `studio:po_pending`.
The persistent layer (`prediction_cache` table in each tenant's Aito
DB) is partitioned the same way, by virtue of being a separate DB.

### Three-tier rate limit

`src/rate_limit.py`:

```
PER_IP_MAX = 60         # req / 60s / IP
PER_TENANT_MAX = 600    # req / 60s / tenant
GLOBAL_MAX = 1500       # req / 60s total
```

Three sliding-window counters, configurable via env vars:

1. **Per-IP** — one client can't drown everyone else
2. **Per-tenant** — abusing one persona can't degrade the others
3. **Global** — botnet hammering thousands of IPs each below the
   per-IP cap still hits the global ceiling

### `tolerate_missing=True`

The demo's per-tenant DBs may not all have every table loaded yet
(`Studio` has no `purchases` until `./do load-data --tenant=studio`
runs). The `AitoClient` flag returns canonical empty responses on
`failed to open '<table>'` instead of raising, so endpoints render
empty states rather than 500-ing.

In production this same flag is what lets you provision tenants
cheaply: an empty Aito DB is a few KB; the schema gets populated
on first batch upload from your existing data.

---

## Tier 1 — Single tenant (proof of concept)

**Range**: one customer, dev/staging environments, internal POCs.

**Architecture**: identical to the demo. One Aito DB, one FastAPI
process, in-memory + Aito-side cache.

**Bottleneck**: none, until you add the second tenant.

**Cost**: one Aito DB on shared.aito.ai (free tier covers ~10K rows
and ~1 QPS). Storage scales linearly with row count; query cost is
bounded by `_predict`'s `limit` parameter, not table size.

**Operational notes**: the `PUBLIC_DEMO=1` lockdown bundle in
`src/cache.py:35-38` (memory-only cache, no schema mutation) is the
right shape for a public single-tenant deployment where you want a
read-only API key.

---

## Tier 2 — 10–100 tenants

**Range**: typical Finnish SMB SaaS (Lemonsoft, Oscar Software, ERPly
mid-market) — hundreds of customers each running their own ERP instance.

**What changes**:

### Per-tenant Aito DBs are still fine

At 100 tenants × ~50K rows/tenant = 5M total rows distributed across
100 DBs. Each query still hits a single DB; storage and query cost
are linear in tenant count.

The `_build_clients` function in `src/app.py:63` already does this
correctly — config supplies a `(api_url, api_key)` pair per tenant,
the dict gets built at startup. Adding a tenant means adding a row
to your tenants table and restarting the FastAPI process (or
hot-reloading; see Tier 3).

### Cache layer moves out of process

The in-memory cache in `src/cache.py:39` (`_cache: dict[str, tuple[float, Any]]`)
assumes a single FastAPI worker. At Tier 2 you'll want:

- **Multiple FastAPI workers** (uvicorn `--workers 4`+) for concurrency
- **Redis** as the cache backing — keep the same `tenant_key()`
  prefix scheme, just swap the dict for a Redis client
- **Aito-side persistent cache** (the `prediction_cache` table) stays
  as the source of truth — Redis is a hot read tier in front of it

The cache contract is small (`get`, `set`, `clear`, `clear_all` in
`src/cache.py`), so swapping the backend is a ~50-line change.

### Onboarding pipeline

A real SaaS has a "create tenant" flow. That means:

1. Provision a new Aito DB via the [Aito API](https://aito.ai/docs/api/)
2. Upload schema (see `src/data_loader.py`)
3. Run a *historical bulk import* from the customer's existing ERP
   (the predictions only get good after ~6 months of history is
   loaded — the cold-start problem)
4. Register the new `(api_url, api_key)` in your tenants config
5. Optionally: pre-warm the prediction cache for the new tenant
   (see `_warm_one_tenant` in `src/app.py:133`)

---

## Tier 3 — 1 000–10 000 tenants

**Range**: vertical SaaS at scale (US-mid-market accounting, EU retail,
~thousand-customer professional services platforms).

**What breaks at the demo's architecture**:

### `_build_clients()` is wrong

You can't hold 1 000 `AitoClient` instances in memory at startup, and
you can't restart the process every time a tenant is added.

**Fix**: lazy client construction with an LRU cache.

```python
from functools import lru_cache

@lru_cache(maxsize=1024)
def _client_for(tenant_id: str) -> AitoClient:
    creds = lookup_credentials(tenant_id)  # from your tenants DB
    return AitoClient.from_creds(creds.api_url, creds.api_key,
                                  tolerate_missing=True)
```

The hot tenants (today's active users) stay in the LRU; idle
tenants get evicted. Construction is cheap (no network call) so
re-creation on cache miss is ~microseconds.

### One Aito DB per tenant gets expensive

At 10K tenants × $X/month/DB = real money. Two options:

**Option A: Pool by cohort**. Group tenants into ~100-tenant pools,
one Aito DB per pool, every row gets a `tenant_id` column. Every
query gets `where: { ..., tenant_id: <id> }` injected. The
[multi-tenant accounting demo](https://github.com/AitoDotAI/aito-accounting-demo)
shows this pattern at 256 tenants per DB.

**Option B: Stay one-DB-per-tenant**, but use a tenant router that
spins up DBs only on first activity. Cold-start latency on the first
request after a long idle is the trade-off (~few seconds for DB
provisioning).

We've seen Option A win for high-tenant-count low-data-per-tenant
workloads (small retailers, micro-businesses), Option B for
high-data-per-tenant workloads (mid-market manufacturers with
years of PO history).

### Cache moves to Aito-only

The `prediction_cache` table in each tenant's Aito DB becomes the
*sole* cache layer. Drop Redis. Aito's cache table is queryable
(`_search` by `cache_key`), persistent across restarts, and already
tenant-isolated.

Trade-off: every cache read is a network round-trip (~5-20ms). For
predictions where computation is 30-100ms, the cache still wins on
hit. For trivially fast computations (rule lookups), skip the cache.

### Rate limit moves to a shared store

`src/rate_limit.py` keeps state in process-local dicts. At Tier 3
that won't survive multiple FastAPI workers behind a load balancer.

**Fix**: Redis-backed sliding window counters, same three-tier
contract. Or hand off to your edge layer (Cloudflare, Fastly) for
the per-IP and global tiers; keep per-tenant in your app.

---

## Tier 4 — 100 000+ tenants

**Range**: hyperscale verticals (e-commerce platforms with hundreds
of thousands of micro-merchants, payment processors).

**The architecture is fundamentally different**:

### Pooled DBs are mandatory

Per-tenant DBs don't economically work at 100K. Pool sizes of
~1K-10K tenants per Aito DB, sharded by:

- **Geography** — EU customers in EU DBs (data residency)
- **Cohort** — high-volume tenants get smaller pool sizes; long-tail
  micro-tenants pack densely
- **Vertical** — different verticals have different schemas (retail
  ≠ professional services ≠ industrial); pool by vertical so the
  schema is uniform within a pool

### Predictions get pre-computed

At 100K tenants × N predictions/day the synchronous predict-on-request
pattern doesn't fit. Move to:

1. **Stream events** (PO created, invoice received, order placed) into
   a queue (Kafka, Pub/Sub)
2. **Worker pool** consumes events, calls `_predict`, writes the
   prediction back to a `predictions` table in the customer's Aito DB
3. **Frontend reads predictions**, never calls `_predict` directly

The latency budget shifts from "user is waiting" (sub-100ms) to
"user gets to the queue eventually" (sub-30s). That changes which
predictions are economical to compute.

### Aito sales conversation

This tier is where you should be talking to Aito sales directly:
- Dedicated cluster (not shared.aito.ai)
- EU vs US residency
- Volume pricing
- SLA guarantees

The demo doesn't try to model this — talk to
[hello@aito.ai](mailto:hello@aito.ai) for tier-4 architectures.

---

## What stays the same

Across every tier:

- The service modules (`po_service.py`, `smartentry_service.py`, …)
- The query shapes — `_predict`, `_relate`, `_evaluate`, `_search`,
  `_match` — never change
- The `$why` rendering pipeline (`src/why_processor.py` →
  `frontend/components/prediction/PredictionExplanation.tsx`)
- The 14 use-case patterns documented under [docs/use-cases/](use-cases/)
- The override-as-training-signal pattern — every accepted/overridden
  prediction is a row in `purchases` (or whichever table) that
  improves the next prediction. No retraining step at any tier.

That's the architectural payoff of treating predictions as queries
against a database. Scaling concerns are concentrated in the routing
and caching tier above them, not in the prediction logic itself.

---

## Performance numbers — measured on the demo

| Operation | Cold (first call) | Warm cache (subsequent) |
|-----------|-------------------|-------------------------|
| `_predict` single field | 30–100ms | <1ms |
| `_predict` multi-field (Smart Entry, 4 fields parallel) | 80–150ms | <2ms |
| `_relate` over 5K-row table | 100–300ms | <1ms |
| `_evaluate` per transaction | 30–80ms | <1ms |
| Page-load (cold) | 1–3s | 100–300ms |

These are measured on shared.aito.ai with ~12K total rows, a single
FastAPI worker, and the in-memory cache. Production numbers will
differ — see Tier 2/3 notes above for what changes.

For the demo's actual cache stats, hit `GET /api/cache/stats`.

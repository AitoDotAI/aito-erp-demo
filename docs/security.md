# Security

Threat model first, then concrete controls. The demo isn't a packaged
product — it's a public sales surface that needs to survive the
internet for as long as a sales conversation lasts, on the cheapest
infrastructure that does the job.

## Threat model

What we're protecting:
- **Aito API credentials** — the three per-tenant API keys. Burning
  through query budget in a day, or worse leaking the keys, both kill
  the demo.
- **Demo experience** — anything that prevents a real visitor from
  seeing the workflow loop (slow page, 500 errors, garbage entries
  in the live PO Queue).

What we're not trying to protect:
- The *content* — every record is fictional. There's no PII to leak.
- The *code* — Apache 2.0, public on GitHub.
- The *Aito query patterns* — published verbatim in the right-rail
  panels and use-case guides.

What's specifically in scope for this document:
1. API-key exposure (browser, repo, build artefacts).
2. Abuse vectors (rate limit, write paths, scrapers).
3. Information disclosure (schema, tenant URLs, internal state).
4. Operational hygiene (read-only keys, monitoring, freeze switches).

---

## Public-demo lockdown — `PUBLIC_DEMO=1`

Setting `PUBLIC_DEMO=1` in the deployed environment changes several
defaults. The flag is read in `src/app.py` (`_PUBLIC`) and `src/cache.py`.

### CORS lockdown

Default in dev: `Access-Control-Allow-Origin: *`. Public:
restricted to the comma-separated list in `CORS_ORIGINS`. Methods
narrowed to `GET, POST, OPTIONS`; headers narrowed to
`Content-Type, X-Tenant`.

Without this, any origin can call the API directly and exhaust your
Aito budget on someone else's site. Set `CORS_ORIGINS` to the deployed
frontend URL only.

### Three-tier rate limit

`src/rate_limit.py` enforces three sliding-window counters every
minute (60 s):

| Tier | Default | Tunable via | Stops |
|---|---|---|---|
| **Per-IP** | 60 req/min | `RATE_LIMIT_PER_IP` | One client drowning the demo |
| **Per-tenant** | 600 req/min | `RATE_LIMIT_PER_TENANT` | One persona's traffic degrading the others |
| **Global** | 1500 req/min | `RATE_LIMIT_GLOBAL` | A botnet of low-per-IP requests still hits the ceiling |

Localhost and `::1` bypass the per-IP tier so screenshot/booktest
tooling never trips itself. Real visitors get their own bucket per IP.

The 429 response carries:
- A specific message per tier (`"This persona is busy"` for tenant,
  `"Demo is at capacity"` for global) — different copy without
  revealing thresholds.
- `Retry-After: 60` so polite clients back off.

### `/api/tenants` — no raw URLs

In dev the endpoint returns each tenant's `aito_url` and a
`shared_with_default` flag. In `PUBLIC_DEMO` mode it returns just
`{id: "metsa"}`, etc. — no advertisement of which DB is which.

### `/api/schema` — disabled

Returns the raw Aito schema in dev (table types, column lists). In
`PUBLIC_DEMO` mode it returns 404. The schema isn't sensitive per se,
but there's no reason to publish it on the demo URL when GitHub already
has [data-model.md](data-model.md).

### Submission sanitisation

`src/submission_store.py` enforces:
- **TTL of 1 hour** — old submissions disappear from the queue.
- **FIFO cap of 50** — queue can't grow unbounded.
- **Per-field length clipping** — supplier ≤ 120, description ≤ 240,
  account_code ≤ 16, etc. Strips control characters.
- **EUR clamp** — amount coerced to `[0, 1_000_000]`.

This applies regardless of `PUBLIC_DEMO`; it's a hardening that
benefits dev too.

### Memory-only persistent cache

In `PUBLIC_DEMO` mode, `init_persistent_cache()` is a no-op:
- No `prediction_cache` schema PUT (would need write scope).
- No `set()` writes to Aito (same).
- The in-memory TTL cache is the only path.

This lets the public deployment run with **read-only Aito API keys**.
Trade-off: the cache is cold after every restart; the warmup loop
pays the predict cost again at startup. For a public demo's traffic
shape, this is acceptable — startup is rare.

---

## Operational hygiene

### Aito API keys

- Each per-tenant DB should be configured with a **read-only key**.
  All write paths in the public demo are gated off (cache, schema
  changes); only `_search` / `_predict` / `_relate` / `_match` /
  `_evaluate` are needed.
- Keys live only in `.env` (and the deployed environment's secret
  store). Never committed to git. `.env.example` documents which
  variables exist; the real values are out-of-band.
- Rotate keys if a deployment is compromised — the rotation needs no
  code change, just an env-var update + restart.

### What the browser sees

The frontend's bundle never contains an Aito key. All Aito calls go
through the FastAPI backend; the browser only knows about
`http://your-host/api/...`. Verify with `grep -r "AITO_" frontend/.next/static`
on the build output before deploying.

### Monitoring

Watch for the abuse signals:
- **429s/min** rising — someone's hammering. The per-tier reason in
  the response tells you which tier is tripping.
- **5xx/min** rising — backend issue or Aito-side outage.
- **Aito query count vs budget** — set a billing alert at 80% of
  monthly budget. Easy to overshoot in a viral moment.
- **Per-tenant request distribution** — wildly skewed traffic to one
  persona could mean a deep-link is doing the rounds (good) or a
  scraper is targeting a specific surface (bad).

### Kill switch

If the demo is being abused, the cleanest mitigation is an env-var
flip — set `RATE_LIMIT_GLOBAL=0` (or an absurdly low number),
restart, and the API returns 429 to everyone. The frontend keeps
serving its static export so visitors don't see a hard 5xx; they just
see "Demo is at capacity" until you flip it back.

---

## What we're not protecting against

Honest disclosure:
- **Authenticated user data** — there is none. No login, no PII.
  Don't add either without a fresh threat-model pass.
- **Schema evolution** — the deployed schema is whatever the loaded
  fixtures wrote. There's no migration story; if you change a column
  type in `data_loader.py` you need to drop and reload.
- **Privileged paths** — there are none in the demo. If you wire
  privileged paths in (e.g. a "promote rule" button that actually
  edits production rules), put authentication in front.
- **Dependency provenance** — Python deps via `uv`, frontend deps via
  `npm`. Both pull from public registries. Lockfiles are committed
  but no SBOM is generated. Add `npm audit` / `uv pip audit` to your
  pre-deploy checklist if compliance requires it.

---

## Compliance posture

The demo is intentionally not GDPR-relevant: every supplier name,
person name, project, and SKU is fabricated. The data files are
checked in or generated deterministically; nothing in the deployed
DB came from a real customer.

If you fork this and load real data, every assumption above changes
and the public-demo lockdown is the *floor*, not the ceiling. Talk to
your compliance team.

---

## Reporting an issue

Found a security issue in the demo code? Open a GitHub issue if the
code is public (not the deployed instance — that's the wrong place);
or email `info@aito.ai` for anything that shouldn't be discussed in
the open.

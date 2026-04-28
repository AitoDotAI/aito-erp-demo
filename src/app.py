"""FastAPI application — Predictive ERP demo backend.

Thin API layer that delegates to Aito. Each endpoint is a direct
window into an Aito capability, not an abstraction over it.

Multi-tenant routing
────────────────────
The frontend's TopBar profile switcher writes the selected tenant id
into localStorage. `apiFetch` reads it and sends `X-Tenant: <id>` on
every API request. This module:

  1. Builds an `AitoClient` per tenant id from `config.tenants`. When a
     persona is not separately configured, its client points at the
     single-tenant default — so existing single-DB deployments work
     unchanged.
  2. `client_from_request(request)` reads `X-Tenant` and returns
     `(tenant_id, client)`.
  3. Cache keys are scoped via `cache.tenant_key(tenant, ...)`, and
     the persistent-cache layer routes to the right Aito DB based on
     the same prefix.

Serves the Next.js static export from frontend/out/ when available.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.aito_client import AitoClient, AitoError
from src import cache
from src.config import DEFAULT_TENANT, TENANT_IDS, TenantId, load_config
from src.rate_limit import check_rate_limit

from src.po_service import DEMO_POS, compute_metrics, demo_pos_for, predict_batch, predict_single
from src import submission_store
from src.smartentry_service import INPUT_FIELDS, KNOWN_SUPPLIERS, known_suppliers_for, predict_fields
from src.approval_service import DEMO_APPROVAL_QUEUE, demo_approval_queue_for, predict_batch as predict_approval_batch
from src.anomaly_service import get_demo_anomalies
from src.supplier_service import get_supplier_intelligence
from src.rulemining_service import mine_rules, get_rule_summary
from src.catalog_service import get_incomplete, predict_attributes
from src.pricing_service import get_pricing_overview
from src.demand_service import get_demand_forecast
from src.inventory_service import get_inventory_status
from src.overview_service import get_overview
from src.project_service import get_portfolio, forecast_with_override
from src.recommendation_service import (
    get_overview as get_recommendation_overview,
    get_cross_sell as get_recommendation_cross_sell,
    get_similar as get_recommendation_similar,
)
from src.utilization_service import (
    get_overview as get_utilization_overview,
    forecast_assignment as forecast_utilization_assignment,
)

config = load_config()


def _build_clients() -> dict[TenantId, AitoClient]:
    """One AitoClient per tenant. In single-tenant mode every persona
    resolves to the same underlying DB — but cache keys still differ,
    so switching personas in the UI never serves stale data.

    `tolerate_missing=True` so that views querying a table that hasn't
    been loaded for a tenant (e.g. Studio's `purchases`/`products`
    before `./do load-data --tenant=studio` runs) render an empty
    state instead of crashing the request with a 500.
    """
    return {
        t: AitoClient.from_creds(c.api_url, c.api_key, tolerate_missing=True)
        for t, c in config.tenants.items()
    }


_clients: dict[TenantId, AitoClient] = _build_clients()


def client_from_request(request: Request) -> tuple[TenantId, AitoClient]:
    """Resolve `(tenant_id, AitoClient)` from the X-Tenant header.

    Falls back to DEFAULT_TENANT when the header is missing or names
    an unknown tenant — keeps curl-from-the-shell usable.
    """
    raw = request.headers.get("x-tenant", "").strip().lower()
    tenant: TenantId = raw if raw in TENANT_IDS else DEFAULT_TENANT  # type: ignore[assignment]
    return tenant, _clients[tenant]


def _tk(tenant: TenantId, key: str) -> str:
    """Shorthand: scope a cache key to a tenant."""
    return cache.tenant_key(tenant, key)


def _warm_cache() -> None:
    """Pre-compute cacheable endpoints for every tenant on startup."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    def warm():
        # Initialise each tenant's persistent cache table once. Single-
        # tenant deployments register the same client three times, which
        # is harmless — the table already exists and PUT is idempotent.
        for tenant_id, client in _clients.items():
            if client.check_connectivity():
                cache.init_persistent_cache(client, tenant=tenant_id)

        if config.is_multi_tenant:
            tenants_to_warm: list[TenantId] = list(TENANT_IDS)
        else:
            # No point warming three identical tenants pointing at the
            # same DB — pick one and the rest will share its cache
            # entries on the underlying Aito (and pull through on first
            # request via the persistent layer).
            tenants_to_warm = [DEFAULT_TENANT]

        for tenant_id in tenants_to_warm:
            client = _clients[tenant_id]
            if not client.check_connectivity():
                print(f"  [{tenant_id}] Aito unreachable — skipping warmup.")
                continue
            print(f"Warming cache for tenant '{tenant_id}'...")
            _warm_one_tenant(tenant_id, client)

        print("Cache warm.")

    threading.Thread(target=warm, daemon=True).start()


def _warm_one_tenant(tenant_id: TenantId, aito: AitoClient) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def warm_or_load(key: str, compute_fn) -> None:
        scoped = _tk(tenant_id, key)
        existing = cache.get(scoped)
        if existing:
            print(f"  [{tenant_id}] loaded: {key} (from cache)")
            return
        try:
            result = compute_fn()
            cache.set(scoped, result)
            print(f"  [{tenant_id}] computed: {key}")
        except Exception as e:
            print(f"  [{tenant_id}] error warming {key}: {e}")

    def warm_po():
        def compute():
            predictions = predict_batch(aito, demo_pos_for(tenant_id), tenant=tenant_id)
            return {
                "pos": [p.to_dict() for p in predictions],
                "metrics": compute_metrics(predictions),
            }
        warm_or_load("po_pending", compute)

    def warm_approval():
        def compute():
            predictions = predict_approval_batch(aito, demo_approval_queue_for(tenant_id))
            return {"approvals": [p.to_dict() for p in predictions]}
        warm_or_load("approval_queue", compute)

    def warm_anomalies():
        warm_or_load("anomalies_scan", lambda: {
            "anomalies": [f.to_dict() for f in get_demo_anomalies(aito, tenant_id)],
        })

    def warm_supplier():
        warm_or_load("supplier_overview", lambda: get_supplier_intelligence(aito).to_dict())

    def warm_rules():
        def compute():
            candidates = mine_rules(aito)
            return {
                "candidates": [c.to_dict() for c in candidates],
                "summary": get_rule_summary(candidates),
            }
        warm_or_load("rules_candidates", compute)

    def warm_catalog():
        def compute():
            products, total = get_incomplete(aito)
            return {"products": [p.to_dict() for p in products], "total": total}
        warm_or_load("catalog_incomplete", compute)

    def warm_pricing():
        warm_or_load("pricing_overview", lambda: get_pricing_overview(aito, tenant=tenant_id))

    def warm_demand():
        warm_or_load("demand_forecast", lambda: get_demand_forecast(aito, tenant=tenant_id))

    def warm_inventory():
        warm_or_load("inventory_status", lambda: get_inventory_status(aito, tenant=tenant_id).to_dict())

    def warm_overview():
        warm_or_load("overview_metrics", lambda: get_overview(aito).to_dict())

    def warm_projects():
        warm_or_load("projects_portfolio", lambda: get_portfolio(aito).to_dict())

    def warm_recommendations():
        # Aurora-only feature; skip for other personas (the API also
        # 404s for them, see RECOMMENDATIONS_TENANTS below).
        if tenant_id != "aurora":
            return
        warm_or_load("recommendations_overview",
                     lambda: get_recommendation_overview(aito).to_dict())

    def warm_utilization():
        warm_or_load("utilization_overview",
                     lambda: get_utilization_overview(aito).to_dict())

    def warm_smartentry():
        import json as _json
        from concurrent.futures import ThreadPoolExecutor as TPE
        def warm_supplier_entry(supplier):
            where = {"supplier": supplier}
            key = "smartentry:" + _json.dumps(where, sort_keys=True)
            warm_or_load(key, lambda: predict_fields(aito, where).to_dict())
        with TPE(max_workers=4) as vpool:
            list(vpool.map(warm_supplier_entry, known_suppliers_for(tenant_id)))

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [
            pool.submit(warm_po),
            pool.submit(warm_approval),
            pool.submit(warm_anomalies),
            pool.submit(warm_supplier),
            pool.submit(warm_rules),
            pool.submit(warm_smartentry),
        ]
        for f in futures:
            try:
                f.result()
            except Exception as e:
                print(f"  [{tenant_id}] warmup error: {e}")

    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = [
            pool.submit(warm_catalog),
            pool.submit(warm_pricing),
            pool.submit(warm_demand),
            pool.submit(warm_inventory),
            pool.submit(warm_projects),
            pool.submit(warm_recommendations),
            pool.submit(warm_utilization),
        ]
        for f in futures:
            try:
                f.result()
            except Exception as e:
                print(f"  [{tenant_id}] warmup error: {e}")

    warm_overview()


_warm_cache()

app = FastAPI(
    title="Predictive ERP — Aito Demo API",
    version="0.1.0",
)

# CORS: in PUBLIC_DEMO mode we lock to specific origins (set via
# CORS_ORIGINS env, comma-separated). Locally we keep the permissive
# default so dev tooling and curl-from-the-shell still work.
import os as _os

_PUBLIC = _os.environ.get("PUBLIC_DEMO", "").lower() in ("1", "true", "yes")
_cors_origins_env = _os.environ.get("CORS_ORIGINS", "").strip()
if _PUBLIC and _cors_origins_env:
    _allow_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
else:
    _allow_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    # Only the headers the frontend actually sends — narrower than "*"
    # while still permitting the X-Tenant routing header.
    allow_headers=["Content-Type", "X-Tenant"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        client_ip = request.client.host if request.client else "unknown"
        # Read the same X-Tenant header the routing middleware uses so
        # the per-tenant tier can attribute the call correctly.
        tenant = (request.headers.get("x-tenant") or "").strip().lower() or None
        allowed, reason = check_rate_limit(client_ip, tenant=tenant)
        if not allowed:
            messages = {
                "ip":     "Rate limit exceeded for your IP. Try again in a minute.",
                "tenant": "This persona is busy. Try again in a moment, or switch profiles.",
                "global": "Demo is at capacity. Please try again in a minute.",
            }
            return JSONResponse(
                status_code=429,
                content={"error": messages.get(reason, "Rate limit exceeded.")},
                headers={"Retry-After": "60"},
            )
    return await call_next(request)


# ── Health & schema ──────────────────────────────────────────────

@app.get("/api/health")
def health(request: Request):
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "health")
    cached = cache.get(cache_key)
    if cached:
        return cached
    connected = aito.check_connectivity()
    result = {
        "status": "ok",
        "tenant": tenant,
        "aito_connected": connected,
        "aito_url": aito._base_url,
        "multi_tenant": config.is_multi_tenant,
    }
    cache.set(cache_key, result, ttl=60)
    return result


@app.get("/api/tenants")
def tenants_list():
    """Surface what the backend knows about — useful for the UI to
    confirm the multi-tenant config and for ops to verify env vars.

    In PUBLIC_DEMO mode we omit the raw Aito URLs (don't advertise
    which DBs are which on the public internet)."""
    base = {
        "default": DEFAULT_TENANT,
        "multi_tenant": config.is_multi_tenant,
    }
    if _PUBLIC:
        base["tenants"] = [{"id": t} for t in TENANT_IDS]
    else:
        base["tenants"] = [
            {
                "id": t,
                "aito_url": _clients[t]._base_url,
                "shared_with_default": _clients[t]._base_url == config.aito_api_url
                                       and config.is_multi_tenant is False,
            }
            for t in TENANT_IDS
        ]
    return base


@app.get("/api/schema")
def schema(request: Request):
    """The raw Aito schema is useful in dev (lets you inspect column
    types) but reveals internals on a public demo. Lock it down in
    PUBLIC_DEMO mode."""
    if _PUBLIC:
        return JSONResponse(
            status_code=404,
            content={"error": "Not available in public demo mode."},
        )
    _, aito = client_from_request(request)
    try:
        return aito.get_schema()
    except AitoError as exc:
        return {"error": str(exc), "status_code": exc.status_code}


# ── Procurement ──────────────────────────────────────────────────

@app.get("/api/po/pending")
def po_pending(request: Request):
    """PO queue with live Aito predictions for account, cost center, approver."""
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "po_pending")
    cached = cache.get(cache_key)
    submissions = submission_store.list_submissions()
    if cached and not submissions:
        return cached

    demo_predictions = predict_batch(aito, demo_pos_for(tenant), tenant=tenant)

    submitted_predictions = []
    for sub in submissions:
        po_input = {
            "purchase_id": sub["purchase_id"],
            "supplier": sub["supplier"],
            "description": sub["description"] or sub["supplier"],
            "amount_eur": sub["amount_eur"],
            "category": sub.get("category", "general"),
        }
        try:
            pred = predict_single(aito, po_input, tenant=tenant)
            submitted_predictions.append(pred)
        except Exception:
            continue

    all_predictions = submitted_predictions + demo_predictions
    result = {
        "pos": [p.to_dict() for p in all_predictions],
        "metrics": compute_metrics(all_predictions),
    }
    if not submissions:
        cache.set(cache_key, result)
    return result


@app.get("/api/smartentry/suppliers")
def smartentry_suppliers(request: Request):
    tenant, _ = client_from_request(request)
    return {"suppliers": known_suppliers_for(tenant)}


@app.post("/api/smartentry/predict")
def smartentry_predict(body: dict, request: Request):
    import json as _json
    tenant, aito = client_from_request(request)
    where = {k: v for k, v in body.items() if k in INPUT_FIELDS and v}
    if not where:
        return {"error": "at least one field is required"}
    cache_key = _tk(tenant, "smartentry:" + _json.dumps(where, sort_keys=True))
    cached = cache.get(cache_key)
    if cached:
        return cached
    entry_result = predict_fields(aito, where)
    result = entry_result.to_dict()
    cache.set(cache_key, result, ttl=300)
    return result


@app.post("/api/po/submit")
def po_submit(body: dict, request: Request):
    tenant, _ = client_from_request(request)
    required = ["supplier", "amount_eur"]
    missing = [k for k in required if not body.get(k)]
    if missing:
        return {"error": f"missing fields: {', '.join(missing)}"}, 400

    record = {
        "supplier": str(body["supplier"]),
        "description": str(body.get("description", "")),
        "amount_eur": float(body["amount_eur"]),
        "category": str(body.get("category", "general")),
        "cost_center": body.get("cost_center"),
        "account_code": body.get("account_code"),
        "approver": body.get("approver"),
        "project": body.get("project"),
        "source": body.get("source", "smart_entry"),
    }
    entry = submission_store.add_submission(record)
    # Invalidate cached PO queue for this tenant.
    cache._cache.pop(_tk(tenant, "po_pending"), None)
    return {"ok": True, "purchase_id": entry["purchase_id"], "submitted_at": entry["submitted_at"]}


@app.get("/api/po/submissions")
def po_submissions():
    return {"submissions": submission_store.list_submissions()}


@app.get("/api/approval/queue")
def approval_queue(request: Request):
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "approval_queue")
    cached = cache.get(cache_key)
    if cached:
        return cached
    predictions = predict_approval_batch(aito, demo_approval_queue_for(tenant))
    result = {"approvals": [p.to_dict() for p in predictions]}
    cache.set(cache_key, result)
    return result


# ── Intelligence ─────────────────────────────────────────────────

@app.get("/api/anomalies/scan")
def anomalies_scan(request: Request):
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "anomalies_scan")
    cached = cache.get(cache_key)
    if cached:
        return cached
    flags = get_demo_anomalies(aito, tenant)
    result = {"anomalies": [f.to_dict() for f in flags]}
    cache.set(cache_key, result)
    return result


@app.get("/api/supplier/overview")
def supplier_overview(request: Request):
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "supplier_overview")
    cached = cache.get(cache_key)
    if cached:
        return cached
    intel = get_supplier_intelligence(aito)
    result = intel.to_dict()
    cache.set(cache_key, result)
    return result


@app.get("/api/rules/candidates")
def rules_candidates(request: Request):
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "rules_candidates")
    cached = cache.get(cache_key)
    if cached:
        return cached
    candidates = mine_rules(aito)
    result = {
        "candidates": [c.to_dict() for c in candidates],
        "summary": get_rule_summary(candidates),
    }
    cache.set(cache_key, result)
    return result


# ── Product ──────────────────────────────────────────────────────

@app.get("/api/catalog/incomplete")
def catalog_incomplete(request: Request):
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "catalog_incomplete")
    cached = cache.get(cache_key)
    if cached:
        return cached
    products, total = get_incomplete(aito)
    result = {"products": [p.to_dict() for p in products], "total": total}
    cache.set(cache_key, result)
    return result


@app.post("/api/catalog/predict")
def catalog_predict(body: dict, request: Request):
    tenant, aito = client_from_request(request)
    sku = body.get("sku")
    if not sku:
        return {"error": "sku is required"}
    cache_key = _tk(tenant, f"catalog_predict:{sku}")
    cached = cache.get(cache_key)
    if cached:
        return cached
    enrichment = predict_attributes(aito, sku)
    result = enrichment.to_dict()
    cache.set(cache_key, result, ttl=300)
    return result


@app.get("/api/pricing/estimate")
def pricing_estimate(request: Request):
    tenant, aito = client_from_request(request)
    return cache.get_or_compute(
        _tk(tenant, "pricing_overview"),
        lambda: get_pricing_overview(aito, tenant=tenant),
    )


@app.get("/api/demand/forecast")
def demand_forecast(request: Request):
    tenant, aito = client_from_request(request)
    return cache.get_or_compute(
        _tk(tenant, "demand_forecast"),
        lambda: get_demand_forecast(aito, tenant=tenant),
    )


@app.get("/api/inventory/status")
def inventory_status(request: Request):
    tenant, aito = client_from_request(request)
    return cache.get_or_compute(
        _tk(tenant, "inventory_status"),
        lambda: get_inventory_status(aito, tenant=tenant).to_dict(),
    )


# ── Recommendations (Aurora retail story) ────────────────────────
#
# Cross-sell + similar-product recommendations only ship for the
# Aurora persona — the side-nav already filters the link out of
# Metsä and Studio because their `orders` and `products` tables
# don't have the density Recommendations needs to be credible.
# This guard mirrors that decision at the API layer so anyone
# curling the endpoint directly gets a clean 404 instead of empty
# arrays / mismatched supplier rows.

RECOMMENDATIONS_TENANTS: set[TenantId] = {"aurora"}


def _require_recommendations_tenant(tenant: TenantId) -> None:
    if tenant not in RECOMMENDATIONS_TENANTS:
        raise HTTPException(
            status_code=404,
            detail=f"recommendations are not available for tenant '{tenant}'",
        )


@app.get("/api/recommendations/overview")
def recommendations_overview(request: Request):
    """Browsable product list + trending ribbon for the picker."""
    tenant, aito = client_from_request(request)
    _require_recommendations_tenant(tenant)
    cache_key = _tk(tenant, "recommendations_overview")
    cached = cache.get(cache_key)
    if cached:
        return cached
    overview = get_recommendation_overview(aito)
    result = overview.to_dict()
    cache.set(cache_key, result)
    return result


@app.get("/api/recommendations/cross-sell")
def recommendations_cross_sell(request: Request, sku: str):
    """`Customers who bought X also bought Y` — month co-occurrence."""
    tenant, aito = client_from_request(request)
    _require_recommendations_tenant(tenant)
    cache_key = _tk(tenant, f"recommendations_cross:{sku}")
    cached = cache.get(cache_key)
    if cached:
        return cached
    items = get_recommendation_cross_sell(aito, sku)
    result = {"items": [i.to_dict() for i in items]}
    cache.set(cache_key, result, ttl=600)
    return result


@app.get("/api/recommendations/similar")
def recommendations_similar(request: Request, sku: str):
    """Similar products by category + supplier + price band."""
    tenant, aito = client_from_request(request)
    _require_recommendations_tenant(tenant)
    cache_key = _tk(tenant, f"recommendations_similar:{sku}")
    cached = cache.get(cache_key)
    if cached:
        return cached
    items = get_recommendation_similar(aito, sku)
    result = {"items": [i.to_dict() for i in items]}
    cache.set(cache_key, result, ttl=600)
    return result


# ── Utilization & Capacity (Studio services story) ──────────────

@app.get("/api/utilization/overview")
def utilization_overview(request: Request):
    """Per-person current load + at-risk allocation + historical avg."""
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "utilization_overview")
    cached = cache.get(cache_key)
    if cached:
        return cached
    overview = get_utilization_overview(aito)
    result = overview.to_dict()
    cache.set(cache_key, result)
    return result


@app.post("/api/utilization/forecast")
def utilization_forecast(body: dict, request: Request):
    """`If we put person X on a typical {project_type}, what role
    and allocation do they take?` Uses _predict on the assignments
    table joined to projects.project_type."""
    _, aito = client_from_request(request)
    person = body.get("person")
    ptype = body.get("project_type")
    if not person or not ptype:
        return {"error": "person and project_type are required"}
    forecast = forecast_utilization_assignment(aito, person, ptype)
    return forecast.to_dict()


# ── Operations / Projects ────────────────────────────────────────

@app.get("/api/projects/portfolio")
def projects_portfolio(request: Request):
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "projects_portfolio")
    cached = cache.get(cache_key)
    if cached:
        return cached
    overview = get_portfolio(aito)
    result = overview.to_dict()
    cache.set(cache_key, result)
    return result


@app.post("/api/projects/forecast")
def projects_forecast(body: dict, request: Request):
    _, aito = client_from_request(request)
    project_id = body.get("project_id")
    if not project_id:
        return {"error": "project_id is required"}
    override = body.get("team_members_override")
    return forecast_with_override(aito, project_id, override)


# ── Overview ─────────────────────────────────────────────────────

@app.get("/api/overview/metrics")
def overview_metrics(request: Request):
    tenant, aito = client_from_request(request)
    cache_key = _tk(tenant, "overview_metrics")
    cached = cache.get(cache_key)
    if cached:
        return cached
    metrics = get_overview(aito)
    result = metrics.to_dict()
    cache.set(cache_key, result)
    return result


# ── Static files ─────────────────────────────────────────────────

_frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "out"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")

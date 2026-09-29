#!/usr/bin/env python3
"""Live smoke of the deployed ERP demo: every view a visitor opens, read-only.

    python scripts/live_smoke.py                       # https://erp.aito.ai
    python scripts/live_smoke.py --base http://localhost:8400

Fails when a route errors OR comes back hollow where the tenant's data
guarantees content. Board td-20260929184223822327: across the demos, empty-on-
error handlers let a broken query look like "no data" (one did, for nine
months, in the grocery demo), and on 29.9 this demo's Demand view read all
zeros and Inventory "overstock, 999 days" on every tenant with every route
answering 200.

Read-only by construction: GETs, plus the planner POSTs that only read (they
predict and estimate; nothing is stored). With PUBLIC_DEMO set, the server
writes nothing to Aito (src/cache.py). No key is needed: the deployed server
uses its own.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

LIVE_BASE = "https://erp.aito.ai"
SLOW_SECONDS = 20.0


@dataclass
class Step:
    name: str
    tenant: str
    path: str
    check: Callable[[Any], str]
    body: dict | None = None            # a POST body, for the read-only planner calls


def _list(body: dict, key: str, what: str, at_least: int = 1) -> list:
    value = body.get(key)
    assert isinstance(value, list), f"{what}: no `{key}` list in {sorted(body)[:8]}"
    assert len(value) >= at_least, f"{what}: `{key}` has {len(value)} items, expected >= {at_least}"
    return value


def nonempty(key: str, what: str, at_least: int = 1) -> Callable[[dict], str]:
    def check(body: dict) -> str:
        return f"{len(_list(body, key, what, at_least))} {key}"
    return check


def check_tenants(body: dict) -> str:
    names = {t.get("id") or t.get("tenant") or t.get("name") for t in _list(body, "tenants", "tenants", 3)}
    return f"{len(names)} tenants"


def check_demand(body: dict) -> str:
    """Demand is computed from `orders` history. Some product must have history
    and a non-zero Aito forecast; all-zero is the 29.9 failure."""
    products = _list(body, "products", "demand forecast")
    live = [p for p in products
            if p.get("history") and any((h.get("aito") or 0) > 0 for h in p.get("horizon", []))]
    assert live, (f"none of {len(products)} products has history and a non-zero forecast "
                  "(29.9: every hero SKU read history [] and forecast 0)")
    return f"{len(live)}/{len(products)} products forecast from history"


def check_inventory(body: dict) -> str:
    """Days of supply follow from the demand forecast: if every item reads
    overstock, the forecast behind it is zero."""
    items = _list(body, "items", "inventory")
    counts = body.get("counts") or {}
    overstock = counts.get("overstock", sum(1 for i in items if i.get("status") == "overstock"))
    assert overstock < len(items), f"all {len(items)} items read overstock: demand forecast is zero?"
    return f"{len(items)} items, {overstock} overstock"


def check_pricing(body: dict) -> str:
    """Quotes are scored against Aito's estimate from price history."""
    products = _list(body, "products", "pricing")
    quotes = [q for p in products for q in p.get("quotes", [])]
    assert quotes, "no quotes scored"
    estimated = [q for q in quotes if (q.get("aito") or 0) > 0]
    assert estimated, f"none of {len(quotes)} quotes has an Aito estimate"
    flagged = [q for q in quotes if q.get("flagged")]
    return f"{len(estimated)}/{len(quotes)} quotes estimated, {len(flagged)} flagged"


def check_portfolio(body: dict) -> str:
    projects = _list(body, "projects", "portfolio")
    scored = [p for p in projects if p.get("success_p") is not None]
    assert scored, f"none of {len(projects)} projects carries success_p"
    return f"{len(scored)}/{len(projects)} projects scored"


def check_plan(body: dict) -> str:
    roles = _list(body, "roles", "plan")
    staffed = [r for r in roles if r.get("candidates")]
    assert staffed, f"no role of {len(roles)} has candidates"
    return f"{len(roles)} roles, {len(staffed)} with candidates"


def check_estimate(body: dict) -> str:
    assert not body.get("error"), body.get("error")
    assert (body.get("cost_eur") or 0) > 0, f"no cost estimate: {body.get('cost_eur')!r}"
    assert (body.get("neighbour_count") or 0) > 0, "estimate has no comparable projects behind it"
    return f"€{body['cost_eur']:,.0f}, {body.get('duration_days')} d, {body['neighbour_count']} neighbours"


# Each view runs on a tenant that SHOWS it (frontend/lib/tenants.ts hideRoutes):
# a route that answers for a tenant whose navigation hides it guards nothing.
# Empty by design, so not checked: matching/recommendations/catalog/demand/
# pricing on metsa and studio (no invoice_lines/impressions), utilization on
# metsa and aurora, projects/planner/forecast on aurora. The PO queue has 1-2
# `source: "review"` rows per tenant since #50: never assert zero review rows.
STEPS = [
    Step("tenants", "metsa", "/api/tenants", check_tenants),
    Step("po/pending", "metsa", "/api/po/pending", nonempty("pos", "PO queue")),
    Step("approval/queue", "metsa", "/api/approval/queue", nonempty("approvals", "approvals")),
    Step("anomalies/scan", "metsa", "/api/anomalies/scan", nonempty("anomalies", "anomalies")),
    Step("supplier/overview", "metsa", "/api/supplier/overview", nonempty("top_suppliers", "suppliers")),
    Step("rules/candidates", "metsa", "/api/rules/candidates", nonempty("candidates", "rule mining")),
    Step("catalog/incomplete", "aurora", "/api/catalog/incomplete", nonempty("products", "catalog")),
    Step("matching/batch", "aurora", "/api/matching/batch", nonempty("lines", "invoice matching")),
    Step("recommendations/overview", "aurora", "/api/recommendations/overview",
         nonempty("products", "recommendations")),
    # #40's live bug: cross-sell came back empty while the overview's products were full
    Step("recommendations/cross-sell", "aurora", "/api/recommendations/cross-sell?sku={first_sku}",
         nonempty("items", "cross-sell")),
    Step("recommendations/similar", "aurora", "/api/recommendations/similar?sku={first_sku}",
         nonempty("items", "similar products")),
    Step("demand/forecast", "aurora", "/api/demand/forecast", check_demand),
    Step("inventory/status", "metsa", "/api/inventory/status", check_inventory),
    Step("pricing/estimate", "aurora", "/api/pricing/estimate", check_pricing),
    Step("utilization/overview", "studio", "/api/utilization/overview", nonempty("rows", "utilization")),
    Step("projects/portfolio", "metsa", "/api/projects/portfolio", check_portfolio),
    Step("forecast/outlook", "metsa", "/api/forecast/outlook", nonempty("months", "outlook")),
    Step("overview/metrics", "metsa", "/api/overview/metrics", nonempty("prediction_quality", "overview")),
    Step("planner/plan", "metsa", "/api/planner/plan", check_plan,
         {"customer": "C", "project_type": "construction", "quoted_eur": 250000,
          "duration_days": 90, "team_size": 4, "site": "Helsinki"}),
    Step("planner/estimate", "metsa", "/api/planner/estimate", check_estimate,
         {"project_type": "construction"}),
]


def fetch(base: str, step: Step, timeout: float, path: str | None = None) -> Any:
    data = None if step.body is None else json.dumps(step.body).encode()
    req = urllib.request.Request(base + (path or step.path), data=data, method="POST" if data else "GET",
                                 headers={"X-Tenant": step.tenant, "content-type": "application/json",
                                          "user-agent": "erp-live-smoke"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default=LIVE_BASE)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--pause", type=float, default=0.5,
                        help="seconds between calls (PUBLIC_DEMO rate-limits)")
    args = parser.parse_args()

    print(f"ERP live smoke — {args.base}, {len(STEPS)} views\n")
    failures = []
    first_sku = None
    for step in STEPS:
        started = time.monotonic()
        try:
            path = step.path
            if "{first_sku}" in path:
                # the SKU a visitor would click: the first product the overview lists
                if first_sku is None:
                    overview = fetch(args.base, Step("", step.tenant, "/api/recommendations/overview", str),
                                     args.timeout)
                    first_sku = (overview.get("products") or [{}])[0].get("sku")
                    assert first_sku, "the recommendations overview lists no product to open"
                path = path.replace("{first_sku}", urllib.parse.quote(first_sku))
            summary = step.check(fetch(args.base, step, args.timeout, path))
            marker = "SLOW" if time.monotonic() - started > SLOW_SECONDS else "ok  "
            print(f"  {marker}  {step.name:<26} [{step.tenant}] {summary}  ({time.monotonic() - started:.1f}s)")
        except Exception as exc:   # noqa: BLE001 -- record every failure and walk on (RemoteDisconnected,
            # ConnectionResetError and ssl.SSLError are OSErrors, not URLErrors)
            reason = f"{type(exc).__name__}: {exc}"
            failures.append((step.name, reason))
            print(f"  FAIL  {step.name:<26} [{step.tenant}] {reason}  ({time.monotonic() - started:.1f}s)")
        time.sleep(args.pause)

    print()
    if failures:
        print(f"{len(failures)} of {len(STEPS)} views FAILED:")
        for name, reason in failures:
            print(f"  {name}: {reason}")
        return 1
    print(f"All {len(STEPS)} views answered with content.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

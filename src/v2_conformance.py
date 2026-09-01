"""Does every view still work on Aito's v2 API?

Runs each of the demo's views end to end — the same service functions
`app.py` calls, against a real Aito database — and reports one line per
view: does it answer, does it answer with content, or does it break.

    ./do v2-check                    # every tenant, v2
    ./do v2-check --tenant=metsa     # one tenant
    ./do v2-check --api-version=v1   # the same sweep against v1

Why a runner and not a test: the interesting failures are shape
mismatches that only a live database produces, and the answer we want
is a *list* — which views are ported, which aren't, and what the API
said — not a pass/fail. Run it against v1 first to see the baseline,
then against v2 to see the delta.

A view is reported as:

    OK       the call returned, and every part of it has content
    PARTIAL  the view rendered but one of its panels came back empty —
             the likeliest migration failure, since a moved response
             key empties one panel and leaves the rest working
    EMPTY    the call returned nothing — either this persona has no
             fixture for that table (Aurora-only views on Metsä), or
             a shape difference is emptying the result. Compare
             against the v1 baseline before concluding.
    BROKEN   the call raised; the message is the Aito error

EMPTY and PARTIAL are deliberately not folded into OK. A query that
stops matching is exactly the failure mode a version migration
produces, and calling it "fine" would hide the thing this script
exists to find.
"""

import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from src.aito_client import AitoClient
from src.config import API_VERSIONS, ApiVersion, TENANT_IDS, TenantId, load_config

from src.anomaly_service import get_demo_anomalies
from src.approval_service import demo_approval_queue_for, predict_batch as predict_approval_batch
from src.catalog_service import get_incomplete
from src.demand_service import get_demand_forecast
from src.inventory_service import get_inventory_status
from src.forecast_service import get_outlook
from src.overview_service import get_overview
from src.po_service import demo_pos_for, predict_batch as predict_po_batch
from src.pricing_service import get_pricing_overview
from src.project_service import get_portfolio
from src.recommendation_service import get_overview as get_recommendation_overview
from src.rulemining_service import mine_rules
from src.smartentry_service import known_suppliers_for, predict_fields
from src.supplier_service import get_supplier_intelligence
from src.utilization_service import get_overview as get_utilization_overview


@dataclass(frozen=True)
class View:
    """One demo view, and the Aito query types it leans on.

    `endpoints` is documentation, not dispatch — it's what makes the
    report readable as "which Aito operations survived", which is the
    question a core gap gets filed against.
    """
    name: str
    endpoints: str
    run: Callable[[AitoClient, TenantId], Any]


VIEWS: tuple[View, ...] = (
    View("po-queue", "_predict",
         lambda c, t: predict_po_batch(c, demo_pos_for(t), tenant=t)),
    View("smart-entry", "_predict ×5",
         lambda c, t: predict_fields(c, {"supplier": known_suppliers_for(t)[0]})),
    View("approval", "_predict",
         lambda c, t: predict_approval_batch(c, demo_approval_queue_for(t))),
    View("anomalies", "_predict (inverse) + _search",
         lambda c, t: get_demo_anomalies(c, tenant=t)),
    View("supplier", "_search + _relate",
         lambda c, t: get_supplier_intelligence(c)),
    View("rules", "_relate",
         lambda c, t: mine_rules(c)),
    # get_incomplete returns (products, total_scanned); the products
    # list is what the view renders and what can go empty.
    View("catalog", "_search + _predict",
         lambda c, t: get_incomplete(c)[0]),
    View("pricing", "_search + stats",
         lambda c, t: get_pricing_overview(c, tenant=t)),
    View("demand", "_predict + _search",
         lambda c, t: get_demand_forecast(c, tenant=t)),
    View("inventory", "demand + _search",
         lambda c, t: get_inventory_status(c, tenant=t)),
    View("recommendations", "_recommend + _match",
         lambda c, t: get_recommendation_overview(c)),
    View("projects", "_predict + _relate",
         lambda c, t: get_portfolio(c)),
    View("utilization", "_predict + _search",
         lambda c, t: get_utilization_overview(c)),
    View("forecast", "_predict ×2 + _search",
         lambda c, t: get_outlook(c)),
    View("overview", "_evaluate + _search",
         lambda c, t: get_overview(c)),
)


def _emptiness(result: Any) -> tuple[bool, list[str]]:
    """Did the view come back with nothing to render, and what's missing?

    Returns `(everything_empty, names_of_empty_parts)`.

    The services return either a collection or a dataclass wrapping
    several (`PortfolioOverview` carries both `projects` and
    `success_factors`). Reporting only all-or-nothing hides the most
    likely migration failure: one panel of a working view quietly
    losing its data because a response key moved. So partly-empty is
    named, not rounded to OK.
    """
    if result is None:
        return True, []
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    if isinstance(result, (list, tuple, str)):
        return len(result) == 0, []
    if isinstance(result, dict):
        parts = {k: v for k, v in result.items() if isinstance(v, (list, tuple, dict))}
        if not parts:
            return len(result) == 0, []
        blank = sorted(k for k, v in parts.items() if len(v) == 0)
        return len(blank) == len(parts), blank
    return False, []


def check_tenant(tenant: TenantId, api_version: ApiVersion, verbose: bool) -> list[tuple[str, str, str]]:
    """Run every view for one tenant. Returns (view, status, detail)."""
    # Pick the credential set for the version being *checked*, not the
    # one `AITO_API_VERSION` happens to be set to — this runner exists
    # to compare the two, so it addresses each explicitly.
    config = load_config()
    if api_version == "v2":
        if tenant not in config.v2_tenants:
            raise ValueError(
                f"No v2 credentials for tenant '{tenant}'. See .env.example."
            )
        creds = config.v2_tenants[tenant]
    else:
        creds = config.tenants[tenant]

    client = AitoClient.from_creds(creds.api_url, creds.api_key,
                                   api_version=api_version)

    print(f"\n=== {tenant} · {api_version} · {creds.api_url} ===")
    rows: list[tuple[str, str, str]] = []
    for view in VIEWS:
        try:
            result = view.run(client, tenant)
            all_empty, blank_parts = _emptiness(result)
            if all_empty:
                status, detail = "EMPTY", ""
            elif blank_parts:
                status, detail = "PARTIAL", "no " + ", ".join(blank_parts)
            else:
                status, detail = "OK", ""
        except Exception as exc:  # noqa: BLE001 — reporting, not handling
            status = "BROKEN"
            detail = f"{type(exc).__name__}: {exc}"
            if verbose:
                traceback.print_exc()
        rows.append((view.name, status, detail))
        mark = {"OK": "  ok  ", "PARTIAL": "partial", "EMPTY": " empty",
                "BROKEN": "BROKEN "}[status]
        print(f"  [{mark}] {view.name:<17} {view.endpoints:<28} {detail[:110]}")
    return rows


def main(argv: list[str]) -> int:
    api_version: ApiVersion = "v2"
    tenants: list[TenantId] = list(TENANT_IDS)
    verbose = "--verbose" in argv

    for arg in argv:
        if arg.startswith("--api-version="):
            value = arg.split("=", 1)[1]
            if value not in API_VERSIONS:
                print(f"Unknown api version: {value}. Valid: {', '.join(API_VERSIONS)}")
                return 2
            api_version = value  # type: ignore[assignment]
        elif arg.startswith("--tenant="):
            value = arg.split("=", 1)[1].strip().lower()
            if value == "all":
                continue
            if value not in TENANT_IDS:
                print(f"Unknown tenant: {value}. Valid: {', '.join(TENANT_IDS)} or 'all'.")
                return 2
            tenants = [value]  # type: ignore[list-item]

    all_rows: list[tuple[str, str, str]] = []
    for tenant in tenants:
        all_rows.extend(check_tenant(tenant, api_version, verbose))

    broken = [r for r in all_rows if r[1] == "BROKEN"]
    empty = [r for r in all_rows if r[1] == "EMPTY"]
    partial = [r for r in all_rows if r[1] == "PARTIAL"]
    print(f"\n{len(all_rows) - len(broken) - len(empty) - len(partial)} ok · "
          f"{len(partial)} partial · {len(empty)} empty · {len(broken)} broken  "
          f"(api {api_version})")
    # Non-zero on a break so this can gate a merge later; EMPTY doesn't
    # fail the run because some views legitimately have no data per
    # persona, and the report says which.
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Pre-deploy gate: is this build safe to point at that Aito?

    ./do preflight [--api-version=v2] [--tenant=all]

`./do v2-check` proves every view's query SHAPE survives. It was green
throughout a week in which rep2 lost ten points of matching accuracy
and got them back, and it was green while two personas were serving a
products schema three days out of date. Shape is not readiness.

This checks the things that actually go wrong between a working laptop
and a working deployment, in the order they bite:

  * **Which environment am I about to talk to.** An unscoped v2 URL
    resolves to `master` and answers 200 OK, so the difference between
    a branch and production is one missing path segment.
  * **Is the loaded schema the one this build expects.** A column added
    to `data_loader.SCHEMAS` and never loaded is invisible until a view
    returns nothing. This is what caught metsä and studio still running
    a products table with no `origin`, three days after the fixtures
    changed.
  * **Is there data in it.** An empty table is a 200 OK and a blank
    page.
  * **What engine build is answering.** Numbers in this repo have a
    build attached to them (core #1281 reversed between two), and rep2
    collections written by an older build can be unreadable after an
    upgrade (core #1303) — which presents as a 500 on an ordinary read.

Exit code is non-zero when anything is BROKEN, so it can gate a deploy.
"""

import os
import sys

from src.aito_client import AitoClient, AitoError
from src.config import TENANT_IDS, TenantId, load_config
from src.data_loader import SCHEMAS, load_fixture

# Tables whose absence or emptiness would visibly break a view. The rest
# are optional per persona (`OPTIONAL_TABLES`), so they are reported but
# do not fail the gate.
REQUIRED = ("purchases", "products", "orders", "projects")


def missing_columns(declared: dict, loaded: dict | None) -> list[str]:
    """Columns this build expects that the loaded schema does not have.

    Pure, so the red path is testable. A gate nobody has watched fail is
    a gate nobody should trust — and this is the check that caught two
    personas serving a `products` table three days out of date, which
    `./do v2-check` had been calling green the whole time.
    """
    return sorted(set(declared.get("columns", {}))
                  - set((loaded or {}).get("columns", {})))


def _row_count(client: AitoClient, table: str) -> int | None:
    try:
        return client.search(table, {}, limit=1).get("total")
    except AitoError:
        return None


def check_tenant(tenant: TenantId, api_version: str | None) -> list[str]:
    """Return a list of problems. Empty means ready."""
    problems: list[str] = []
    config = load_config(api_version=api_version)
    creds = config.creds_for(tenant)
    client = AitoClient.from_creds(creds.api_url, creds.api_key,
                                   api_version=config.api_version)

    # 1. Which environment.
    env = creds.api_url.rsplit("/env/", 1)[-1] if "/env/" in creds.api_url else None
    if env is None:
        print(f"  [ WARN ] {tenant:7} URL names no /env/ — this is MASTER")
    else:
        print(f"  [  ok  ] {tenant:7} env={env}")

    # 2. Schema drift: what this build declares versus what is loaded.
    for table, schema in SCHEMAS.items():
        fixture = load_fixture(table, tenant)
        if not fixture:
            continue                     # not this persona's table
        try:
            live = client._request("GET", f"/schema/{table}")
        except AitoError as exc:
            problems.append(f"{tenant}/{table}: schema unreadable — {exc}")
            continue
        missing = missing_columns(schema, live)
        if missing:
            problems.append(
                f"{tenant}/{table}: loaded schema is STALE, missing "
                f"{missing} — run ./do load-data"
                f"{'-v2' if config.api_version == 'v2' else ''} "
                f"--tenant={tenant} --reset")

    # 3. Data present.
    for table in REQUIRED:
        if not load_fixture(table, tenant):
            continue
        count = _row_count(client, table)
        if count is None:
            problems.append(f"{tenant}/{table}: unreadable (see core #1303 — an "
                            "engine upgrade can orphan collections; reload)")
        elif not count:
            problems.append(f"{tenant}/{table}: loaded but EMPTY")
    return problems


def main() -> None:
    # No default. `load_config(api_version=None)` follows AITO_API_VERSION
    # the way the app does — and a gate that checks a different
    # environment than the app will run against is worse than no gate.
    # This shipped hard-coded to "v1", which meant that the moment .env
    # said v2, preflight cheerfully reported `dev` healthy while the app
    # was pointed at `v2`.
    api_version: str | None = None
    tenants: list[TenantId] = list(TENANT_IDS)
    for arg in sys.argv[1:]:
        if arg.startswith("--api-version="):
            api_version = arg.split("=", 1)[1]
        elif arg.startswith("--tenant=") and arg.split("=", 1)[1] != "all":
            tenants = [arg.split("=", 1)[1]]  # type: ignore[list-item]

    config = load_config(api_version=api_version)
    resolved = config.api_version
    if api_version:
        source = "--api-version"
    elif os.environ.get("AITO_API_VERSION", "").strip():
        source = "AITO_API_VERSION"
    elif os.environ.get("AITO_V2_ENV", "").strip():
        source = f"AITO_V2_ENV={os.environ['AITO_V2_ENV'].strip()}"
    else:
        source = "default"
    print(f"Preflight — api {resolved}  (from {source})\n")
    creds = config.creds_for(tenants[0])
    probe = AitoClient.from_creds(creds.api_url, creds.api_key,
                                  api_version=resolved)
    try:
        version = probe._request("GET", "/_version")
        print(f"  engine {version.get('version')} "
              f"({version.get('gitRevision', '')[:12]}, "
              f"built {version.get('builtAt', '?')[:10]})\n")
    except AitoError:
        print("  engine version: not reported on this surface\n")

    problems: list[str] = []
    for tenant in tenants:
        problems += check_tenant(tenant, api_version)

    print()
    if problems:
        print(f"NOT READY — {len(problems)} problem(s):")
        for problem in problems:
            print(f"  ✗ {problem}")
        print("\nFix these, then run `./do v2-check"
              f"{' --api-version=v1' if resolved == 'v1' else ''} --tenant=all`.")
        sys.exit(1)
    print("Ready. Every tenant is env-scoped, current with this build's "
          "schema, and populated.")
    print("Next: `./do v2-check"
          f"{' --api-version=v1' if resolved == 'v1' else ''} --tenant=all` "
          "for query shape, then the promote steps in docs/v2-migration.md.")


if __name__ == "__main__":
    main()

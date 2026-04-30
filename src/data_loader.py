"""Upload sample data to Aito.

Creates table schemas and uploads fixture data. Idempotent.

Usage:
    python -m src.data_loader                          # default tenant
    python -m src.data_loader --tenant=metsa            # one tenant
    python -m src.data_loader --tenant=all              # every tenant
    python -m src.data_loader --reset                   # drop + reload
    python -m src.data_loader --tenant=all --reset      # full bring-up

Per-tenant data: looks under `data/<tenant>/` first; falls back to the
flat `data/` directory if a tenant-specific file isn't present yet.
This lets you migrate fixtures into per-tenant folders one persona at
a time without breaking the others.
"""

import json
import sys
from pathlib import Path

from src.aito_client import AitoClient, AitoError
from src.config import DEFAULT_TENANT, TENANT_IDS, TenantId, load_config

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Aito table schemas — field types match the fixture data.
SCHEMAS = {
    "purchases": {
        "type": "table",
        "columns": {
            "purchase_id": {"type": "String", "nullable": False},
            "supplier": {"type": "String", "nullable": False},
            "description": {"type": "Text", "nullable": False},
            "category": {"type": "String", "nullable": False},
            "amount_eur": {"type": "Decimal", "nullable": False},
            "cost_center": {"type": "String", "nullable": False},
            "account_code": {"type": "String", "nullable": False},
            "approver": {"type": "String", "nullable": False},
            "approval_level": {"type": "String", "nullable": False},
            "delivery_late": {"type": "Boolean", "nullable": False},
            "order_month": {"type": "String", "nullable": False},
            "project": {"type": "String", "nullable": False},
            "routed_by": {"type": "String", "nullable": False},
        },
    },
    "products": {
        "type": "table",
        "columns": {
            "sku": {"type": "String", "nullable": False},
            "name": {"type": "String", "nullable": False},
            "supplier": {"type": "String", "nullable": True},
            "category": {"type": "String", "nullable": True},
            "unit_price": {"type": "Decimal", "nullable": True},
            "hs_code": {"type": "String", "nullable": True},
            "unit_of_measure": {"type": "String", "nullable": True},
            "weight_kg": {"type": "Decimal", "nullable": True},
            "account_code": {"type": "String", "nullable": True},
            "tax_class": {"type": "String", "nullable": True},
        },
    },
    "orders": {
        "type": "table",
        "columns": {
            "order_id": {"type": "String", "nullable": False},
            "product_id": {"type": "String", "nullable": False, "link": "products.sku"},
            "month": {"type": "String", "nullable": False},
            "units_sold": {"type": "Int", "nullable": False},
        },
    },
    "price_history": {
        "type": "table",
        "columns": {
            "price_id": {"type": "String", "nullable": False},
            "product_id": {"type": "String", "nullable": False, "link": "products.sku"},
            "supplier": {"type": "String", "nullable": False},
            "unit_price": {"type": "Decimal", "nullable": False},
            "volume": {"type": "Int", "nullable": False},
            "order_date": {"type": "String", "nullable": False},
        },
    },
    "projects": {
        "type": "table",
        "columns": {
            "project_id": {"type": "String", "nullable": False},
            "name": {"type": "String", "nullable": False},
            "project_type": {"type": "String", "nullable": False},
            "customer": {"type": "String", "nullable": False},
            "manager": {"type": "String", "nullable": False},
            "team_lead": {"type": "String", "nullable": False},
            "team_size": {"type": "Int", "nullable": False},
            # Text so Aito tokenizes individual names — that's what
            # makes "presence of person X predicts success" learnable.
            "team_members": {"type": "Text", "nullable": False},
            "budget_eur": {"type": "Decimal", "nullable": False},
            "duration_days": {"type": "Int", "nullable": False},
            "priority": {"type": "String", "nullable": False},
            "status": {"type": "String", "nullable": False},
            "start_month": {"type": "String", "nullable": False},
            # Outcomes are nullable: only completed projects have them.
            "on_time": {"type": "Boolean", "nullable": True},
            "on_budget": {"type": "Boolean", "nullable": True},
            "success": {"type": "Boolean", "nullable": True},
        },
    },
    "assignments": {
        "type": "table",
        "columns": {
            "assignment_id": {"type": "String", "nullable": False},
            "project_id": {"type": "String", "nullable": False, "link": "projects.project_id"},
            "person": {"type": "String", "nullable": False},
            "role": {"type": "String", "nullable": False},
            "allocation_pct": {"type": "Int", "nullable": False},
            # Denormalised mirror of projects.{project_type, success} so
            # `_predict` and `_relate` on this table can filter by them
            # directly without needing a cross-table join.
            "project_type": {"type": "String", "nullable": False},
            "project_success": {"type": "Boolean", "nullable": True},
        },
    },
    # Browsing/cart impressions — drives `_recommend goal: {clicked: true}`
    # cross-sell ranking. Only Aurora ships fixture data for this; the
    # other personas don't surface a Recommendations view, so loading
    # this table is a no-op for them (run_tenant skips if no fixture).
    "impressions": {
        "type": "table",
        "columns": {
            "impression_id": {"type": "String", "nullable": False},
            "session_id": {"type": "String", "nullable": False},
            "customer_segment": {"type": "String", "nullable": False},
            "product_id": {"type": "String", "nullable": False, "link": "products.sku"},
            # Self-link via products: previous product in the session
            # so `_recommend` can condition on "what they just looked at"
            # the same way help_impressions condition on prev_article_id.
            "prev_product_id": {"type": "String", "nullable": True, "link": "products.sku"},
            "clicked": {"type": "Boolean", "nullable": False},
            "purchased": {"type": "Boolean", "nullable": False},
            "month": {"type": "String", "nullable": False},
        },
    },
}

# Tables whose fixture file may be absent for some personas. The loader
# silently skips these instead of erroring — the Aito table is created
# either way, so queries against it from non-data tenants get a clean
# empty result rather than a 500.
OPTIONAL_TABLES = {"impressions"}


def load_fixture(name: str, tenant: str | None = None) -> list[dict] | None:
    """Load a JSON fixture file.

    Looks for `data/<tenant>/<name>.json` first; falls back to the flat
    `data/<name>.json` so personas with no persona-specific data yet
    still work. Returns None when an OPTIONAL_TABLES fixture is missing
    so the caller can skip the upload instead of crashing.
    """
    if tenant:
        per_tenant = DATA_DIR / tenant / f"{name}.json"
        if per_tenant.exists():
            with open(per_tenant) as f:
                return json.load(f)
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        if name in OPTIONAL_TABLES:
            return None
        raise FileNotFoundError(f"Fixture file not found: {path}.")
    with open(path) as f:
        return json.load(f)


def create_schema(client: AitoClient, table_name: str, schema: dict) -> None:
    """Create or replace a table schema in Aito."""
    print(f"  Creating schema for '{table_name}'...")
    client._request("PUT", f"/schema/{table_name}", json=schema)


def upload_data(client: AitoClient, table_name: str, records: list[dict]) -> None:
    """Upload records to an Aito table in batches."""
    batch_size = 100
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]
        client._request("POST", f"/data/{table_name}/batch", json=batch)
        print(f"  Uploaded {min(i + batch_size, total)}/{total} records to '{table_name}'")


def delete_table(client: AitoClient, table_name: str) -> None:
    """Delete a table and its data from Aito."""
    print(f"  Deleting table '{table_name}'...")
    try:
        client._request("DELETE", f"/schema/{table_name}")
    except AitoError as exc:
        if exc.status_code == 404:
            print(f"  Table '{table_name}' does not exist, skipping.")
        else:
            raise


def run_tenant(tenant: TenantId, reset: bool = False) -> None:
    """Load data into a single tenant's Aito DB."""
    config = load_config()
    creds = config.creds_for(tenant)
    client = AitoClient.from_creds(creds.api_url, creds.api_key)

    if not client.check_connectivity():
        print(f"[{tenant}] Cannot connect to Aito at {creds.api_url}")
        sys.exit(1)

    print(f"\n=== Tenant: {tenant} ===")
    print(f"[{tenant}] Connected to {creds.api_url}")

    if reset:
        print(f"[{tenant}] Resetting — deleting existing tables...")
        delete_table(client, "prediction_cache")
        for table_name in reversed(list(SCHEMAS.keys())):
            delete_table(client, table_name)

    print(f"[{tenant}] Creating schemas...")
    for table_name, schema in SCHEMAS.items():
        create_schema(client, table_name, schema)

    print(f"[{tenant}] Uploading data...")
    total = 0
    for table_name in SCHEMAS:
        records = load_fixture(table_name, tenant=tenant)
        if records is None:
            print(f"  [{tenant}] no fixture for optional table '{table_name}' — schema created, no data uploaded.")
            continue
        upload_data(client, table_name, records)
        total += len(records)

    print(f"[{tenant}] Done. Loaded {total} records.")


def run(reset: bool = False, tenants: list[TenantId] | None = None) -> None:
    """Main entry point for the data loader.

    If `tenants` is None, only the default tenant is loaded — keeps the
    behaviour for `python -m src.data_loader` unchanged.
    """
    targets: list[TenantId] = tenants if tenants else [DEFAULT_TENANT]
    seen_urls: set[str] = set()
    config = load_config()

    for tenant_id in targets:
        creds = config.creds_for(tenant_id)
        # In single-tenant mode every persona points at the same DB.
        # Don't re-upload the same data three times — first writer wins.
        if creds.api_url in seen_urls:
            print(f"\n[{tenant_id}] Aito DB already loaded under another "
                  f"tenant — skipping (single-tenant fallback).")
            continue
        seen_urls.add(creds.api_url)
        run_tenant(tenant_id, reset=reset)


def _parse_tenants_arg(argv: list[str]) -> list[TenantId] | None:
    """Parse `--tenant=<id|all>`. Returns None for default behaviour."""
    for arg in argv:
        if arg.startswith("--tenant="):
            value = arg.split("=", 1)[1].strip().lower()
            if value == "all":
                return list(TENANT_IDS)
            if value in TENANT_IDS:
                return [value]  # type: ignore[list-item]
            print(f"Unknown tenant: {value}. "
                  f"Valid: {', '.join(TENANT_IDS)} or 'all'.")
            sys.exit(1)
    return None


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    tenants = _parse_tenants_arg(sys.argv)
    run(reset=reset, tenants=tenants)

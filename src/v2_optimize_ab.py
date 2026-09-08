"""A/B a v2 environment's prediction quality against `optimize`.

    uv run python -m src.v2_optimize_ab --load   # build the control env
    uv run python -m src.v2_optimize_ab          # measure all three

Aito R&D reported (2026-08-31) that rep2's `optimize` — a compaction
that rewrites how rows sit in segments — can change predictions for
plain-String targets, while every link target stays bit-identical. A
compaction must not be able to move an answer: statistics are a property
of the data, not of its layout. The suspicion is a sibling of the #1245
segment-structure defect.

`./do load-data-v2` calls `optimize` on every collection, so this demo's
v2 numbers are post-compaction, and all three of its predicted fields
(`cost_center`, `account_code`, `approver`) are plain Strings. That
makes the demo a cheap, small-corpus A/B for the report: build a third
environment holding the same rows with no `optimize` call, and evaluate
v1, optimized-v2 and raw-v2 side by side.

Non-destructive by construction: `v2raw` is a fresh copy-on-write branch
of `master`, and every write is scoped to it. The public demo's `master`
is never touched. Findings are recorded in docs/v2-migration.md.
"""

import sys

from src.aito_client import AitoClient
from src.config import load_config
from src.data_loader import (SCHEMAS, create_schema, delete_table,
                             load_fixture, schema_for, upload_data)
from src.overview_service import _case_p

# Metsä only: one tenant is enough to see a layout-dependent statistic,
# and the fixture is the smallest of the three.
DB = "https://shared.aito.ai/db/aito-erp-demo-2"
CONTROL_ENV = "v2raw"
FIELDS = ["cost_center", "account_code", "approver"]
FEATURES = ["supplier", "description", "amount_eur"]


def _measure(client: AitoClient, field: str) -> dict:
    """Held-out accuracy plus the size of the `p < 0.5` band.

    The band matters as much as the accuracy: it is what the Automation
    Overview renders as "needs review", so a case crossing it is visible
    in the demo even when top-1 does not move.
    """
    response = client.evaluate_with_cases(
        table="purchases", predict_field=field,
        feature_fields=FEATURES, limit=200,
    )
    cases = response.get("cases") or []
    return {
        "accuracy": round(float(response.get("accuracy") or 0.0), 4),
        "n": len(cases),
        "below_p50": sum(1 for case in cases if _case_p(case) < 0.5),
    }


def build_control(client: AitoClient, key: str) -> None:
    """Branch `v2raw` off master and load purchases — without optimize."""
    boot = AitoClient.from_creds(DB, key, api_version="v2")
    boot._request("POST", "/_envs",
                  json={"name": CONTROL_ENV, "basedOn": "master"})
    print(f"created env {CONTROL_ENV} (copy-on-write from master)")

    # The branch inherits master's rep1 tables; they have to go before
    # the same names can be declared as collections.
    for table_name in reversed(list(SCHEMAS.keys())):
        delete_table(client, table_name)
    create_schema(client, "purchases", schema_for("purchases", "v2"))
    rows = load_fixture("purchases", tenant="metsa")
    upload_data(client, "purchases", rows)
    print(f"uploaded {len(rows)} purchases — no optimize call")


def main() -> None:
    key = load_config(api_version="v2").creds_for("metsa").api_key
    control = AitoClient.from_creds(f"{DB}/env/{CONTROL_ENV}", key,
                                    api_version="v2")
    if "--load" in sys.argv:
        build_control(control, key)

    environments = {
        "v1 (rep1)": AitoClient.from_creds(f"{DB}/env/dev", key,
                                           api_version="v1"),
        "v2 optimized": AitoClient.from_creds(f"{DB}/env/v2", key,
                                              api_version="v2"),
        "v2 raw": control,
    }
    print(f"\n{'env':16} {'field':14} {'accuracy':>9} {'n':>5} {'p<0.5':>6}")
    for label, client in environments.items():
        for field in FIELDS:
            result = _measure(client, field)
            print(f"{label:16} {field:14} {result['accuracy']:>9} "
                  f"{result['n']:>5} {result['below_p50']:>6}")


if __name__ == "__main__":
    main()

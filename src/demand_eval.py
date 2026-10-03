"""`./do demand-eval` — does the demand forecast beat the obvious rules?

Scores `_estimate units_sold` over `monthly_demand` against the six
months in `monthly_demand_holdout`, which `_estimate` has never seen,
next to the two forecasts a buyer already has without Aito:

  same month last year   — the seasonal naive rule
  trailing 3-month mean  — what a plain ERP min/max reorder rule uses

The Demand and Inventory views quote these numbers, so they are
measured here first. A view may only claim an advantage this prints.

Metric: WAPE, sum|forecast - actual| / sum(actual). One number that
weights a 200-unit miss on a fast mover above a 2-unit miss on a slow
one, which is how a buyer experiences error.
"""

from __future__ import annotations

import random
import sys
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from src.shared_window import refuse_in_batch_window
from src.aito_client import AitoClient
from src.config import TENANT_IDS
from src.demand_service import FEATURES   # the view's `where`; one definition

SAMPLE_PER_TENANT = 300


def _all_rows(client: AitoClient, table: str) -> list[dict]:
    """The whole table in one read. Asserted, not assumed: a short page
    would quietly score a subset and report it as the whole."""
    res = client.search(table, {}, limit=50_000)
    hits = res.get("hits") or []
    if res.get("total") != len(hits):
        raise RuntimeError(f"{table}: read {len(hits)} of {res.get('total')} rows")
    return hits


def _prior_year(month: str) -> str:
    return f"{int(month[:4]) - 1}{month[4:]}"


def evaluate(client: AitoClient, tenant: str) -> dict:
    history = _all_rows(client, "monthly_demand")
    holdout = _all_rows(client, "monthly_demand_holdout")
    by_key = {(r["sku"], r["month"]): r["units_sold"] for r in history}
    series: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in history:
        series[r["sku"]].append((r["month"], r["units_sold"]))
    trailing = {sku: sum(u for _, u in sorted(rows)[-3:]) / 3 for sku, rows in series.items()}

    rng = random.Random(zlib.crc32(tenant.encode()))
    sample = sorted(holdout, key=lambda r: r["demand_id"])
    if len(sample) > SAMPLE_PER_TENANT:
        sample = rng.sample(sample, SAMPLE_PER_TENANT)

    def aito(row: dict) -> float:
        res = client.estimate("monthly_demand", {k: row[k] for k in FEATURES}, "units_sold")
        value = res.get("estimate")
        if not isinstance(value, (int, float)):
            raise ValueError(f"_estimate returned no number for {row}: {res}")
        return float(value)

    with ThreadPoolExecutor(max_workers=8) as pool:
        estimates = list(pool.map(aito, sample))

    actual = [r["units_sold"] for r in sample]
    # The seasonal naive rule needs last year's row. Holdout months are
    # Oct-Mar, so the prior year is always inside the history; a miss is
    # a data error, not a gap to paper over.
    last_year = [by_key[(r["sku"], _prior_year(r["month"]))] for r in sample]
    trail = [trailing[r["sku"]] for r in sample]

    def wape(pred: list[float]) -> float:
        return sum(abs(p - a) for p, a in zip(pred, actual)) / sum(actual)

    return {
        "tenant": tenant,
        "n": len(sample),
        "wape_aito": round(wape(estimates), 3),
        "wape_last_year": round(wape(last_year), 3),
        "wape_trailing": round(wape(trail), 3),
    }


def main() -> None:
    refuse_in_batch_window("demand-eval")   # before any query: src/shared_window.py
    import src.app as app   # builds one client per tenant from the environment
    clients = app._build_clients()
    tenants = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--tenant=")]
    for tenant in (tenants or list(TENANT_IDS)):
        r = evaluate(clients[tenant], tenant)
        print(f"{r['tenant']:7} n={r['n']:4}  WAPE  aito {r['wape_aito']:.3f}   "
              f"same-month-last-year {r['wape_last_year']:.3f}   "
              f"trailing-3-month {r['wape_trailing']:.3f}")


if __name__ == "__main__":
    main()

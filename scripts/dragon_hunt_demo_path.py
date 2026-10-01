#!/usr/bin/env python3
"""Dragon hunt on the ERP demo's own query path: plausible wrong answers, not crashes.

Pre-registered in docs/notes/dragon-hunt-demo-path-preregistration.md
(C1, P1-P8, R1-R3, M1-M2, L1-L2, E1-E2). Read-only. Saves every answer
and every body sent, so a run on a later engine can be diffed against it.
Never run it between 08:00 and 10:00 Helsinki (shared batch window).

    uv run python scripts/dragon_hunt_demo_path.py --out baseline.json
    uv run python scripts/dragon_hunt_demo_path.py --out after.json --compare baseline.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import query_log  # noqa: E402
from src.demand_service import FEATURES as DEMAND_FEATURES  # noqa: E402
from src.matching_service import (BASED_ON, CATALOGUE_FIELDS, INFERENCE_PRESET,  # noqa: E402
                                   LINE_FEATURES, VENDOR_FEATURES, rank_line)
from src.planner_service import PERSON_FIELDS  # noqa: E402
from src.recommendation_service import RELATE_LIMIT  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
TENANTS = ("metsa", "aurora", "studio")
PO_FIELDS = ("cost_center", "account_code", "approver")
checks: list[dict] = []
answers: dict[str, object] = {}
unscored: list[str] = []
bad_tables: dict[str, set[str]] = {t: set() for t in TENANTS}


def check(pid: str, cell: str, ok: bool, detail: str) -> None:
    checks.append({"property": pid, "cell": cell, "pass": bool(ok), "detail": detail})


def fixture(tenant: str, table: str) -> list[dict]:
    return json.loads((DATA / tenant / f"{table}.json").read_text())


def hits_of(r: dict) -> list[tuple[str, float]]:
    return [(str(h["$value"]), float(h["$p"])) for h in r["hits"]]


def why_product(node) -> float:
    """Multiply a $why tree back together; a lift's `prior` explains it, it is not a factor."""
    if node.get("type") == "product":
        return math.prod(why_product(f) for f in node["factors"])
    return float(node["value"])


def find_base(node):
    if isinstance(node, dict):
        if node.get("type") == "baseP":
            return node
        for k, v in node.items():
            if k != "prior" and (hit := find_base(v)):
                return hit
    elif isinstance(node, list):
        for x in node:
            if hit := find_base(x):
                return hit
    return None


def recorded(fn):
    """Run one call and keep the body it sent next to its answer."""
    with query_log.recording() as sent:
        result = fn()
    return result, [q["body"] for q in sent]


# ── C1: the oracle ───────────────────────────────────────────────────


def count_cells(c, tenant: str, tables: list[str]) -> None:
    for table in tables:
        rows = fixture(tenant, table)
        total = c.search(table, {}, limit=1)["total"]
        ok = total == len(rows)
        check("C1", f"{tenant} {table}", ok, f"shared {total} vs fixtures {len(rows)}")
        if not ok:
            bad_tables[tenant].add(table)


# ── P1-P8: PO Queue and Approval predictions ─────────────────────────


def predict_properties(c, tenant, name, where, field, purchases, exclusive_ok):
    full, body = recorded(lambda: c.predict("purchases", where, field, limit=50))
    h = hits_of(full)
    answers[name] = {"hits": h[:10], "body": body}
    check("P1", name, all(0 <= p <= 1 for _, p in h) and h == sorted(h, key=lambda x: -x[1]),
          "bounds and order")
    if exclusive_ok:
        total = sum(p for _, p in h)
        check("P2", name, abs(total - 1) <= 0.01, f"sum of $p = {total:.4f}")
    top3 = hits_of(c.predict("purchases", where, field, limit=3))
    check("P3", name, [v for v, _ in top3] == [v for v, _ in h[:3]]
          and all(abs(a[1] - b[1]) < 1e-9 for a, b in zip(top3, h[:3])),
          f"limit 3 {top3} vs limit 50 {h[:3]}")
    check("P4", name, hits_of(c.predict("purchases", where, field, limit=50)) == h, "repeat")
    reordered = dict(reversed(list(where.items())))
    check("P5", name, hits_of(c.predict("purchases", reordered, field, limit=50)) == h,
          "reversed where keys")
    column = {str(r.get(field)) for r in purchases}
    check("P6", name, h[0][0] in column, f"top value {h[0][0]!r} in the tenant's {field} column")
    return full


def po_cells(c, tenant: str) -> None:
    purchases = fixture(tenant, "purchases")
    rows = sorted(purchases, key=lambda r: r["purchase_id"])
    distinct = {f: len({r.get(f) for r in purchases}) for f in (*PO_FIELDS, "approval_level")}
    for row in (rows[0], rows[len(rows) // 2]):
        where = {"supplier": row["supplier"]}
        if row.get("description"):
            where["description"] = row["description"]
        for field in PO_FIELDS:                      # po_service.predict_single
            name = f"{tenant} {row['purchase_id']} {field}"
            full = predict_properties(c, tenant, name, where, field, purchases, distinct[field] <= 50)
            if distinct[field] > 50:
                unscored.append(f"P2 {name}: {distinct[field]} distinct values > 50")
            top = full["hits"][0]
            product = why_product(top["$why"])
            check("P7", name, abs(math.log10(product / top["$p"])) < 0.1,
                  f"chain {product:.4g} vs $p {top['$p']:.4g} (known history: td-20260909133103405502)")
            base = find_base(top["$why"])
            share = sum(str(r.get(field)) == str(top["$value"]) for r in purchases) / len(purchases)
            check("P8", name, base is not None and abs(base["value"] - share) <= 0.001,
                  f"baseP {base and base['value']} vs tenant share {share:.4f}")
        # approval_service.predict_approval: where supplier + category
        where = {"supplier": row["supplier"], "category": row["category"]}
        name = f"{tenant} {row['purchase_id']} approval_level"
        predict_properties(c, tenant, name, where, "approval_level", purchases,
                           distinct["approval_level"] <= 50)


# ── R1-R3: _relate counts are exact ──────────────────────────────────


def relate_counts(pid, name, hits, n, condition, related_of, rows) -> None:
    """Every fs count against the fixtures. `condition(row)` is the where;
    `related_of(hit)` gives a predicate for the related value."""
    on_condition = [r for r in rows if condition(r)]
    for hit in hits:
        matches = related_of(hit)
        f = sum(matches(r) for r in rows)
        f_on = sum(matches(r) for r in on_condition)
        fs = hit["fs"]
        got = (fs["n"], fs["fCondition"], fs["f"], fs["fOnCondition"])
        want = (n, len(on_condition), f, f_on)
        label = f"{name}: {hit['related']}"
        check(pid, label, got == want, f"fs (n, fCondition, f, fOnCondition) {got} vs fixtures {want}")
        exact_lift = (f_on / len(on_condition)) / (f / n) if f and on_condition else None
        answers.setdefault("relate lifts (reported, not scored)", []).append(
            f"{label}: lift {hit['lift']:.3f} vs exact {exact_lift if exact_lift is None else round(exact_lift, 3)}")


def relate_limit_check(c, name, table, where, field, limit, full_hits) -> None:
    """`limit=None` is the demo's own call, which sends no limit."""
    top3 = c.relate(table, where, field, limit=3)["hits"]
    pairs = lambda hs: [(json.dumps(h["related"], sort_keys=True), h["lift"]) for h in hs]  # noqa: E731
    a, b = pairs(top3), pairs(full_hits[:3])
    check("P3", name, [x for x, _ in a] == [x for x, _ in b]
          and all(abs(x - y) < 1e-9 for (_, x), (_, y) in zip(a, b)),
          f"limit 3 vs limit {limit}")


def relate_cells(c, tenant: str) -> None:
    purchases = fixture(tenant, "purchases")
    n = len(purchases)
    if "purchases" not in bad_tables[tenant]:
        # supplier_service.get_delivery_risks
        r, body = recorded(lambda: c.relate("purchases", {"delivery_late": True}, "supplier"))
        name = f"{tenant} R1 relate supplier | delivery_late"
        answers[name] = {"hits": [(h["related"], h["lift"]) for h in r["hits"]], "body": body}
        relate_limit_check(c, name, "purchases", {"delivery_late": True}, "supplier", None, r["hits"])
        relate_counts("R1", name, r["hits"], n, lambda row: row.get("delivery_late") is True,
                      lambda h: (lambda row, s=h["related"]["supplier"]: row.get("supplier") == s), purchases)
        check("P4", name, c.relate("purchases", {"delivery_late": True}, "supplier")["hits"] == r["hits"],
              "repeat")
        # rulemining_service.mine_rules, for the two biggest suppliers
        for supplier, _ in Counter(row["supplier"] for row in purchases).most_common(2):
            r, body = recorded(lambda: c.relate("purchases", {"supplier": supplier}, "account_code"))
            name = f"{tenant} R2 relate account_code | supplier={supplier}"
            answers[name] = {"hits": [(h["related"], h["lift"]) for h in r["hits"]], "body": body}
            relate_limit_check(c, name, "purchases", {"supplier": supplier}, "account_code", None, r["hits"])
            relate_counts("R2", name, r["hits"], n, lambda row, s=supplier: row.get("supplier") == s,
                          lambda h: (lambda row, a=h["related"]["account_code"]:
                                     str(row.get("account_code")) == str(a)), purchases)
    if tenant == "aurora" and "baskets" not in bad_tables[tenant]:
        baskets = fixture(tenant, "baskets")
        sets = [set(b["products"]) for b in baskets]
        for anchor, _ in Counter(s for b in sets for s in b).most_common(3):
            where = {"products": {"$has": anchor}}
            r, body = recorded(lambda: c.relate("baskets", where, "products", limit=RELATE_LIMIT))
            name = f"aurora R3 relate products | products has {anchor}"
            answers[name] = {"hits": [(h["related"], h["lift"]) for h in r["hits"][:10]], "body": body}
            relate_counts("R3", name, r["hits"], len(baskets), lambda b, a=anchor: a in b["set"],
                          lambda h: (lambda b, s=h["related"]["products"]: s in b["set"]),
                          [{"set": s} for s in sets])
            relate_limit_check(c, name, "baskets", where, "products", RELATE_LIMIT, r["hits"])


# ── M1-M2: matching returns real catalogue rows ──────────────────────


def matching_cells(c) -> None:
    products = {p["sku"]: p for p in fixture("aurora", "products")}
    vendors = {v["vendor"]: v for v in fixture("aurora", "vendors")}
    lines = sorted(fixture("aurora", "invoice_lines_holdout"), key=lambda r: r["line_id"])
    for line in (lines[0], lines[500], lines[1000]):
        name = f"aurora matching {line['line_id']}"
        vendor = vendors.get(line["billing_supplier"])
        ranked, _ = rank_line(c, line, vendor=vendor)
        # rank_line swallows AitoError into []; an empty answer is reported, not passed.
        check("M0", name, bool(ranked), f"{len(ranked)} candidates (rank_line returns [] on any AitoError)")
        # The same _predict rank_line sends, read raw: its Candidate objects
        # coerce a missing name to "", which would hide exactly what M1 checks.
        where = {f: line[f] for f in LINE_FEATURES if line.get(f) is not None}
        for field in VENDOR_FEATURES:
            if vendor and vendor.get(field) is not None:
                where[f"billing_supplier.{field}"] = vendor[field]
        r, body = recorded(lambda: c.predict("invoice_lines", where, "sku", limit=5,
                                             select_extra=CATALOGUE_FIELDS, ai=INFERENCE_PRESET,
                                             based_on=BASED_ON if c.api_version == "v2" else None))
        hits = r["hits"]
        answers[name] = {"hits": [(h["$value"], h["$p"]) for h in hits], "body": body}
        check("P1", name, all(0 <= h["$p"] <= 1 for h in hits)
              and [h["$p"] for h in hits] == sorted((h["$p"] for h in hits), reverse=True), "bounds and order")
        check("M2", name, all(h["$value"] in products for h in hits), "every sku is in products")
        mismatched = [(h["$value"], f, h.get(f), products[h["$value"]].get(f))
                      for h in hits if h["$value"] in products for f in CATALOGUE_FIELDS
                      if h.get(f) != products[h["$value"]].get(f)]
        check("M1", name, not mismatched, f"linked columns vs products: {mismatched[:3]}")
        again, _ = rank_line(c, line, vendor=vendor)
        check("P4", name, [(k.sku, k.p) for k in again] == [(k.sku, k.p) for k in ranked], "repeat")


# ── L1-L2: planner filters hold ──────────────────────────────────────


def planner_cells(c, tenant: str) -> None:
    people = {p["person"]: p for p in fixture(tenant, "people")}
    assignments = fixture(tenant, "assignments")
    (ptype, role), _ = Counter((a["project_type"], a["role"]) for a in assignments).most_common(1)[0]
    site, _ = Counter(p["site"] for p in people.values()).most_common(1)[0]
    for clause, value, attr in (("person.seniority", "senior", "seniority"), ("person.site", site, "site")):
        where = {"project_type": ptype, "role": role, clause: value}   # planner_service's person where
        name = f"{tenant} planner {ptype}/{role} {clause}={value}"
        r, body = recorded(lambda: c.predict("assignments", where, "person", limit=6,
                                             select_extra=PERSON_FIELDS))
        hits = r["hits"]
        answers[name] = {"hits": [(h["$value"], h["$p"]) for h in hits], "body": body}
        check("P1", name, all(0 <= h["$p"] <= 1 for h in hits)
              and [h["$p"] for h in hits] == sorted((h["$p"] for h in hits), reverse=True), "bounds and order")
        unknown = [h["$value"] for h in hits if h["$value"] not in people]
        check("L1", name, not unknown and all(people[h["$value"]][attr] == value for h in hits),
              f"{[(h['$value'], people.get(h['$value'], {}).get(attr)) for h in hits]}; unknown {unknown}")
        diffs = [(h["$value"], f, h.get(f), people[h["$value"]].get(f)) for h in hits
                 if h["$value"] in people for f in PERSON_FIELDS if h.get(f) != people[h["$value"]].get(f)]
        check("L2", name, not diffs, f"profile columns vs people: {diffs[:3]}")
        check("P4", name, c.predict("assignments", where, "person", limit=6,
                                    select_extra=PERSON_FIELDS)["hits"] == hits, "repeat")


# ── E1-E2: demand estimates ──────────────────────────────────────────


def components_of(why: dict) -> list[dict]:
    return why.get("components") or []


def demand_cells(c, tenant: str) -> None:
    history = fixture(tenant, "monthly_demand")
    lo, hi = min(r["units_sold"] for r in history), max(r["units_sold"] for r in history)
    rows = sorted(fixture(tenant, "monthly_demand_holdout"), key=lambda r: r["demand_id"])
    for row in (rows[0], rows[len(rows) // 2]):
        where = {f: row[f] for f in DEMAND_FEATURES}                   # demand_service's where
        name = f"{tenant} demand {row['demand_id']}"
        r, body = recorded(lambda: c.estimate("monthly_demand", where, "units_sold"))
        est = float(r["estimate"])
        answers[name] = {"estimate": est, "why": r.get("why"), "body": body}
        check("E1", name, lo <= est <= hi, f"estimate {est:.3f} vs observed [{lo}, {hi}]")
        comps = components_of(r.get("why") or {})
        # Field names confirmed on the first response before scoring (pre-registration).
        if comps and all("weight" in x and "value" in x for x in comps):
            mean = sum(x["weight"] * x["value"] for x in comps) / sum(x["weight"] for x in comps)
            check("E2", name, abs(mean - est) <= 1e-6 * max(1.0, abs(est)),
                  f"weighted mean {mean:.6f} vs estimate {est:.6f} over {len(comps)} components")
        else:
            unscored.append(f"E2 {name}: component keys {sorted(comps[0]) if comps else 'none'}")
        check("P4", name, float(c.estimate("monthly_demand", where, "units_sold")["estimate"]) == est, "repeat")
        reordered = dict(reversed(list(where.items())))
        check("P5", name, float(c.estimate("monthly_demand", reordered, "units_sold")["estimate"]) == est,
              "reversed where keys")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--compare", help="an earlier run's JSON to diff answers against")
    args = parser.parse_args()
    now = datetime.now(ZoneInfo("Europe/Helsinki"))
    if 8 <= now.hour < 10:
        raise SystemExit("08:00-10:00 Helsinki is the shared batch window; run after 10:00.")
    import src.app as app
    clients = app._build_clients()
    engine = {t: clients[t]._v2.request("GET", "/_version") for t in TENANTS}
    tables = {"metsa": ["purchases", "assignments", "people", "monthly_demand"],
              "aurora": ["purchases", "baskets", "products", "vendors", "invoice_lines_holdout",
                         "monthly_demand"],
              "studio": ["purchases", "assignments", "people"]}
    for t in TENANTS:
        count_cells(clients[t], t, tables[t])
    for t in TENANTS:
        if "purchases" not in bad_tables[t]:
            po_cells(clients[t], t)
        relate_cells(clients[t], t)
    if not bad_tables["aurora"] & {"products", "vendors", "invoice_lines_holdout"}:
        matching_cells(clients["aurora"])
    for t in ("metsa", "studio"):
        if not bad_tables[t] & {"assignments", "people"}:
            planner_cells(clients[t], t)
    for t in ("metsa", "aurora"):
        if "monthly_demand" not in bad_tables[t]:
            demand_cells(clients[t], t)
    Path(args.out).write_text(json.dumps({"engine": engine, "ran_at": now.isoformat(), "answers": answers,
                                          "checks": checks, "unscored": unscored}, indent=1, default=str))
    failed = [x for x in checks if not x["pass"]]
    versions = {t: e.get("version") for t, e in engine.items()}
    print(f"engine {versions}: {len(checks) - len(failed)}/{len(checks)} checks pass, "
          f"{len(unscored)} recorded unscored")
    for x in failed:
        print(f"  FAIL {x['property']} {x['cell']}: {x['detail']}")
    for u in unscored:
        print(f"  UNSCORED {u}")
    if args.compare:
        before = json.load(open(args.compare))["answers"]
        changed = [k for k in answers if json.dumps(answers[k], default=str) != json.dumps(before.get(k), default=str)]
        print(f"answers changed since {args.compare}: {len(changed)}")
        for k in changed:
            print(f"  CHANGED {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Project Plan view — generative planning + subcontractor matchmaking.

Two flows on one page, both backed by the `tasks` table:

  1. **Generate a plan** for a brand-new project. Caller provides the
     project context (project_type, customer, budget, region). We:
     - Discover the typical phase set for that project_type by
       grouping completed tasks via `_search`.
     - For each phase, find the typical task names (top-N by frequency
       within the phase × project_type slice).
     - For each task, run three parallel `_predict`s on the `tasks`
       table — assignee (subcontractor or person), planned_days,
       planned_cost_eur — conditioned on the project context.
     The result is a ready-to-edit project plan drawn from history,
     not a hand-coded template.

  2. **Re-rank candidates** for an existing task. Run `_recommend
     from=tasks where={phase, region, season, project_type}
     recommend=subcontractor goal={success: true}` to surface the
     historical-best subcontractor for the exact task context, plus
     `_predict success` for the currently-assigned vendor so the demo
     can show a side-by-side delta ("if you swap Lemminkäinen for
     Caverion on MEP, P(success) jumps from 0.55 to 0.93").

The Aito query patterns are ported straight from `smartentry_service`
(multi-field _predict per row) and `recommendations_service`
(_recommend with success=true goal). No new operators — just the
right context per call.
"""

from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from src.aito_client import AitoClient

log = logging.getLogger(__name__)

# Limit how many tasks we propose per phase. The fixture's most-
# frequent task names per phase are 3-4; capping at 4 keeps the
# generated plan readable without dropping signal.
MAX_TASKS_PER_PHASE = 4


# Phase → typical purchase categories. The Lemonsoft+Jakamo punchline
# of this demo: a generated phase doesn't just propose tasks and
# subcontractors — it ALSO proposes the typical materials/POs that
# phase needs, with the right supplier from the buyer's history.
# Categories are the values that already live in the `purchases.category`
# column for Metsä (production, electrical, fuel, ppe, …).
#
# Each list is a *prior* — for a given (project_type, phase) we then
# ask Aito which suppliers are most likely per category. A phase
# whose list is empty (planning, design, audit, …) skips the
# supplier-suggestion step entirely; the demo doesn't pretend every
# phase generates POs.
PHASE_PURCHASE_CATEGORIES: dict[str, list[str]] = {
    # construction phases
    "site-prep":     ["fuel", "ppe", "construction"],
    "earthworks":    ["fuel", "construction"],
    "foundations":   ["construction", "fuel"],
    "structural":    ["construction", "production", "capex"],
    "mep":           ["electrical", "production"],
    "finishing":     ["maintenance", "cleaning", "production"],
    "commissioning": ["maintenance", "electrical"],
    "handover":      ["cleaning"],
    # maintenance phases
    "inspection":    ["maintenance"],
    "repair":        ["production", "maintenance", "electrical"],
    # rollout phases
    "installation":  ["production", "electrical"],
    # purely administrative phases — empty list means "no auto-PO"
    "planning":      [],
    "procurement":   [],
    "design":        [],
    "discovery":     [],
    "prototype":     ["production", "electrical"],
    "validation":    [],
    "documentation": [],
    "fieldwork":     [],
    "reporting":     [],
    "testing":       [],
}


# Hand-curated execution order for phases. The `tasks` table doesn't
# carry an explicit phase ordering, so we sort the discovered phases
# against this canonical list. Phases not in the list keep their
# discovered order at the bottom — useful for accepting unknown
# project_types without crashing.
PHASE_ORDER: list[str] = [
    # construction-style
    "site-prep", "earthworks", "foundations", "structural",
    "mep", "finishing", "commissioning", "handover",
    # maintenance-style
    "planning", "inspection", "procurement", "repair",
    # rollout-style
    "design", "installation", "testing",
    # rd-style
    "discovery", "prototype", "validation", "documentation",
    # audit-style
    "fieldwork", "reporting",
]


@dataclass
class TaskCandidate:
    """One row in a generated plan or in the rerank list."""
    phase: str
    task_name: str
    assignee_kind: str          # "subcontractor" | "employee"
    assignee: str               # the predicted vendor or person
    assignee_confidence: float  # P from _predict
    planned_days: int
    planned_cost_eur: float
    success_p: float            # P(success) for the predicted assignment

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "task_name": self.task_name,
            "assignee_kind": self.assignee_kind,
            "assignee": self.assignee,
            "assignee_confidence": self.assignee_confidence,
            "planned_days": self.planned_days,
            "planned_cost_eur": self.planned_cost_eur,
            "success_p": self.success_p,
        }


@dataclass
class PurchaseSuggestion:
    """One auto-drafted PO line per (phase, category). The recommended
    supplier comes from `_predict from=purchases predict=supplier`
    conditioned on (project_type, category); the typical amount is
    the historical mean for that supplier+category slice.

    This is the Jakamo half of the Lemonsoft+Jakamo pitch: when Aito
    drafts a project plan, it doesn't just propose tasks and
    subcontractors — it pre-fills the materials POs that phase
    needs, routed to the supplier history says is right."""
    phase: str
    category: str
    supplier: str
    supplier_confidence: float
    typical_amount_eur: float | None
    coverage: int

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "category": self.category,
            "supplier": self.supplier,
            "supplier_confidence": self.supplier_confidence,
            "typical_amount_eur": self.typical_amount_eur,
            "coverage": self.coverage,
        }


@dataclass
class GeneratedPlan:
    project_type: str
    region: str
    season: str
    estimated_budget_eur: float | None
    phases: list[str]
    tasks: list[TaskCandidate] = field(default_factory=list)
    purchases: list[PurchaseSuggestion] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "project_type": self.project_type,
            "region": self.region,
            "season": self.season,
            "estimated_budget_eur": self.estimated_budget_eur,
            "phases": self.phases,
            "tasks": [t.to_dict() for t in self.tasks],
            "purchases": [p.to_dict() for p in self.purchases],
            # Convenience aggregates for the UI's headline stats.
            "total_planned_days": sum(t.planned_days for t in self.tasks),
            "total_planned_cost_eur": sum(t.planned_cost_eur for t in self.tasks),
            "total_purchases_eur": sum(
                p.typical_amount_eur or 0.0 for p in self.purchases
            ),
            "avg_success_p": (
                sum(t.success_p for t in self.tasks) / len(self.tasks)
                if self.tasks else 0.0
            ),
        }


@dataclass
class AlternativeAssignee:
    """One candidate assignee in a rerank list."""
    name: str                   # subcontractor name (or person, if employee task)
    success_p: float            # P(success) given the task's context
    coverage: int               # historical sample size — how many similar tasks they did
    avg_days: float | None      # mean planned_days when they did similar tasks
    avg_cost_eur: float | None  # mean planned_cost_eur

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "success_p": self.success_p,
            "coverage": self.coverage,
            "avg_days": self.avg_days,
            "avg_cost_eur": self.avg_cost_eur,
        }


# ── _search helpers ─────────────────────────────────────────────────


def _completed_tasks_for_type(client: AitoClient, project_type: str, limit: int = 1500) -> list[dict]:
    """Fetch completed task history for a project_type. Used to discover
    phases + typical task names by frequency (Aito's own
    `_predict task_name` works too, but a cheap grouping over `_search`
    keeps the generative path fast and easy to explain in the panel)."""
    try:
        response = client.search(
            "tasks",
            {"project_type": project_type, "status": "complete"},
            limit=limit,
        )
    except Exception as exc:
        log.warning("tasks _search failed for %s: %s", project_type, exc)
        return []
    return response.get("hits") or []


def _ordered_phases(phases: list[str]) -> list[str]:
    """Sort discovered phases against PHASE_ORDER so a generated plan
    flows in the order a project manager expects."""
    seen = list(dict.fromkeys(phases))  # preserve discovery order, dedupe
    keyed = sorted(
        seen,
        key=lambda p: PHASE_ORDER.index(p) if p in PHASE_ORDER else len(PHASE_ORDER),
    )
    return keyed


def _typical_tasks_per_phase(history: list[dict], limit: int) -> dict[str, list[str]]:
    """Group completed tasks by phase, return the top-N task_name values
    per phase by frequency. The names are what we then feed into
    `_predict assignee` for the generated plan."""
    by_phase: dict[str, Counter] = {}
    for row in history:
        by_phase.setdefault(row["phase"], Counter())[row["task_name"]] += 1
    return {
        phase: [name for name, _ in counter.most_common(limit)]
        for phase, counter in by_phase.items()
    }


# ── _predict helpers ────────────────────────────────────────────────


def _predict_value(
    client: AitoClient, where: dict, predict_field: str,
) -> tuple[Any, float]:
    """Run a single _predict call and return the top hit's (feature, $p)."""
    try:
        response = client.predict("tasks", where, predict_field, limit=1)
    except Exception as exc:
        log.warning("predict %s failed: %s", predict_field, exc)
        return None, 0.0
    hits = response.get("hits") or []
    if not hits:
        return None, 0.0
    return hits[0].get("feature"), float(hits[0].get("$p", 0.0))


def _success_p(client: AitoClient, where: dict) -> float:
    """P(success=true) for a task with the given context."""
    try:
        response = client.predict("tasks", where, "success", limit=2)
    except Exception:
        return 0.0
    for hit in response.get("hits") or []:
        if hit.get("feature") in (True, "true", "True"):
            return float(hit.get("$p", 0.0))
    return 0.0


def _predict_task_assignment(
    client: AitoClient,
    project_type: str,
    phase: str,
    task_name: str,
    region: str,
    season: str,
) -> TaskCandidate:
    """Three parallel _predicts give Aito's best guess for one task row."""
    where = {
        "project_type": project_type,
        "phase": phase,
        "task_name": task_name,
        "region": region,
        "season": season,
    }

    with ThreadPoolExecutor(max_workers=4) as pool:
        kind_future       = pool.submit(_predict_value, client, where, "assignee_kind")
        days_future       = pool.submit(_predict_value, client, where, "planned_days")
        cost_future       = pool.submit(_predict_value, client, where, "planned_cost_eur")

        assignee_kind, _kind_p = kind_future.result()
        days_value, _days_p    = days_future.result()
        cost_value, _cost_p    = cost_future.result()

    assignee_kind = str(assignee_kind or "subcontractor")
    predict_field = "subcontractor" if assignee_kind == "subcontractor" else "assignee_person"
    assignee, assignee_p = _predict_value(
        client, {**where, "assignee_kind": assignee_kind}, predict_field,
    )

    success_where = {**where, "assignee_kind": assignee_kind, predict_field: assignee}
    success_p = _success_p(client, success_where)

    return TaskCandidate(
        phase=phase,
        task_name=task_name,
        assignee_kind=assignee_kind,
        assignee=str(assignee or "—"),
        assignee_confidence=assignee_p,
        planned_days=int(days_value or 0) if isinstance(days_value, (int, float)) else 0,
        planned_cost_eur=float(cost_value or 0) if isinstance(cost_value, (int, float)) else 0.0,
        success_p=success_p,
    )


# ── purchase / supplier suggestions per phase ──────────────────────


def _predict_purchase_supplier(
    client: AitoClient, project_type: str, category: str,
) -> tuple[str | None, float, float | None, int]:
    """For (category), return Aito's top supplier guess plus the
    typical amount + sample size from `purchases`. Powers the
    auto-drafted PO lines on the project plan.

    NOTE: `purchases` doesn't carry `project_type` — it's a tenant-
    wide spend table, not project-scoped. So the where-clause is
    just the category. The pattern still demonstrates the core
    Jakamo punchline ("auto-route material POs to the historically
    right supplier") without needing a schema change.
    """
    where = {"category": category}
    try:
        response = client.predict(
            "purchases", where, "supplier", limit=1,
        )
    except Exception as exc:
        log.warning("predict supplier (%s) failed: %s", category, exc)
        return None, 0.0, None, 0
    hits = response.get("hits") or []
    if not hits:
        return None, 0.0, None, 0
    supplier = hits[0].get("feature")
    p = float(hits[0].get("$p", 0.0))
    if not supplier:
        return None, p, None, 0

    # Fetch a sample of historical purchases for this supplier+category
    # to estimate the typical PO amount.
    try:
        sample = client.search(
            "purchases",
            {"category": category, "supplier": supplier},
            limit=120,
        )
    except Exception:
        return str(supplier), p, None, 0
    rows = sample.get("hits") or []
    coverage = sample.get("total", len(rows))
    if not rows:
        return str(supplier), p, None, coverage
    avg = sum(float(r["amount_eur"]) for r in rows) / len(rows)
    return str(supplier), p, avg, coverage


def predict_purchases_for_phase(
    client: AitoClient, project_type: str, phase: str,
) -> list[PurchaseSuggestion]:
    """Auto-draft the typical material POs for one phase. Skips phases
    whose category list is empty (planning / design / audit work)."""
    categories = PHASE_PURCHASE_CATEGORIES.get(phase, [])
    if not categories:
        return []

    # Run the per-category supplier predictions in parallel — each
    # category is two Aito calls (predict supplier, search history).
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda c: (c, *_predict_purchase_supplier(client, project_type, c)),
            categories,
        ))

    out: list[PurchaseSuggestion] = []
    for category, supplier, p, avg, coverage in results:
        if not supplier:
            continue
        out.append(PurchaseSuggestion(
            phase=phase,
            category=category,
            supplier=supplier,
            supplier_confidence=p,
            typical_amount_eur=avg,
            coverage=coverage,
        ))
    return out


# ── public API ──────────────────────────────────────────────────────


def generate_plan(
    client: AitoClient,
    project_type: str,
    region: str,
    season: str,
    estimated_budget_eur: float | None = None,
) -> GeneratedPlan:
    """Generative project-plan flow.

    Look up the typical phase + task list for `project_type` from
    history, then for each task run parallel `_predict`s on the
    `tasks` table for assignee, planned_days, planned_cost_eur. The
    return is a ready-to-edit plan drawn from real precedent.

    The whole call ships ~3-5 `_predict` requests per task — the
    latency ticker on the demo will show 30+ pills fly past, which
    is the point: visitors *see* that "Aito drafts this plan" is
    real database work, not a single offline LLM call.
    """
    history = _completed_tasks_for_type(client, project_type)
    if not history:
        return GeneratedPlan(
            project_type=project_type,
            region=region,
            season=season,
            estimated_budget_eur=estimated_budget_eur,
            phases=[],
            tasks=[],
        )

    typical = _typical_tasks_per_phase(history, limit=MAX_TASKS_PER_PHASE)
    phases = _ordered_phases(list(typical.keys()))

    plan = GeneratedPlan(
        project_type=project_type,
        region=region,
        season=season,
        estimated_budget_eur=estimated_budget_eur,
        phases=phases,
    )

    # Run the per-task predict fan-out in parallel — keeps total latency
    # under ~3s even for a 25-task construction plan.
    work: list[tuple[str, str]] = []
    for phase in phases:
        for task_name in typical.get(phase, []):
            work.append((phase, task_name))

    with ThreadPoolExecutor(max_workers=8) as pool:
        plan.tasks = list(pool.map(
            lambda pt: _predict_task_assignment(
                client, project_type, pt[0], pt[1], region, season,
            ),
            work,
        ))

        # Per-phase material POs: which categories does this phase
        # typically need, and which supplier does Aito recommend per
        # category? Runs alongside the task fan-out so the entire
        # plan (tasks + auto-POs) lands in one round-trip.
        purchases_per_phase = list(pool.map(
            lambda phase: predict_purchases_for_phase(client, project_type, phase),
            phases,
        ))
    plan.purchases = [p for sub in purchases_per_phase for p in sub]

    return plan


def rerank_assignees(
    client: AitoClient,
    phase: str,
    project_type: str,
    region: str,
    season: str,
    top_n: int = 5,
) -> list[AlternativeAssignee]:
    """Subcontractor matchmaking via `_recommend goal: {success: true}`.

    Returns the historical-best subcontractor candidates for the
    given task context, ranked by P(success). Pairs with `_predict
    success` so the UI can show "currently assigned X (P=0.55) →
    swap to Y (P=0.93)".
    """
    where = {
        "phase": phase,
        "project_type": project_type,
        "region": region,
        "season": season,
        "assignee_kind": "subcontractor",
    }
    try:
        response = client.recommend(
            table="tasks",
            where=where,
            recommend_field="subcontractor",
            goal={"success": True},
            limit=top_n,
        )
    except Exception as exc:
        log.warning("recommend subcontractor failed: %s", exc)
        return []

    hits = response.get("hits") or []

    # Pull historical sample-size + averages per candidate from a
    # parallel search call. Single fetch over the (phase, project_type)
    # slice avoids one search per candidate.
    history = _completed_tasks_for_type(client, project_type, limit=1500)
    history_by_sub: dict[str, list[dict]] = {}
    for row in history:
        if row.get("phase") != phase:
            continue
        sub = row.get("subcontractor")
        if not sub:
            continue
        history_by_sub.setdefault(sub, []).append(row)

    out: list[AlternativeAssignee] = []
    for hit in hits:
        # _recommend hit shape mirrors _predict: feature + $p.
        name = hit.get("feature") or hit.get("subcontractor")
        if not name:
            continue
        rows = history_by_sub.get(str(name), [])
        out.append(AlternativeAssignee(
            name=str(name),
            success_p=float(hit.get("$p", 0.0)),
            coverage=len(rows),
            avg_days=(
                sum(r["planned_days"] for r in rows) / len(rows)
                if rows else None
            ),
            avg_cost_eur=(
                sum(float(r["planned_cost_eur"]) for r in rows) / len(rows)
                if rows else None
            ),
        ))
    return out

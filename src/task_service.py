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
class GeneratedPlan:
    project_type: str
    region: str
    season: str
    estimated_budget_eur: float | None
    phases: list[str]
    tasks: list[TaskCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "project_type": self.project_type,
            "region": self.region,
            "season": self.season,
            "estimated_budget_eur": self.estimated_budget_eur,
            "phases": self.phases,
            "tasks": [t.to_dict() for t in self.tasks],
            # Convenience aggregates for the UI's headline stats.
            "total_planned_days": sum(t.planned_days for t in self.tasks),
            "total_planned_cost_eur": sum(t.planned_cost_eur for t in self.tasks),
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

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

import contextvars
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from src.aito_client import AitoClient
from src.why_processor import process_factors

log = logging.getLogger(__name__)

T = TypeVar("T")


def _ctx_map(pool: ThreadPoolExecutor, fn: Callable[..., T], iterable) -> list[T]:
    """`ThreadPoolExecutor.map` that propagates the calling thread's
    `contextvars` context into each worker.

    Without this, the per-request timing bucket bound by the FastAPI
    middleware (in `src/timing.py`) never reaches worker threads, and
    every Aito call made in the fan-out fails to record into the
    `X-Aito-Calls` response header. The latency badge then shows just
    the main-thread `_search` instead of the real ~140 calls a
    generated plan ships.

    Two subtleties:
      - `copy_context()` must be called from the *parent* thread; if
        called inside the worker it captures the worker's (empty)
        context. So we pre-create one copy per item before submitting.
      - We need a *separate* copy per worker — `Context.run` rejects
        concurrent re-entries of the same Context. Different copies
        still share the underlying ContextVar storage references, so
        all workers' `record_call` appends land in the same list that
        the middleware reads.
    """
    def submit(item: Any):
        ctx = contextvars.copy_context()
        return pool.submit(ctx.run, fn, item)

    futures = [submit(item) for item in iterable]
    return [f.result() for f in futures]

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


# Supplier-portal listings — the storyline punchline. The ERP customer
# operates an external supplier management system (think Jakamo-style
# supplier portal); suppliers register their offerings against each
# category there. When the planner edits a material PO, we surface
# Aito's history-ranked picks *plus* portal-listed candidates as
# additional options. The portal candidates have no purchase history
# yet, so they show a "new entrant" badge instead of an Aito $p — once
# they execute even a few POs, `_predict` would start picking them
# up alongside the historical ones.
#
# Picked to NOT collide with the suppliers already in Metsä's fixtures
# so the demo visibly mixes "from history" with "from portal".
SUPPLIER_PORTAL_LISTINGS: dict[str, list[str]] = {
    "production":   ["Pohjola Industrial", "Nordic Machinery"],
    "construction": ["Skanska Suomi", "Peab Finland"],
    "electrical":   ["Sähkö-Pekka", "Helsinki Electrical"],
    "maintenance":  ["Are Talotekniikka"],
    "fuel":         ["St1 Oy"],
    "ppe":          ["Würth Finland"],
    "cleaning":     ["ISS Suomi"],
    "capex":        ["Granlund Manufacturing"],
    "security":     ["Securitas Finland"],
    "telecom":      ["Elisa Yritysasiakkaat"],
    "office":       ["Staples Finland"],
    "utilities":    ["Helen Oy"],
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
    materials: list["MaterialSuggestion"] = field(default_factory=list)

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
            "materials": [m.to_dict() for m in self.materials],
        }


@dataclass
class MaterialSuggestion:
    """One material line under a task — what's needed, who supplies it, what it costs.

    The Aito story per material:
      - product line: top `description` from `purchases` history for the
        task's phase category (search + counter — same pattern as
        `suggest_tasks_for_phase`, because `description` is a Text column
        and `_predict` would return tokens).
      - supplier: `_predict from=purchases predict=supplier
        where={category, description}` — who, in this buyer's history,
        usually delivers this product line. The processed `$why` rides
        along so the UI's `?` popover shows the lift chain.
      - estimated amount: `_predict from=purchases predict=amount_eur
        where={category, description, supplier}` — Aito's numeric
        prediction for the line's EUR cost.
    """
    description: str                # product line, e.g. "Steel erection batch"
    category: str                   # purchases.category bucket
    supplier: str
    supplier_source: str            # "history" | "portal"
    supplier_confidence: float
    supplier_why: dict | None
    estimated_amount_eur: float | None
    amount_confidence: float        # $p for the amount prediction
    coverage: int                   # # of historical rows behind the supplier pick

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "category": self.category,
            "supplier": self.supplier,
            "supplier_source": self.supplier_source,
            "supplier_confidence": self.supplier_confidence,
            "supplier_why": self.supplier_why,
            "estimated_amount_eur": self.estimated_amount_eur,
            "amount_confidence": self.amount_confidence,
            "coverage": self.coverage,
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
    descriptions_by_category: dict[str, list[str]] | None = None,
) -> TaskCandidate:
    """Three parallel _predicts give Aito's best guess for one task row."""
    where = {
        "project_type": project_type,
        "phase": phase,
        "task_name": task_name,
        "region": region,
        "season": season,
    }

    # One copy per submitted task — Context.run rejects concurrent
    # re-entries of the same Context. All copies share the underlying
    # timing-bucket list via the ContextVar's reference semantics.
    with ThreadPoolExecutor(max_workers=4) as pool:
        kind_future = pool.submit(contextvars.copy_context().run, _predict_value, client, where, "assignee_kind")
        days_future = pool.submit(contextvars.copy_context().run, _predict_value, client, where, "planned_days")
        cost_future = pool.submit(contextvars.copy_context().run, _predict_value, client, where, "planned_cost_eur")

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

    materials = predict_materials_for_task(
        client, phase, task_name=task_name,
        descriptions_by_category=descriptions_by_category,
    )

    return TaskCandidate(
        phase=phase,
        task_name=task_name,
        assignee_kind=assignee_kind,
        assignee=str(assignee or "—"),
        assignee_confidence=assignee_p,
        planned_days=int(days_value or 0) if isinstance(days_value, (int, float)) else 0,
        planned_cost_eur=float(cost_value or 0) if isinstance(cost_value, (int, float)) else 0.0,
        success_p=success_p,
        materials=materials,
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
        results = _ctx_map(
            pool,
            lambda c: (c, *_predict_purchase_supplier(client, project_type, c)),
            categories,
        )

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


# ── per-task materials (product line + supplier + amount) ────────


# How many product lines we surface per task. 2 is a calibrated demo
# choice: a task like "Steel erection" naturally has ~2 dominant
# product lines in the buyer's history (e.g. "Steel erection batch"
# from construction + "Spare parts kit" from production); going higher
# adds noise without storytelling value.
MAX_MATERIALS_PER_TASK = 2


def _typical_descriptions_for_category(
    client: AitoClient, category: str, top_n: int = 4,
) -> list[str]:
    """Top-N product line names (Text `description` values) for a category.

    Mirrors `suggest_tasks_for_phase`'s approach for the same reason:
    `description` is a Text column, so `_predict description` would
    return token-level hits ("Steel", "erection", "batch") rather than
    the whole product line. Grouping a `_search` slice by exact value
    is the right shape and reads honestly in the panel."""
    try:
        sample = client.search(
            "purchases", {"category": category}, limit=600,
        )
    except Exception as exc:
        log.warning("description search (%s) failed: %s", category, exc)
        return []
    rows = sample.get("hits") or []
    if not rows:
        return []
    counts: Counter = Counter()
    for r in rows:
        d = r.get("description")
        if d:
            counts[d] += 1
    return [d for d, _ in counts.most_common(top_n)]


def _predict_material_supplier_and_amount(
    client: AitoClient, category: str, description: str,
) -> MaterialSuggestion | None:
    """Two-call fan-out per product line: who supplies it, and at what cost.

    Both calls condition on (category, description) so the prediction
    is scoped to the exact product line — not a broad category average.
    Returns None if Aito can't pick a supplier (unloaded slice, missing
    table, etc.) so the caller can drop the line cleanly.
    """
    where = {"category": category, "description": description}
    try:
        supplier_resp = client.predict("purchases", where, "supplier", limit=1)
    except Exception as exc:
        log.warning("predict material supplier failed (%s/%s): %s", category, description, exc)
        return None
    s_hits = supplier_resp.get("hits") or []
    if not s_hits:
        return None
    supplier_hit = s_hits[0]
    supplier = supplier_hit.get("feature")
    if not supplier:
        return None
    supplier_p = float(supplier_hit.get("$p", 0.0))
    supplier_why = process_factors(supplier_hit.get("$why"), supplier_p)

    # Amount is conditioned on the chosen supplier — gets us the
    # supplier-specific price band rather than the category-wide one.
    amount_where = {**where, "supplier": supplier}
    estimated: float | None = None
    amount_p = 0.0
    try:
        amount_resp = client.predict("purchases", amount_where, "amount_eur", limit=1)
        a_hits = amount_resp.get("hits") or []
        if a_hits:
            feat = a_hits[0].get("feature")
            if isinstance(feat, (int, float)):
                estimated = float(feat)
                amount_p = float(a_hits[0].get("$p", 0.0))
    except Exception as exc:
        log.warning("predict material amount failed (%s/%s/%s): %s", category, description, supplier, exc)

    # Coverage = # of historical rows that match the exact slice. One
    # cheap search so the UI can show "n=42 history rows behind this".
    coverage = 0
    try:
        s = client.search("purchases", amount_where, limit=1)
        coverage = int(s.get("total", 0))
    except Exception:
        pass

    return MaterialSuggestion(
        description=description,
        category=category,
        supplier=str(supplier),
        supplier_source="history",
        supplier_confidence=supplier_p,
        supplier_why=supplier_why,
        estimated_amount_eur=estimated,
        amount_confidence=amount_p,
        coverage=coverage,
    )


# Tokens that distract more than they help when matching task names
# against purchase descriptions ("Drainage installation" → useful token
# is "drainage", not "installation" which is generic). Trimmed to the
# few that actually pollute the metsä task corpus — keep small.
_TASK_STOP_TOKENS = {
    "installation", "subcontract", "service", "services",
    "system", "systems", "with", "and", "the", "for", "of",
}


def _task_name_tokens(task_name: str) -> list[str]:
    """Tokens worth matching against `purchases.description`.

    Lowercase, keep alphanumeric, drop generic words and tokens <4 chars
    so "Steel erection" → ["steel", "erection"] and "Drainage installation"
    → ["drainage"] (rather than ["drainage","installation"] which would
    flood matches with every "installation" row in the table).
    """
    import re
    raw = re.split(r"[^A-Za-z0-9]+", task_name.lower())
    return [t for t in raw if len(t) >= 4 and t not in _TASK_STOP_TOKENS]


def _task_specific_descriptions(
    client: AitoClient, phase: str, task_name: str, top_n: int,
) -> list[tuple[str, str]]:
    """Find (category, description) candidates whose tokens overlap with
    the task name. Drives task-specific materials — e.g. a "Steel
    erection" task surfaces "Steel erection batch", not whatever's
    most frequent in the construction category overall.

    One `_search` per phase category using `$or` over token-level
    `$has` clauses; aggregate by frequency. Returns empty when no
    overlap is found; the caller falls back to phase-wide descriptions.
    """
    categories = PHASE_PURCHASE_CATEGORIES.get(phase, [])
    tokens = _task_name_tokens(task_name)
    if not categories or not tokens:
        return []

    or_clause = [{"description": {"$has": t}} for t in tokens]
    counts: Counter = Counter()
    for cat in categories:
        where = {"category": cat, "$or": or_clause}
        try:
            resp = client.search("purchases", where, limit=200)
        except Exception:
            continue
        for row in (resp.get("hits") or []):
            d = row.get("description")
            if d:
                counts[(cat, d)] += 1
    return [pair for pair, _ in counts.most_common(top_n)]


def predict_materials_for_task(
    client: AitoClient,
    phase: str,
    task_name: str | None = None,
    descriptions_by_category: dict[str, list[str]] | None = None,
    top_n: int = MAX_MATERIALS_PER_TASK,
) -> list[MaterialSuggestion]:
    """Predict the typical material lines for one task.

    Two-step strategy:
      1. If `task_name` is given, try a task-specific lookup that
         filters `purchases.description` by token overlap with the
         task name (Aito's `$has` on the Text column). A task called
         "Steel erection" surfaces "Steel erection batch" rather than
         the phase's most-frequent description overall.
      2. Fall back to phase-wide top descriptions per category when
         no overlap is found — covers tasks whose names don't share
         vocabulary with any purchase line (e.g. "Site survey",
         "Quality control").

    For each surfaced (category, description) pair we then run two
    `_predict`s on `purchases`: one for the supplier, one for the
    amount. Each result rides with the supplier's processed `$why`
    so the UI's `?` popover shows the lift chain.

    `descriptions_by_category` is an optional pre-computed map used by
    the full-plan generator to avoid repeating per-category searches
    across many tasks.
    """
    categories = PHASE_PURCHASE_CATEGORIES.get(phase, [])
    if not categories:
        return []

    candidates: list[tuple[str, str]] = []
    if task_name:
        candidates = _task_specific_descriptions(client, phase, task_name, top_n)

    if len(candidates) < top_n:
        # Pad with phase-wide top descriptions, round-robin across
        # the phase's categories so the materials feel diverse.
        descriptions_by_category = descriptions_by_category or {}
        seen: set[tuple[str, str]] = set(candidates)
        per_cat_idx = {cat: 0 for cat in categories}
        while len(candidates) < top_n:
            progressed = False
            for cat in categories:
                descs = descriptions_by_category.get(cat) or _typical_descriptions_for_category(
                    client, cat, top_n=top_n,
                )
                descriptions_by_category[cat] = descs
                idx = per_cat_idx[cat]
                while idx < len(descs) and (cat, descs[idx]) in seen:
                    idx += 1
                if idx < len(descs):
                    pair = (cat, descs[idx])
                    candidates.append(pair)
                    seen.add(pair)
                    per_cat_idx[cat] = idx + 1
                    progressed = True
                    if len(candidates) >= top_n:
                        break
                else:
                    per_cat_idx[cat] = idx
            if not progressed:
                break

    if not candidates:
        return []

    with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as pool:
        results = _ctx_map(
            pool,
            lambda cd: _predict_material_supplier_and_amount(client, cd[0], cd[1]),
            candidates,
        )

    return [m for m in results if m is not None]


# ── supplier swap (editable material rows) ────────────────────────


@dataclass
class SupplierOption:
    """One candidate supplier in the material-PO editor's dropdown.

    Two sources are mixed in a single ranked list:

      - `source="history"` — Aito's `_predict from=purchases predict=supplier`
        hits for the category. Confidence is the model's $p; `why` carries
        the processed $why factors for the WhyPopover.

      - `source="portal"` — suppliers listed against the category in the
        external supplier management system the ERP customer just
        acquired. They have no purchase history yet, so $p is meaningless
        — we surface a synthetic `portal_listed_at` score (newest first)
        and let the UI badge them as "new entrant via portal".
    """
    supplier: str
    source: str                    # "history" | "portal"
    confidence: float              # $p from _predict (history) or 0.0 (portal)
    coverage: int                  # # of historical POs (history) or 0 (portal)
    avg_amount_eur: float | None
    why: dict | None               # processed $why for history; None for portal

    def to_dict(self) -> dict:
        return {
            "supplier": self.supplier,
            "source": self.source,
            "confidence": self.confidence,
            "coverage": self.coverage,
            "avg_amount_eur": self.avg_amount_eur,
            "why": self.why,
        }


def _supplier_history_stats_scoped(
    client: AitoClient, category: str, supplier: str, description: str | None,
) -> tuple[int, float | None]:
    """Same as `_supplier_history_stats` but optionally scopes by
    product line. When `description` is set, the dropdown's per-row
    "n=… · ~€…" reflects rows for the exact product line — not the
    category as a whole."""
    where = {"category": category, "supplier": supplier}
    if description:
        where["description"] = description
    try:
        sample = client.search("purchases", where, limit=120)
    except Exception:
        return 0, None
    rows = sample.get("hits") or []
    coverage = sample.get("total", len(rows))
    if not rows:
        return coverage, None
    avg = sum(float(r["amount_eur"]) for r in rows) / len(rows)
    return coverage, avg


def suggest_suppliers_for_category(
    client: AitoClient,
    category: str,
    top_n: int = 5,
    description: str | None = None,
) -> list[SupplierOption]:
    """Top-N supplier candidates for a material category, mixing
    history (Aito _predict) with supplier-portal listings.

    When `description` is provided, the where-clause narrows to that
    product line so the dropdown surfaces who actually supplies it
    (e.g. "Steel erection batch") rather than the category at large.
    Each history hit carries the processed $why for the popover;
    portal hits carry none.
    """
    where: dict = {"category": category}
    if description:
        where["description"] = description
    try:
        response = client.predict("purchases", where, "supplier", limit=top_n)
    except Exception as exc:
        log.warning("predict supplier candidates (%s/%s) failed: %s", category, description, exc)
        response = {"hits": []}

    hits = response.get("hits") or []

    # Fan out the per-supplier stats in parallel so the dropdown
    # populates in one round-trip even when top_n=5.
    history_names: list[tuple[str, float, dict | None]] = []
    for hit in hits:
        name = hit.get("feature")
        if not name:
            continue
        p = float(hit.get("$p", 0.0))
        why = process_factors(hit.get("$why"), p)
        history_names.append((str(name), p, why))

    if history_names:
        with ThreadPoolExecutor(max_workers=min(5, len(history_names))) as pool:
            stats = _ctx_map(
                pool,
                lambda item: _supplier_history_stats_scoped(
                    client, category, item[0], description,
                ),
                history_names,
            )
    else:
        stats = []

    options: list[SupplierOption] = []
    seen: set[str] = set()
    for (name, p, why), (coverage, avg) in zip(history_names, stats):
        options.append(SupplierOption(
            supplier=name,
            source="history",
            confidence=p,
            coverage=coverage,
            avg_amount_eur=avg,
            why=why,
        ))
        seen.add(name)

    # Append portal-listed suppliers that aren't already in the
    # history list — they're the "supplier management system pushes a
    # new entrant into planning" half of the demo.
    for portal_name in SUPPLIER_PORTAL_LISTINGS.get(category, []):
        if portal_name in seen:
            continue
        options.append(SupplierOption(
            supplier=portal_name,
            source="portal",
            confidence=0.0,
            coverage=0,
            avg_amount_eur=None,
            why=None,
        ))

    return options


# ── interactive / step-by-step planning ───────────────────────────


@dataclass
class PhaseOption:
    """One candidate phase in the step-by-step walker."""
    phase: str
    p: float                 # probability from `_predict phase`
    typical_task_count: int  # historical mean of N tasks/phase

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "p": self.p,
            "typical_task_count": self.typical_task_count,
        }


@dataclass
class TaskOption:
    """One candidate task name in the step-by-step walker."""
    task_name: str
    p: float
    typical_days: int
    typical_cost_eur: float

    def to_dict(self) -> dict:
        return {
            "task_name": self.task_name,
            "p": self.p,
            "typical_days": self.typical_days,
            "typical_cost_eur": self.typical_cost_eur,
        }


@dataclass
class AssigneeOption:
    """One candidate assignee for a specific task."""
    assignee_kind: str       # "subcontractor" | "employee"
    name: str
    p: float                 # confidence from `_predict subcontractor|assignee_person`
    success_p: float         # P(success) given this assignment

    def to_dict(self) -> dict:
        return {
            "assignee_kind": self.assignee_kind,
            "name": self.name,
            "p": self.p,
            "success_p": self.success_p,
        }


def suggest_next_phase(
    client: AitoClient,
    project_type: str,
    region: str,
    season: str,
    accepted_phases: list[str],
    top_n: int = 3,
) -> list[PhaseOption]:
    """Aito's best guesses for the *next* phase, given the project
    context plus the phases the user has already accepted. Used by the
    step-by-step walker — every click triggers a fresh `_predict`."""
    where = {
        "project_type": project_type,
        "region": region,
        "season": season,
    }
    try:
        response = client.predict("tasks", where, "phase", limit=top_n + len(accepted_phases) + 2)
    except Exception as exc:
        log.warning("predict phase failed: %s", exc)
        return []
    hits = response.get("hits") or []

    # Historical task-count per phase, used to show "~N tasks" so the
    # user knows how big a phase is before accepting it.
    history = _completed_tasks_for_type(client, project_type, limit=1500)
    counts_per_project: dict[tuple[str, str], int] = {}
    for row in history:
        key = (row["project_id"], row["phase"])
        counts_per_project[key] = counts_per_project.get(key, 0) + 1
    by_phase: dict[str, list[int]] = {}
    for (_pid, phase), n in counts_per_project.items():
        by_phase.setdefault(phase, []).append(n)
    typical = {p: round(sum(ns) / len(ns)) for p, ns in by_phase.items()}

    accepted = set(accepted_phases)
    candidates: list[PhaseOption] = []
    for hit in hits:
        phase = hit.get("feature")
        if not phase or phase in accepted:
            continue
        candidates.append(PhaseOption(
            phase=str(phase),
            p=float(hit.get("$p", 0.0)),
            typical_task_count=typical.get(str(phase), 0),
        ))

    # Sort by (PHASE_ORDER position, descending P). The walker is
    # building a plan in execution order; surfacing `site-prep` first
    # before `mep` matches what the user expects, even when MEP wins
    # on raw frequency. Phases unknown to PHASE_ORDER sink to the
    # bottom but stay sorted by P among themselves.
    def order_key(opt: PhaseOption):
        try:
            pos = PHASE_ORDER.index(opt.phase)
        except ValueError:
            pos = len(PHASE_ORDER)
        return (pos, -opt.p)

    candidates.sort(key=order_key)
    return candidates[:top_n]


def suggest_tasks_for_phase(
    client: AitoClient,
    project_type: str,
    phase: str,
    region: str,
    season: str,
    accepted_task_names: list[str],
    top_n: int = 4,
) -> list[TaskOption]:
    """Top-N task name suggestions for the current phase, with typical
    days/cost from history. The walker calls this once per phase and
    lets the user accept individual tasks (or accept all at once).

    Why `_search` + Counter and not `_predict task_name`: the schema
    keeps `task_name` as a Text column so Aito tokenises it (so the
    full-plan generator's `_predict task_name` would return token-
    level hits like "HVAC" instead of the whole "HVAC commissioning"
    string). For the demo's purpose — proposing the typical task
    names for a phase from history — frequency over a `_search` slice
    is the right shape and is what `generate_plan` already uses."""
    history = _completed_tasks_for_type(client, project_type, limit=1500)
    by_name: dict[str, list[dict]] = {}
    for row in history:
        if row["phase"] != phase:
            continue
        by_name.setdefault(row["task_name"], []).append(row)

    if not by_name:
        return []

    total = sum(len(rs) for rs in by_name.values())
    accepted = set(accepted_task_names)
    ranked = sorted(by_name.items(), key=lambda kv: -len(kv[1]))

    out: list[TaskOption] = []
    for name, rows in ranked:
        if name in accepted:
            continue
        avg_days = sum(r["planned_days"] for r in rows) / len(rows)
        avg_cost = sum(float(r["planned_cost_eur"]) for r in rows) / len(rows)
        out.append(TaskOption(
            task_name=name,
            # Frequency-as-probability: the share of tasks in this phase
            # × project_type slice that carry this name. Honest with
            # what the demo is doing (not labelling raw `_search`
            # results as `_predict`).
            p=len(rows) / total,
            typical_days=int(round(avg_days)),
            typical_cost_eur=round(avg_cost, -1),
        ))
        if len(out) >= top_n:
            break
    return out


def suggest_assignees(
    client: AitoClient,
    project_type: str,
    phase: str,
    task_name: str,
    region: str,
    season: str,
    top_n: int = 3,
) -> list[AssigneeOption]:
    """For one task context, return the top-N candidate assignees with
    P(success) for each — the step-by-step walker's per-task slot.

    Unlike `_predict_task_assignment` (which picks the single most-likely
    assignee for one row of a generated plan), this one returns multiple
    candidates so the UI can show the user what *else* Aito would
    consider — closer to the rerank flow but constrained to the task
    name the user just accepted.
    """
    where = {
        "project_type": project_type,
        "phase": phase,
        "task_name": task_name,
        "region": region,
        "season": season,
    }
    # First decide the kind. Top hit's value drives whether we predict
    # subcontractors or employees on the next round.
    kind, _kind_p = _predict_value(client, where, "assignee_kind")
    kind = str(kind or "subcontractor")
    predict_field = "subcontractor" if kind == "subcontractor" else "assignee_person"

    try:
        response = client.predict(
            "tasks", {**where, "assignee_kind": kind}, predict_field, limit=top_n,
        )
    except Exception as exc:
        log.warning("predict assignee failed: %s", exc)
        return []
    hits = response.get("hits") or []

    # Run success-P lookups in parallel so the per-step UI stays snappy.
    out: list[AssigneeOption] = []
    parallel_args: list[tuple[str, float]] = []
    for hit in hits[:top_n]:
        name = hit.get("feature")
        p = float(hit.get("$p", 0.0))
        if name:
            parallel_args.append((str(name), p))

    if not parallel_args:
        return []

    with ThreadPoolExecutor(max_workers=max(2, len(parallel_args))) as pool:
        success_ps = _ctx_map(
            pool,
            lambda np: _success_p(
                client,
                {**where, "assignee_kind": kind, predict_field: np[0]},
            ),
            parallel_args,
        )

    for (name, p), success_p in zip(parallel_args, success_ps):
        out.append(AssigneeOption(
            assignee_kind=kind,
            name=name,
            p=p,
            success_p=success_p,
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

    # Pre-warm per-category descriptions once so the per-task fan-out
    # doesn't repeat the same _search across 20+ tasks. One call per
    # category that the plan's phases actually touch (typically ≤8).
    needed_categories: set[str] = set()
    for phase in phases:
        for cat in PHASE_PURCHASE_CATEGORIES.get(phase, []):
            needed_categories.add(cat)
    descriptions_by_category: dict[str, list[str]] = {}
    if needed_categories:
        ordered_cats = sorted(needed_categories)
        with ThreadPoolExecutor(max_workers=min(8, len(ordered_cats))) as pool:
            desc_lists = _ctx_map(
                pool,
                lambda c: _typical_descriptions_for_category(client, c, top_n=MAX_MATERIALS_PER_TASK),
                ordered_cats,
            )
        descriptions_by_category = dict(zip(ordered_cats, desc_lists))

    # Run the per-task predict fan-out in parallel. Each task ships
    # 4 predicts for assignment + ~4 predicts for materials (2 product
    # lines × 2 predicts) → ~8 calls per task. The latency badge will
    # light up with ~150-200 calls for a 25-task plan, which is the
    # point: the planner *sees* Aito working at every step.
    work: list[tuple[str, str]] = []
    for phase in phases:
        for task_name in typical.get(phase, []):
            work.append((phase, task_name))

    with ThreadPoolExecutor(max_workers=8) as pool:
        plan.tasks = _ctx_map(
            pool,
            lambda pt: _predict_task_assignment(
                client, project_type, pt[0], pt[1], region, season,
                descriptions_by_category,
            ),
            work,
        )

    # Phase-level purchases are derived from task-level materials so
    # the legacy `purchases` field still summarises spend at the phase
    # for any downstream consumers (KPIs, exports). Same shape as the
    # old per-phase predictor, just rolled up from the new flow.
    rollup: dict[tuple[str, str], list[MaterialSuggestion]] = {}
    for t in plan.tasks:
        for m in t.materials:
            rollup.setdefault((t.phase, m.category), []).append(m)
    for (phase, category), mats in rollup.items():
        top_supplier = Counter(m.supplier for m in mats).most_common(1)[0][0]
        in_top = [m for m in mats if m.supplier == top_supplier]
        avg = (
            sum(m.estimated_amount_eur for m in in_top if m.estimated_amount_eur is not None) / len(in_top)
            if any(m.estimated_amount_eur for m in in_top) else None
        )
        plan.purchases.append(PurchaseSuggestion(
            phase=phase,
            category=category,
            supplier=top_supplier,
            supplier_confidence=max(m.supplier_confidence for m in in_top),
            typical_amount_eur=avg,
            coverage=sum(m.coverage for m in in_top),
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

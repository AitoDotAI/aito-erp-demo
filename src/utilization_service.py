"""Utilization & Capacity — Studio's flagship services view.

Three signals combined per consultant:

  1. **Current load** — sum of `allocation_pct` across all *active*
     projects they're assigned to (from the `assignments` table).
     Anything over 100 is overloaded; under 60 means free capacity
     someone in sales should hear about today.

  2. **Historical norm** — average allocation across their completed
     projects. Tells you whether a low current load is a temporary
     bench gap or a structural under-utilisation.

  3. **At-risk load** — allocation tied to projects whose status is
     `at_risk` or `delayed`, or whose predicted success is below the
     review threshold. Lets a partner see "this person is 80% loaded
     but 30 of those 80 points are on projects that may slip".

Predictive layer (per-person detail call):
  - `_predict assignments.role` given person + project_type → what
    role this person *typically* takes on that kind of project.
  - `_predict assignments.allocation_pct` same shape → expected
    allocation. Drives the "if we win a typical implementation,
    here's what loading them costs" capacity planning conversation.

Why services-ERP buyers care: this is the canonical Severa / Kantata
/ Workday Adaptive view. Without it, a services prospect treats the
demo as commerce-flavoured.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass

from src.aito_client import AitoClient


REVIEW_THRESHOLD = 0.55
OVERLOAD_THRESHOLD = 110     # alloc % above which we flag as overloaded
AVAILABLE_THRESHOLD = 60     # alloc % below which we flag as available
AT_RISK_THRESHOLD = 25       # at-risk alloc % above which we flag as at-risk


@dataclass
class UtilizationRow:
    person: str
    primary_role: str            # most common role across all history
    current_allocation_pct: int  # sum of active assignments' allocation
    target_pct: int              # capacity target (100 by default)
    gap_pct: int                 # target - current (negative = over)
    historical_avg_pct: float    # avg allocation across completed projects
    at_risk_pct: int             # alloc on projects flagged at_risk/delayed
    active_projects: int
    completed_projects: int
    status: str                  # "overloaded" | "available" | "balanced" | "at_risk"

    def to_dict(self) -> dict:
        return {
            "person": self.person,
            "primary_role": self.primary_role,
            "current_allocation_pct": self.current_allocation_pct,
            "target_pct": self.target_pct,
            "gap_pct": self.gap_pct,
            "historical_avg_pct": self.historical_avg_pct,
            "at_risk_pct": self.at_risk_pct,
            "active_projects": self.active_projects,
            "completed_projects": self.completed_projects,
            "status": self.status,
        }


@dataclass
class UtilizationSummary:
    total_people: int
    avg_utilization: float
    overloaded_count: int
    available_count: int
    at_risk_count: int
    balanced_count: int

    def to_dict(self) -> dict:
        return {
            "total_people": self.total_people,
            "avg_utilization": self.avg_utilization,
            "overloaded_count": self.overloaded_count,
            "available_count": self.available_count,
            "at_risk_count": self.at_risk_count,
            "balanced_count": self.balanced_count,
        }


@dataclass
class UtilizationOverview:
    rows: list[UtilizationRow]
    summary: UtilizationSummary
    project_types: list[str]     # so the UI can populate the "what if" picker

    def to_dict(self) -> dict:
        return {
            "rows": [r.to_dict() for r in self.rows],
            "summary": self.summary.to_dict(),
            "project_types": self.project_types,
        }


@dataclass
class CapacityForecast:
    """Per-person predicted assignment shape on a hypothetical project."""
    person: str
    project_type: str
    predicted_role: str | None
    role_confidence: float
    role_alternatives: list[dict]
    predicted_allocation: int | None
    allocation_confidence: float
    historical_count: int        # how many past projects of this type they've worked on

    def to_dict(self) -> dict:
        return {
            "person": self.person,
            "project_type": self.project_type,
            "predicted_role": self.predicted_role,
            "role_confidence": self.role_confidence,
            "role_alternatives": self.role_alternatives,
            "predicted_allocation": self.predicted_allocation,
            "allocation_confidence": self.allocation_confidence,
            "historical_count": self.historical_count,
        }


# ── Helpers ─────────────────────────────────────────────────────────


def _classify(current: int, at_risk: int) -> str:
    if current > OVERLOAD_THRESHOLD:
        return "overloaded"
    if current < AVAILABLE_THRESHOLD:
        return "available"
    if at_risk > AT_RISK_THRESHOLD:
        return "at_risk"
    return "balanced"


def _fetch_all(client: AitoClient, table: str, limit: int = 2000) -> list[dict]:
    """Fetch all rows from a table; return [] if the table doesn't exist."""
    from src.aito_client import AitoError
    try:
        return client.search(table, {}, limit=limit).get("hits") or []
    except AitoError as exc:
        if exc.status_code == 400 and f"failed to open '{table}'" in str(exc):
            return []
        raise


# ── Public API ──────────────────────────────────────────────────────


def get_overview(client: AitoClient) -> UtilizationOverview:
    """Aggregate every consultant's load. Pure aggregation over
    `assignments` × `projects` — no per-row Aito predictions needed
    for this view; the predictive layer kicks in on per-person drill-
    down (see `forecast_assignment`)."""
    assignments = _fetch_all(client, "assignments", limit=3000)
    projects = _fetch_all(client, "projects", limit=1000)
    proj_lookup = {p["project_id"]: p for p in projects}

    by_person: dict[str, list[dict]] = defaultdict(list)
    for a in assignments:
        by_person[a["person"]].append(a)

    rows: list[UtilizationRow] = []
    for person, assigns in by_person.items():
        active_alloc = 0
        at_risk_alloc = 0
        active_count = 0
        completed_count = 0
        completed_allocs: list[int] = []
        roles: list[str] = []
        for a in assigns:
            roles.append(a.get("role") or "engineer")
            project = proj_lookup.get(a.get("project_id"))
            if not project:
                continue
            alloc = int(a.get("allocation_pct") or 0)
            status = project.get("status")
            if status == "complete":
                completed_count += 1
                completed_allocs.append(alloc)
            else:
                active_alloc += alloc
                active_count += 1
                if status in ("at_risk", "delayed"):
                    at_risk_alloc += alloc

        primary_role = Counter(roles).most_common(1)[0][0] if roles else "engineer"
        hist_avg = (
            sum(completed_allocs) / len(completed_allocs)
            if completed_allocs else 0.0
        )
        rows.append(UtilizationRow(
            person=person,
            primary_role=primary_role,
            current_allocation_pct=active_alloc,
            target_pct=100,
            gap_pct=100 - active_alloc,
            historical_avg_pct=round(hist_avg, 1),
            at_risk_pct=at_risk_alloc,
            active_projects=active_count,
            completed_projects=completed_count,
            status=_classify(active_alloc, at_risk_alloc),
        ))

    rows.sort(key=lambda r: -r.current_allocation_pct)

    summary = UtilizationSummary(
        total_people=len(rows),
        avg_utilization=round(
            sum(r.current_allocation_pct for r in rows) / max(len(rows), 1), 1,
        ),
        overloaded_count=sum(1 for r in rows if r.status == "overloaded"),
        available_count=sum(1 for r in rows if r.status == "available"),
        at_risk_count=sum(1 for r in rows if r.status == "at_risk"),
        balanced_count=sum(1 for r in rows if r.status == "balanced"),
    )

    project_types = sorted({
        p["project_type"] for p in projects if p.get("project_type")
    })

    return UtilizationOverview(rows=rows, summary=summary, project_types=project_types)


def forecast_assignment(client: AitoClient, person: str, project_type: str) -> CapacityForecast:
    """`If we put this person on a typical {project_type} engagement,
    what role do they take and at what allocation?` Uses Aito's
    `_predict` on the assignments table — `project_type` is
    denormalised onto each assignment row at fixture-load time so the
    query stays a plain single-table predict."""
    where = {
        "person": person,
        "project_type": project_type,
    }

    # Role
    role_pred = client.predict("assignments", where, "role", limit=4)
    role_hits = role_pred.get("hits") or []
    role_top = role_hits[0] if role_hits else None
    role_alts = [
        {"value": str(h.get("feature")), "confidence": float(h.get("$p", 0.0))}
        for h in role_hits[:5]
    ]

    # Allocation — Aito returns a discrete distribution since the field
    # is Int; we take the top-probability bucket.
    alloc_pred = client.predict("assignments", where, "allocation_pct", limit=4)
    alloc_hits = alloc_pred.get("hits") or []
    alloc_top = alloc_hits[0] if alloc_hits else None

    # Historical sample size — useful so the UI can flag "no history".
    history = client.search(
        "assignments",
        {**where},
        limit=200,
    )
    historical_count = len(history.get("hits") or [])

    return CapacityForecast(
        person=person,
        project_type=project_type,
        predicted_role=str(role_top.get("feature")) if role_top else None,
        role_confidence=float(role_top.get("$p", 0.0)) if role_top else 0.0,
        role_alternatives=role_alts,
        predicted_allocation=int(alloc_top.get("feature")) if alloc_top else None,
        allocation_confidence=float(alloc_top.get("$p", 0.0)) if alloc_top else 0.0,
        historical_count=historical_count,
    )

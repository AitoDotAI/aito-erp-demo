"""Project portfolio — predict success and surface broad success factors.

Three Aito patterns combine to answer the question a portfolio manager
asks every Monday: which active projects are at risk, and which signals
across the portfolio actually move outcomes?

  1. _search → list projects + compute KPIs (success / on-time /
     on-budget rates) over completed history.
  2. _predict success=true → for each active project, predict the
     probability it will succeed given its context (manager,
     project_type, team_size, budget × duration). $why returns the
     factor decomposition.
  3. _relate where={success: true} across several fields → which
     factors correlate with success across the portfolio. People
     come from `assignments.person` (String — one row per assignment,
     one factor per person, no text tokenisation), and project-level
     categoricals (manager, project_type, priority) come from
     `projects` directly. The result is one mixed factor list, not a
     people-only sidebar.
"""

from dataclasses import dataclass, field
from typing import Any

from src.aito_client import AitoClient
from src.why_processor import process_factors


REVIEW_THRESHOLD = 0.55


@dataclass
class ProjectKPIs:
    total: int
    completed: int
    active: int
    success_rate: float       # success / completed
    on_time_rate: float
    on_budget_rate: float
    at_risk_count: int        # active projects predicted < threshold

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "completed": self.completed,
            "active": self.active,
            "success_rate": self.success_rate,
            "on_time_rate": self.on_time_rate,
            "on_budget_rate": self.on_budget_rate,
            "at_risk_count": self.at_risk_count,
        }


@dataclass
class ProjectRow:
    project_id: str
    name: str
    project_type: str
    customer: str
    manager: str
    team_lead: str
    team_size: int
    team_members: str
    budget_eur: float
    duration_days: int
    priority: str
    status: str
    start_month: str
    on_time: bool | None
    on_budget: bool | None
    success: bool | None
    # Prediction (only for active projects)
    success_p: float | None = None
    success_alternatives: list[dict] = field(default_factory=list)
    success_why: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "project_type": self.project_type,
            "customer": self.customer,
            "manager": self.manager,
            "team_lead": self.team_lead,
            "team_size": self.team_size,
            "team_members": self.team_members,
            "budget_eur": self.budget_eur,
            "duration_days": self.duration_days,
            "priority": self.priority,
            "status": self.status,
            "start_month": self.start_month,
            "on_time": self.on_time,
            "on_budget": self.on_budget,
            "success": self.success,
            "success_p": self.success_p,
            "success_alternatives": self.success_alternatives,
            "success_why": self.success_why,
        }


@dataclass
class SuccessFactor:
    """One signal that correlates with project success.

    Mixed kinds in a single list: a person from assignments, a manager
    from projects, a project_type, a priority bucket. The frontend
    renders all of them in the same "Success factors" panel, so the
    `kind` discriminator drives styling and the `label` carries the
    human-readable category name.
    """
    kind: str                  # "person" | "manager" | "project_type" | "priority"
    label: str                 # "Person" | "Manager" | …
    field: str                 # source — "assignments.person", "projects.manager", …
    value: str                 # concrete value — "A. Lindgren", "design", "high"
    role_in_pattern: str       # "boost" | "drag" — direction of effect
    lift: float
    coverage: int              # rows matching condition AND this value
    success_rate_with: float
    success_rate_without: float

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "field": self.field,
            "value": self.value,
            "role_in_pattern": self.role_in_pattern,
            "lift": self.lift,
            "coverage": self.coverage,
            "success_rate_with": self.success_rate_with,
            "success_rate_without": self.success_rate_without,
        }


@dataclass
class PortfolioOverview:
    kpis: ProjectKPIs
    projects: list[ProjectRow]
    success_factors: list[SuccessFactor]

    def to_dict(self) -> dict:
        return {
            "kpis": self.kpis.to_dict(),
            "projects": [p.to_dict() for p in self.projects],
            "success_factors": [f.to_dict() for f in self.success_factors],
        }


def _extract_alternatives(hits: list[dict]) -> list[dict]:
    """Aito _predict on a Boolean returns hits like [{feature: true, $p: 0.83}, ...]."""
    out = []
    for h in hits[:5]:
        feat = h.get("feature")
        p = h.get("$p", 0.0)
        out.append({"value": str(feat), "confidence": float(p)})
    return out


def _success_p_from_response(response: dict) -> tuple[float, dict, list[dict]]:
    """Pull P(success=true) and its $why out of an Aito _predict response."""
    hits = response.get("hits") or []
    p_true = 0.0
    why_true: dict = {}
    for hit in hits:
        if hit.get("feature") in (True, "true", "True"):
            p_true = float(hit.get("$p", 0.0))
            why_true = hit.get("$why") or {}
            break
    explanation = process_factors(why_true, p_true)
    alts = _extract_alternatives(hits)
    return p_true, explanation, alts


def _list_projects(client: AitoClient) -> list[dict]:
    """Fetch all projects via _search.

    Returns an empty list when the `projects` table doesn't exist —
    keeps the page renderable on a fresh tenant DB that hasn't run
    `./do load-data` yet, instead of crashing the request.
    """
    from src.aito_client import AitoError
    try:
        response = client.search("projects", {}, limit=500)
    except AitoError as exc:
        if exc.status_code == 400 and "failed to open 'projects'" in str(exc):
            return []
        raise
    return response.get("hits") or []


def _compute_kpis(rows: list[ProjectRow]) -> ProjectKPIs:
    completed = [r for r in rows if r.status == "complete"]
    successful = [r for r in completed if r.success is True]
    on_time = [r for r in completed if r.on_time is True]
    on_budget = [r for r in completed if r.on_budget is True]
    active = [r for r in rows if r.status != "complete"]
    at_risk = [r for r in active if r.success_p is not None and r.success_p < REVIEW_THRESHOLD]

    n_completed = max(len(completed), 1)
    return ProjectKPIs(
        total=len(rows),
        completed=len(completed),
        active=len(active),
        success_rate=len(successful) / n_completed,
        on_time_rate=len(on_time) / n_completed,
        on_budget_rate=len(on_budget) / n_completed,
        at_risk_count=len(at_risk),
    )


def _forecast_active(client: AitoClient, row: ProjectRow) -> ProjectRow:
    """Run _predict success=true for an active project's context.

    `team_members` is deliberately absent from the where clause: it is
    a String column for display, not an Aito feature, so passing it
    here would only contribute one-of-a-kind values. The team-as-signal
    surfaces in the Success factors panel via `assignments.person`
    instead.
    """
    where = {
        "project_type": row.project_type,
        "manager": row.manager,
        "team_size": row.team_size,
        "duration_days": row.duration_days,
        "priority": row.priority,
        # budget_eur is decimal — included as is
        "budget_eur": row.budget_eur,
    }
    try:
        response = client.predict("projects", where, "success", limit=2)
    except Exception:
        return row
    p_true, why, alts = _success_p_from_response(response)
    row.success_p = p_true
    row.success_why = why
    row.success_alternatives = alts
    return row


# Project-level categorical fields we mine for success factors. People
# are mined separately off the assignments table — see _success_factors.
_PROJECT_FACTOR_FIELDS: list[tuple[str, str]] = [
    ("manager",      "Manager"),
    ("project_type", "Project type"),
    ("priority",     "Priority"),
]


def _factors_from_hits(
    hits: list[dict],
    *,
    kind: str,
    label: str,
    field: str,
    min_coverage: int,
) -> list[SuccessFactor]:
    out: list[SuccessFactor] = []
    for hit in hits:
        related = hit.get("related") or {}
        # Aito shape: {"<field>": {"$has": "<value>"}} or {"$is": ...}
        value = None
        for v in related.values():
            if isinstance(v, dict):
                value = v.get("$has") or v.get("$is")
                if value is not None:
                    break
        if value in (None, ""):
            continue
        fs = hit.get("fs") or {}
        ps = hit.get("ps") or {}
        coverage = int(fs.get("fOnCondition", 0))
        if coverage < min_coverage:
            continue
        lift = float(hit.get("lift", 1.0))
        out.append(SuccessFactor(
            kind=kind,
            label=label,
            field=field,
            value=str(value),
            role_in_pattern="boost" if lift >= 1.0 else "drag",
            lift=lift,
            coverage=coverage,
            success_rate_with=float(ps.get("pOnCondition", 0.0)),
            success_rate_without=float(ps.get("pOnNotCondition", ps.get("p", 0.0))),
        ))
    return out


def _success_factors(client: AitoClient) -> list[SuccessFactor]:
    """Discover what correlates with project success — broadly.

    Two `_relate` shapes feed one mixed list:

      - `from: assignments, where: {project_success: true}, relate: person`
        — surfaces individual people. `person` is a String column on
        assignments, so each name is one distinct value, not a
        bag-of-tokens. (That avoids the "feature 'r' from R. Keinonen"
        problem that comes from mining `_relate` over a Text field.)

      - `from: projects, where: {success: true}, relate: <field>` for
        each of `manager`, `project_type`, `priority` — surfaces
        project-level patterns: which managers carry success, which
        project types are over-represented in wins, etc.

    The combined list is sorted by magnitude of lift and capped, so
    the panel shows the strongest signal first regardless of kind.
    """
    factors: list[SuccessFactor] = []

    # People — assignments.person.
    try:
        people_response = client.relate(
            "assignments", {"project_success": True}, "person",
        )
        factors.extend(_factors_from_hits(
            people_response.get("hits") or [],
            kind="person",
            label="Person",
            field="assignments.person",
            min_coverage=4,
        ))
    except Exception:
        pass

    # Project-level categoricals — projects.<field>.
    for field_name, label in _PROJECT_FACTOR_FIELDS:
        try:
            response = client.relate(
                "projects", {"success": True}, field_name,
            )
        except Exception:
            continue
        factors.extend(_factors_from_hits(
            response.get("hits") or [],
            kind=field_name,
            label=label,
            field=f"projects.{field_name}",
            # Project-level fields have far fewer distinct values than
            # people; require more coverage so a single fluke doesn't
            # outrank a real signal.
            min_coverage=6,
        ))

    # Sort by distance from neutral (strongest signal first), with a
    # mild support tiebreaker so a 1.6× lift over 50 rows beats a 1.6×
    # lift over 5 rows.
    def score(f: SuccessFactor) -> float:
        return abs(f.lift - 1.0) * (1.0 + (f.coverage ** 0.5) * 0.05)

    factors.sort(key=score, reverse=True)
    return factors[:14]


def _row_from_dict(d: dict) -> ProjectRow:
    return ProjectRow(
        project_id=d["project_id"],
        name=d["name"],
        project_type=d["project_type"],
        customer=d["customer"],
        manager=d["manager"],
        team_lead=d["team_lead"],
        team_size=int(d["team_size"]),
        team_members=d["team_members"],
        budget_eur=float(d["budget_eur"]),
        duration_days=int(d["duration_days"]),
        priority=d["priority"],
        status=d["status"],
        start_month=d["start_month"],
        on_time=d.get("on_time"),
        on_budget=d.get("on_budget"),
        success=d.get("success"),
    )


def get_portfolio(client: AitoClient) -> PortfolioOverview:
    """Build the project portfolio: KPIs, project rows, staffing factors."""
    raw = _list_projects(client)
    rows = [_row_from_dict(d) for d in raw]

    # Forecast active projects in parallel for snappier startup.
    from concurrent.futures import ThreadPoolExecutor

    active = [r for r in rows if r.status != "complete"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda r: _forecast_active(client, r), active))

    # Sort: at-risk active first, then other active, then completed by month desc.
    def sort_key(r: ProjectRow):
        if r.status != "complete":
            risk = r.success_p if r.success_p is not None else 1.0
            return (0, risk)
        return (1, -int(r.start_month.replace("-", "")))

    rows.sort(key=sort_key)

    kpis = _compute_kpis(rows)
    factors = _success_factors(client)

    return PortfolioOverview(kpis=kpis, projects=rows, success_factors=factors)


def forecast_for_project(client: AitoClient, project_id: str) -> dict:
    """Predict success for a single project on demand.

    Used by the per-row "?" popover when it wants a live re-run instead
    of the cached portfolio entry. The where-clause matches
    `_forecast_active` — project-level fields only, no `team_members`.
    """
    raw = _list_projects(client)
    target = next((d for d in raw if d["project_id"] == project_id), None)
    if not target:
        return {"error": f"project {project_id} not found"}

    row = _row_from_dict(target)
    base = _forecast_active(client, row)
    return {
        "project_id": project_id,
        "base_p": base.success_p,
        "base_why": base.success_why,
        "alternatives": base.success_alternatives,
    }

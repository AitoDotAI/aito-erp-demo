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
     properties of the WORK correlate with success across the
     portfolio: project type, priority and the five outcome drivers
     (contract type, scope clarity, novelty, customer size, team
     seniority). No person appears in it — see `_success_factors`.
"""

from dataclasses import dataclass, field
from typing import Any

from src.aito_client import AitoClient
from src.concurrency import parallel_map
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

    Mixed kinds in a single list: a project_type, a priority bucket, an
    outcome driver such as scope_clarity. The frontend
    renders all of them in the same "Success factors" panel, so the
    `kind` discriminator drives styling and the `label` carries the
    human-readable category name.
    """
    kind: str                  # the projects column — "project_type", "scope_clarity", …
    label: str                 # "Project type" | "Scope clarity" | …
    field: str                 # source — "projects.project_type", …
    value: str                 # concrete value — "design", "unclear", "high"
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
        feat = h.get("$value")
        p = h.get("$p", 0.0)
        out.append({"value": str(feat), "confidence": float(p)})
    return out


def _success_p_from_response(response: dict) -> tuple[float, dict, list[dict]]:
    """Pull P(success=true) and its $why out of an Aito _predict response."""
    hits = response.get("hits") or []
    p_true = 0.0
    why_true: dict = {}
    for hit in hits:
        if hit.get("$value") in (True, "true", "True"):
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
    here would only contribute one-of-a-kind values.
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
# Properties of the work, never of a person. A list of "people who
# correlate with success" ranks colleagues by name on a shared screen,
# and a manager's name is a person too. The five drivers are the ones
# the fixture builds outcomes from (CLAUDE.md, "The outcome drivers"),
# so they are what the panel should be able to find.
_PROJECT_FACTOR_FIELDS: list[tuple[str, str]] = [
    ("project_type",   "Project type"),
    ("priority",       "Priority"),
    ("contract_type",  "Contract"),
    ("scope_clarity",  "Scope clarity"),
    ("novelty",        "Novelty"),
    ("customer_size",  "Customer size"),
    ("team_seniority", "Team seniority"),
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
        # `AitoClient.relate` hands back the canonical shape
        # {"<field>": "<value>"} on both API versions — v1's operator
        # wrapper ({"$has": …}) is unwrapped there, not here.
        value = next((v for v in related.values() if v not in (None, "")), None)
        if value is None:
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
    """Discover which properties of the work correlate with success.

    One `_relate` per field — `from: projects, where: {success: true},
    relate: <field>` — over project type, priority and the five outcome
    drivers, combined into one list sorted by strength of lift.

    People are deliberately absent. This panel used to relate
    `assignments.person` and `projects.manager`, which put named
    colleagues in a ranked list of what goes with success — a league
    table of people, presented as a finding. Who staffs well is the
    Engagement Planner's question, asked about one candidate at a time.
    """
    factors: list[SuccessFactor] = []
    # No try/except: a failed relate used to be skipped, so the panel
    # silently lost a whole kind of factor and still looked complete.
    for field_name, label in _PROJECT_FACTOR_FIELDS:
        response = client.relate("projects", {"success": True}, field_name)
        factors.extend(_factors_from_hits(
            response["hits"],
            kind=field_name,
            label=label,
            field=f"projects.{field_name}",
            # Few distinct values per field; require coverage so a single
            # fluke does not outrank a real signal.
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
    active = [r for r in rows if r.status != "complete"]
    parallel_map(lambda r: _forecast_active(client, r), active, workers=6)

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

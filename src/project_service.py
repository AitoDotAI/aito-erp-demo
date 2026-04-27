"""Project portfolio — predict success and surface staffing factors.

Three Aito patterns combine to answer the question a portfolio manager
asks every Monday: which active projects are at risk, and why?

  1. _search → list projects + compute KPIs (success / on-time /
     on-budget rates) over completed history.
  2. _predict success=true → for each active project, predict the
     probability it will succeed given its context (manager,
     project_type, team composition, budget × duration). $why returns
     the factor decomposition, including which team members shifted
     the prediction.
  3. _relate where={success: true} on assignments.person → which
     individuals correlate with project success across the portfolio.

The fourth pattern (staffing simulator: replace person X with Y, see
predicted delta) is straightforward — just run _predict twice with the
edited team_members. We expose it via the forecast endpoint by letting
the caller pass an override.
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
class StaffingFactor:
    person: str
    role_in_pattern: str       # "boost" | "drag" — direction of effect
    lift: float
    coverage: int              # how many completed projects had this person
    success_rate_with: float
    success_rate_without: float

    def to_dict(self) -> dict:
        return {
            "person": self.person,
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
    staffing_factors: list[StaffingFactor]

    def to_dict(self) -> dict:
        return {
            "kpis": self.kpis.to_dict(),
            "projects": [p.to_dict() for p in self.projects],
            "staffing_factors": [f.to_dict() for f in self.staffing_factors],
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
    """Run _predict success=true for an active project's context."""
    where = {
        "project_type": row.project_type,
        "manager": row.manager,
        "team_size": row.team_size,
        "team_members": row.team_members,
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


def _staffing_factors_from_relate(client: AitoClient) -> list[StaffingFactor]:
    """Use _relate to find people whose presence on a team predicts success.

    We relate `where={success: true}` over `projects.team_members`. The
    Text field stores names space-separated, so Aito tokenises and
    surfaces individual people whose presence is over-represented in
    successful projects. Lift > 1 = boost; lift < 1 = drag.

    Alternative implementation: query `from: assignments, where:
    {project_success: true}, relate: person` — this also works because
    `project_success` is denormalised onto the assignments table at
    fixture-load time. Both shapes return the same kind of result;
    we use the projects.team_members form because it's the more
    natural single-table answer to the question.
    """
    try:
        response = client.relate("projects", {"success": True}, "team_members")
    except Exception:
        return []

    hits = response.get("hits") or []
    factors: list[StaffingFactor] = []
    for hit in hits[:30]:
        related = hit.get("related") or {}
        # Aito returns related as e.g. {"person": {"$has": "A. Lindgren"}}
        person = None
        for v in related.values():
            if isinstance(v, dict):
                person = v.get("$has") or v.get("$is")
                if person:
                    break
        if not person:
            continue
        lift = float(hit.get("lift", 1.0))
        ps = hit.get("ps") or {}
        fs = hit.get("fs") or {}
        p_with = float(ps.get("pOnCondition", 0.0))
        p_without = float(ps.get("pOnNotCondition", ps.get("p", 0.0)))
        f_on = int(fs.get("fOnCondition", 0))
        if f_on < 4:  # need enough samples to be meaningful
            continue
        direction = "boost" if lift >= 1.0 else "drag"
        factors.append(StaffingFactor(
            person=str(person),
            role_in_pattern=direction,
            lift=lift,
            coverage=f_on,
            success_rate_with=p_with,
            success_rate_without=p_without,
        ))

    # Sort by absolute distance from neutral, strongest first.
    factors.sort(key=lambda f: abs(f.lift - 1.0), reverse=True)
    return factors[:12]


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
    factors = _staffing_factors_from_relate(client)

    return PortfolioOverview(kpis=kpis, projects=rows, staffing_factors=factors)


def forecast_with_override(
    client: AitoClient, project_id: str, team_members_override: str | None = None
) -> dict:
    """Predict success for a single project, optionally with an alternative team.

    Lets the caller swap team_members and see the predicted delta — the
    "what if I add A. Lindgren" simulator.
    """
    raw = _list_projects(client)
    target = next((d for d in raw if d["project_id"] == project_id), None)
    if not target:
        return {"error": f"project {project_id} not found"}

    row = _row_from_dict(target)
    base = _forecast_active(client, row)
    base_p = base.success_p

    if team_members_override:
        row_alt = _row_from_dict(target)
        row_alt.team_members = team_members_override
        alt = _forecast_active(client, row_alt)
        return {
            "project_id": project_id,
            "base_p": base_p,
            "base_why": base.success_why,
            "override_team_members": team_members_override,
            "override_p": alt.success_p,
            "override_why": alt.success_why,
            "delta": (alt.success_p or 0.0) - (base_p or 0.0),
        }

    return {
        "project_id": project_id,
        "base_p": base_p,
        "base_why": base.success_why,
        "alternatives": base.success_alternatives,
    }

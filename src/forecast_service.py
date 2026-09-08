"""Revenue outlook — when the order book turns into cash.

The question this answers is the one a services or construction CEO
asks every month and no standard ERP answers: *of the work we have
already sold, how much lands in each of the next few months, and how
much of that is at risk?* An ERP knows the order book. It does not know
which projects will slip, because slipping is a property of the
project's shape — its type, its manager, its crew size, its duration —
and that lives in the delivery history, not in the ledger.

Two Aito patterns, both over `projects`:

  1. _predict on_time  → will this project land on schedule?
  2. _predict on_budget → will it land inside its budget?

Both are conditioned on the same context `project_service` uses for
`success` (project_type, manager, team_size, duration_days, priority,
budget_eur), and both select `$why`, so the driver sits next to the
number rather than in a separate explanation step.

## The money model

Revenue is recognised by **percentage of completion** — the standard
for project accounting, and the only model that answers "which month".
A project's budget is earned evenly across its scheduled months:

    total_months     = duration_days / 30.44, min 1
    elapsed          = months between start and now, clamped
    remaining_eur    = budget × (total_months − elapsed) / total_months
    scheduled slice  = remaining_eur / months_remaining, per month

That is the *scheduled* curve, and it is what the ERP already implies.
The predictive part is what happens to it:

    expected in month m = slice × P(on_time)
    slipped             = remaining_eur × (1 − P(on_time))

with the slipped share landing in the month after the scheduled end.
So the two curves sum to the same total — nothing is invented or lost,
the money is only moved in time — and the gap between them is exactly
what the prediction is claiming.

## Overdue is a first-class state, not an error

A project whose scheduled end is already in the past has no remaining
scheduled month to spread into. Its unrecognised value is reported
separately as `overdue_eur` rather than being folded into the current
month, because "we are late and this has not landed" is a different
statement from "this lands in September" — and it is the one a
delivery lead most needs to see.
"""

from dataclasses import dataclass, field
from datetime import date

from src.aito_client import AitoClient, AitoError
from src.why_processor import process_factors


# How far forward the timeline runs. Three quarters is long enough to
# show a slip moving money between quarters — the thing the view
# exists to make visible — and short enough that every bar is real
# committed work rather than speculation.
HORIZON_MONTHS = 9

# Below this, a project's schedule is doing the reporting rather than
# the model, and the row is called out as at risk.
ON_TIME_REVIEW_THRESHOLD = 0.60


def _month_index(month: str) -> int:
    year, mon = month.split("-")
    return int(year) * 12 + int(mon) - 1


def _month_label(index: int) -> str:
    return f"{index // 12}-{index % 12 + 1:02d}"


def _month_span(duration_days: int) -> int:
    """Scheduled months a duration covers, minimum one.

    Mirrors `data/generate_personas.py:month_span` — the fixtures are
    scheduled in days and recognised in months, and both sides have to
    agree on the conversion or a project's last month drifts.
    """
    return max(1, round(duration_days / 30.44))


@dataclass
class ForecastMonth:
    month: str
    scheduled_eur: float   # what the schedule says lands this month
    expected_eur: float    # schedule × P(on time), per project
    slipped_eur: float     # arriving here because something slipped

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "scheduled_eur": round(self.scheduled_eur, 2),
            "expected_eur": round(self.expected_eur, 2),
            "slipped_eur": round(self.slipped_eur, 2),
        }


@dataclass
class ProjectOutlook:
    project_id: str
    name: str
    customer: str
    project_type: str
    manager: str
    status: str
    budget_eur: float
    start_month: str
    scheduled_end_month: str
    months_total: int
    months_remaining: int
    remaining_eur: float
    overdue: bool
    on_time_p: float | None = None
    on_budget_p: float | None = None
    on_time_why: dict = field(default_factory=dict)
    on_budget_why: dict = field(default_factory=dict)

    @property
    def at_risk_eur(self) -> float:
        """Remaining value the model does not expect to land on schedule."""
        if self.on_time_p is None:
            return 0.0
        return self.remaining_eur * (1.0 - self.on_time_p)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "customer": self.customer,
            "project_type": self.project_type,
            "manager": self.manager,
            "status": self.status,
            "budget_eur": self.budget_eur,
            "start_month": self.start_month,
            "scheduled_end_month": self.scheduled_end_month,
            "months_total": self.months_total,
            "months_remaining": self.months_remaining,
            "remaining_eur": round(self.remaining_eur, 2),
            "overdue": self.overdue,
            "on_time_p": self.on_time_p,
            "on_budget_p": self.on_budget_p,
            "at_risk_eur": round(self.at_risk_eur, 2),
            "on_time_why": self.on_time_why,
            "on_budget_why": self.on_budget_why,
        }


@dataclass
class OutlookKPIs:
    active_count: int
    order_book_eur: float      # unrecognised value across active projects
    next_quarter_eur: float    # expected to land in the next three months
    at_risk_eur: float         # remaining × (1 − P(on time)), summed
    overdue_count: int
    overdue_eur: float

    def to_dict(self) -> dict:
        return {
            "active_count": self.active_count,
            "order_book_eur": round(self.order_book_eur, 2),
            "next_quarter_eur": round(self.next_quarter_eur, 2),
            "at_risk_eur": round(self.at_risk_eur, 2),
            "overdue_count": self.overdue_count,
            "overdue_eur": round(self.overdue_eur, 2),
        }


@dataclass
class RevenueOutlook:
    as_of: str
    kpis: OutlookKPIs
    months: list[ForecastMonth]
    projects: list[ProjectOutlook]

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "kpis": self.kpis.to_dict(),
            "months": [m.to_dict() for m in self.months],
            "projects": [p.to_dict() for p in self.projects],
        }


def _list_projects(client: AitoClient) -> list[dict]:
    """Every project. Empty when the table isn't loaded on this tenant.

    Same tolerance `project_service._list_projects` has: a persona
    without a `projects` fixture should render an empty view, not a 500.
    """
    try:
        response = client.search("projects", {}, limit=500)
    except AitoError as exc:
        if exc.status_code == 400 and "failed to open 'projects'" in str(exc):
            return []
        raise
    return response.get("hits") or []


def _predict_true_p(client: AitoClient, where: dict,
                    predict_field: str) -> tuple[float | None, dict]:
    """P(field = true) for one project's context, with its $why.

    Returns `(None, {})` when Aito has no opinion — an empty hit list,
    or a hit set with no `true` candidate. That is reported as "no
    prediction" rather than coerced to 0.0, because 0.0 here would read
    on screen as "certain to be late", which is a different and much
    louder claim than "not enough history to say".
    """
    response = client.predict("projects", where, predict_field, limit=2)
    for hit in response.get("hits") or []:
        if hit.get("$value") in (True, "true", "True"):
            p = float(hit.get("$p", 0.0))
            return p, process_factors(hit.get("$why") or {}, p)
    return None, {}


def _context_for(project: dict) -> dict:
    """The where clause both predictions run against.

    Deliberately identical to the one `project_service` uses for
    `success`, so a project's on-time, on-budget and success numbers
    are all conditioned on the same facts and can be read side by side.
    `team_members` stays out for the same reason it does there: it is a
    display String, and every value in it is one of a kind.
    """
    return {
        "project_type": project.get("project_type"),
        "manager": project.get("manager"),
        "team_size": project.get("team_size"),
        "duration_days": project.get("duration_days"),
        "priority": project.get("priority"),
        "budget_eur": project.get("budget_eur"),
    }


def _outlook_for(project: dict, now_index: int) -> ProjectOutlook:
    """Schedule arithmetic for one active project. No Aito call here."""
    start = project["start_month"]
    months_total = _month_span(int(project["duration_days"]))
    start_index = _month_index(start)
    end_index = start_index + months_total - 1

    elapsed = min(max(now_index - start_index, 0), months_total)
    months_remaining = months_total - elapsed
    budget = float(project["budget_eur"])
    remaining = budget * (months_remaining / months_total)

    return ProjectOutlook(
        project_id=project["project_id"],
        name=project["name"],
        customer=project.get("customer", ""),
        project_type=project.get("project_type", ""),
        manager=project.get("manager", ""),
        status=project.get("status", "active"),
        budget_eur=budget,
        start_month=start,
        scheduled_end_month=_month_label(end_index),
        months_total=months_total,
        months_remaining=months_remaining,
        # An overdue project has burned its whole schedule, so
        # percentage-of-completion leaves nothing to recognise. Its
        # value is the full unbilled remainder instead — reported
        # under overdue_eur, never spread across future months.
        remaining_eur=budget if months_remaining == 0 else remaining,
        overdue=months_remaining == 0,
    )


def _build_timeline(outlooks: list[ProjectOutlook],
                    now_index: int, horizon: int) -> list[ForecastMonth]:
    """Spread each project's remaining value across the months it is
    scheduled to land in, then move the at-risk share to the slip month.

    Scheduled and expected+slipped sum to the same total per project:
    the prediction moves money in time, it never creates or destroys it.
    """
    months = [
        ForecastMonth(_month_label(now_index + offset), 0.0, 0.0, 0.0)
        for offset in range(horizon)
    ]
    by_index = {_month_index(m.month): m for m in months}

    for outlook in outlooks:
        if outlook.overdue or outlook.months_remaining == 0:
            continue
        slice_eur = outlook.remaining_eur / outlook.months_remaining
        # No prediction means no risk adjustment — the schedule is the
        # forecast, and the UI says so rather than implying certainty.
        p_on_time = 1.0 if outlook.on_time_p is None else outlook.on_time_p
        end_index = _month_index(outlook.scheduled_end_month)

        for offset in range(outlook.months_remaining):
            index = now_index + offset
            month = by_index.get(index)
            if month is None:      # beyond the horizon
                continue
            month.scheduled_eur += slice_eur
            month.expected_eur += slice_eur * p_on_time

        slipped = outlook.remaining_eur * (1.0 - p_on_time)
        slip_month = by_index.get(end_index + 1)
        if slip_month is not None and slipped:
            slip_month.slipped_eur += slipped
            slip_month.expected_eur += slipped

    return months


def get_outlook(client: AitoClient,
                horizon: int = HORIZON_MONTHS) -> RevenueOutlook:
    """The full revenue outlook: KPIs, a month timeline, and the rows.

    One `_search` for the portfolio, then two `_predict` calls per
    active project. Active projects are deliberately few — this is work
    in flight, not history — so the call count stays in the tens.
    """
    today = date.today()
    now_index = _month_index(f"{today.year}-{today.month:02d}")

    projects = _list_projects(client)
    active = [p for p in projects if p.get("status") != "complete"]

    outlooks: list[ProjectOutlook] = []
    for project in active:
        outlook = _outlook_for(project, now_index)
        context = _context_for(project)
        outlook.on_time_p, outlook.on_time_why = _predict_true_p(
            client, context, "on_time")
        outlook.on_budget_p, outlook.on_budget_why = _predict_true_p(
            client, context, "on_budget")
        outlooks.append(outlook)

    months = _build_timeline(outlooks, now_index, horizon)

    # Sort by what needs attention: the most value at risk first, so
    # the top of the table is the CEO's actual reading order.
    outlooks.sort(key=lambda o: -o.at_risk_eur)

    overdue = [o for o in outlooks if o.overdue]
    kpis = OutlookKPIs(
        active_count=len(outlooks),
        order_book_eur=sum(o.remaining_eur for o in outlooks),
        next_quarter_eur=sum(m.expected_eur for m in months[:3]),
        at_risk_eur=sum(o.at_risk_eur for o in outlooks),
        overdue_count=len(overdue),
        overdue_eur=sum(o.remaining_eur for o in overdue),
    )

    return RevenueOutlook(
        as_of=_month_label(now_index),
        kpis=kpis,
        months=months,
        projects=outlooks,
    )

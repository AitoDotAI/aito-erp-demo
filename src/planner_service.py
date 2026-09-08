"""Engagement Planner — staff a proposal, price it, and predict the no.

One screen for the conversation that happens before a project exists:
a customer, a scope, and a rough shape. Everything else on it is
predicted from what the organisation has already delivered and already
quoted.

Four questions, four Aito patterns, all on tables this demo already
carries:

  1. **What roles does work like this need?**
     `_predict role` on `assignments` filtered to the project type.
     The historical role mix, scaled to the requested team size — not
     a template someone maintains by hand.

  2. **Who should fill them?**
     `_predict person` on `assignments` where {project_type, role}.
     Ranked by how often that person actually does that role on that
     kind of work, with `$why` behind each. Each candidate is then
     annotated with their current allocation, so the best-fit name and
     the available name are visible in the same list — those are
     frequently not the same person, and that IS the staffing decision.

  3. **Will it land well?**
     `_predict success | on_time | on_budget` on `projects`, on the
     proposed shape. Same context the portfolio and revenue views use,
     so the numbers are comparable across screens.

  4. **Will they say yes — and if not, what will they say?**
     `_predict won` on `quotes`, then `_predict loss_reason` over the
     lost ones. This is the half no other table can answer: `projects`
     only records work that was WON, so it is survivorship-biased by
     construction. The losses live in `quotes`, and they are where the
     objection is.

(4) is the one worth pointing at in a demo. A delivery organisation's
standing fear is that a careful, honest estimate loses the deal on
price — so the planner prices the work from comparable history, shows
where the quote sits against that, and then says what the customer is
most likely to object to. Sometimes the answer is `timing`, not
`price`, which is the case where discounting would not have helped.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from statistics import median

from src.aito_client import AitoClient, AitoError
from src.availability_service import (WindowAvailability,
                                      availability_in_window, month_label,
                                      month_index, restrict, role_phases,
                                      window_months)
from src.utilization_service import get_overview as get_utilization
from src.why_processor import process_factors


# Where a quote sits against the going rate for comparable work. The
# boundaries are ratios against the median comparable, so they move
# with the data rather than being pinned to an absolute euro figure.
PRICE_BANDS = (
    (0.90, "under"),
    (1.10, "at_market"),
    (1.35, "over"),
    (float("inf"), "well_over"),
)

# A person at or above this is not really available, whatever their fit.
OVERLOAD_PCT = 110


@dataclass
class Candidate:
    person: str
    fit: float                 # P(person | project_type, role, site)
    current_load_pct: int
    status: str                # from the utilization view's own vocabulary
    # The person's own profile, returned by the SAME `_predict` call:
    # `assignments.person` links to `people.person`, so Aito hands back
    # every column of the linked row on each hit. No second lookup.
    title: str = ""
    discipline: str = ""
    skills: list[str] = field(default_factory=list)
    certifications: str = ""
    site: str = ""
    seniority: str = ""
    domains: list[str] = field(default_factory=list)
    years_experience: int = 0
    matches: list[dict] = field(default_factory=list)
    # Standing over THIS project's window, not a running total. A
    # person at 300% today whose bookings end before the project starts
    # is available for it; the flat number said otherwise.
    booked_pct: int = 0
    free_pct: int = 100
    available: bool = True
    absent_months: list[str] = field(default_factory=list)
    absence_kind: str = ""
    contention: int = 0
    contention_pct: int = 0
    # P(went_well = true) for THIS person in THIS seat —
    # `_predict went_well` with the person in the where. The question a
    # delivery lead is actually asking, and the only number here that
    # ranks people by how it went rather than by how often they were
    # picked.
    quality_p: float | None = None
    quality_why: dict = field(default_factory=dict)
    # How many assignments of this kind they have. A COUNT, because a
    # normalised share is not a fact about a person: `fit` sums to 1
    # across the shortlist, so it moves when the shortlist changes.
    history_count: int = 0
    why: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "person": self.person,
            "fit": self.fit,
            "current_load_pct": self.current_load_pct,
            "status": self.status,
            "title": self.title,
            "discipline": self.discipline,
            "skills": self.skills,
            "certifications": self.certifications,
            "site": self.site,
            "seniority": self.seniority,
            "domains": self.domains,
            "years_experience": self.years_experience,
            "matches": self.matches,
            "booked_pct": self.booked_pct,
            "free_pct": self.free_pct,
            "available": self.available,
            "absent_months": self.absent_months,
            "absence_kind": self.absence_kind,
            "contention": self.contention,
            "contention_pct": self.contention_pct,
            "quality_p": self.quality_p,
            "quality_why": self.quality_why,
            "history_count": self.history_count,
            "why": self.why,
        }


@dataclass
class RoleSlot:
    role: str
    count: int                 # how many of this role the mix implies
    share: float               # P(role) in comparable history
    candidates: list[Candidate]
    skills: str = ""           # `person.skills` requirement for THIS seat
    # Requirement terms this tenant has nobody for. Reported rather
    # than silently filtering the shortlist to nothing.
    unknown_skills: list[str] = field(default_factory=list)
    seniority: str = ""        # `person.seniority` filter for THIS seat
    # The months this seat actually occupies — a designer at the start,
    # a QA engineer at the end, not everyone for the whole project.
    from_month: str = ""
    to_month: str = ""
    # One name per seat, picked from `candidates` — see `_fill_seats`.
    # The dropdown in the UI offers the rest.
    assignees: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "count": self.count,
            "share": self.share,
            "skills": self.skills,
            "unknown_skills": self.unknown_skills,
            "seniority": self.seniority,
            "from_month": self.from_month,
            "to_month": self.to_month,
            "candidates": [c.to_dict() for c in self.candidates],
            "assignees": self.assignees,
        }


# Futurice's 3+3, in the order they are argued: the three that decide
# whether the engagement was worth doing, then the three that qualify
# it. Each is its own Boolean on `projects`, so each is its own
# `_predict` with its own `$why` — a schedule risk and a morale risk
# have different drivers and should not be one number.
CORE_OUTCOMES = [
    ("financial_ok", "Makes money"),
    ("team_happy", "Team stays happy"),
    ("customer_happy", "Customer stays happy"),
]
QUALIFYING_OUTCOMES = [
    ("on_time", "Lands when we said"),
    ("outcome_ok", "The thing works"),
    ("doors_opened", "Opens a door"),
]


@dataclass
class Outcome:
    field: str
    label: str
    p: float | None
    why: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"field": self.field, "label": self.label,
                "p": self.p, "why": self.why}


@dataclass
class DeliveryRisk:
    success_p: float | None
    core: list[Outcome]
    qualifying: list[Outcome]
    success_why: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success_p": self.success_p,
            "core": [o.to_dict() for o in self.core],
            "qualifying": [o.to_dict() for o in self.qualifying],
            "success_why": self.success_why,
        }


@dataclass
class PriceCheck:
    comparable_count: int
    median_eur: float
    low_eur: float             # 25th percentile of comparables
    high_eur: float            # 75th
    quoted_eur: float
    ratio: float               # quoted / median
    band: str

    def to_dict(self) -> dict:
        return {
            "comparable_count": self.comparable_count,
            "median_eur": round(self.median_eur, 2),
            "low_eur": round(self.low_eur, 2),
            "high_eur": round(self.high_eur, 2),
            "quoted_eur": self.quoted_eur,
            "ratio": round(self.ratio, 3),
            "band": self.band,
        }


@dataclass
class Objection:
    reason: str
    p: float

    def to_dict(self) -> dict:
        return {"reason": self.reason, "p": self.p}


@dataclass
class SalesRisk:
    win_p: float | None
    win_why: dict
    objections: list[Objection]
    quote_history: int         # comparable quotes the numbers rest on

    def to_dict(self) -> dict:
        return {
            "win_p": self.win_p,
            "win_why": self.win_why,
            "objections": [o.to_dict() for o in self.objections],
            "quote_history": self.quote_history,
        }


@dataclass
class Estimate:
    """What comparable work actually cost, took, and needed."""
    cost_eur: float | None
    duration_days: int | None
    team_size: int | None
    comparable_count: int            # exact matches for the whole shape
    neighbour_count: int             # deliveries the estimate is made of
    quoted_vs_actual: float | None   # historical actual / quoted ratio

    def to_dict(self) -> dict:
        return {
            "cost_eur": round(self.cost_eur, 2) if self.cost_eur else None,
            "duration_days": self.duration_days,
            "team_size": self.team_size,
            "comparable_count": self.comparable_count,
            "neighbour_count": self.neighbour_count,
            "quoted_vs_actual": (round(self.quoted_vs_actual, 3)
                                 if self.quoted_vs_actual else None),
        }


@dataclass
class TeamShape:
    """What comparable work was staffed with, before anyone is named."""
    suggested_size: int | None
    size_p: float | None

    def to_dict(self) -> dict:
        return {"suggested_size": self.suggested_size, "size_p": self.size_p}


# The changes a delivery lead can actually make to a proposal before
# signing it. Deliberately not "hire someone" or "charge less" — these
# are the three dials that exist inside the room where the plan is
# argued about.
LEVERS = [
    # The commercial ones first, because they move the most and they are
    # the ones argued about before signing. `set` replaces a field,
    # `add` shifts a number.
    ("Nail the scope down", {"scope_clarity": ("set", "clear")}),
    ("Time & materials", {"contract_type": ("set", "time_and_materials")}),
    ("Cap it instead", {"contract_type": ("set", "capped")}),
    ("Senior-heavy crew", {"team_seniority": ("set", "senior_heavy")}),
    ("Proven stack", {"novelty": ("set", "proven")}),
    ("Three weeks longer", {"duration_days": ("add", 21)}),
    ("One more person", {"team_size": ("add", 1)}),
]

# Which outcomes a lever is reported against. Not all six: a lever
# panel that moves six numbers each is a wall, and these are the three
# a lead trades between.
LEVER_OUTCOMES = [
    ("financial_ok", "Makes money"),
    ("on_time", "Lands when we said"),
    ("customer_happy", "Customer happy"),
]


@dataclass
class LeverEffect:
    label: str
    detail: str
    deltas: list[dict]          # {field, label, before, after, delta}

    def to_dict(self) -> dict:
        return {"label": self.label, "detail": self.detail,
                "deltas": self.deltas}


@dataclass
class EngagementPlan:
    customer: str
    scope: str
    project_type: str
    quoted_eur: float
    duration_days: int
    team_size: int
    priority: str
    site: str
    technology: str
    domain: str
    contract_type: str
    scope_clarity: str
    novelty: str
    customer_size: str
    team_seniority: str
    required_skills: str
    seniority: str
    local_only: bool
    start_month: str
    window_months: int
    shape: TeamShape
    levers: list[LeverEffect]
    roles: list[RoleSlot]
    delivery: DeliveryRisk
    price: PriceCheck | None
    sales: SalesRisk | None

    def to_dict(self) -> dict:
        return {
            "customer": self.customer,
            "scope": self.scope,
            "project_type": self.project_type,
            "quoted_eur": self.quoted_eur,
            "duration_days": self.duration_days,
            "team_size": self.team_size,
            "priority": self.priority,
            "site": self.site,
            "technology": self.technology,
            "domain": self.domain,
            "contract_type": self.contract_type,
            "scope_clarity": self.scope_clarity,
            "novelty": self.novelty,
            "customer_size": self.customer_size,
            "team_seniority": self.team_seniority,
            "required_skills": self.required_skills,
            "seniority": self.seniority,
            "local_only": self.local_only,
            "start_month": self.start_month,
            "window_months": self.window_months,
            "shape": self.shape.to_dict(),
            "levers": [l.to_dict() for l in self.levers],
            "roles": [r.to_dict() for r in self.roles],
            "delivery": self.delivery.to_dict(),
            "price": self.price.to_dict() if self.price else None,
            "sales": self.sales.to_dict() if self.sales else None,
        }


# Proposals worth opening the screen on. A planner that starts empty
# asks a visitor to invent a project before it can show them anything,
# and the interesting cases — the fixed-price-on-an-unclear-scope one,
# the new-stack one where the team is delighted and the margin is not —
# are exactly the ones nobody types by accident.
#
# Each is a full proposal, so loading one and pressing Plan it is the
# whole demo path.
PLANNER_EXAMPLES: dict[str, list[dict]] = {
    "studio": [
        {
            "name": "The one that eats the margin",
            "note": "fixed price on a scope nobody has pinned down",
            "customer": "City of Tampere", "project_type": "implementation",
            "scope": "Citizen portal rebuild, scope still moving",
            "quoted_eur": 165000, "duration_days": 150,
            "contract_type": "fixed_price", "scope_clarity": "unclear",
            "novelty": "some_new", "customer_size": "mid",
            "team_seniority": "mixed",
        },
        {
            "name": "Happy team, unhappy CFO",
            "note": "a stack nobody has shipped before",
            "customer": "Fortum", "project_type": "implementation",
            "scope": "Event-driven data platform on a new stack",
            "quoted_eur": 140000, "duration_days": 120,
            "contract_type": "fixed_price", "scope_clarity": "evolving",
            "novelty": "new_stack", "customer_size": "enterprise",
            "team_seniority": "mixed",
        },
        {
            "name": "The healthy one",
            "note": "time & materials, clear scope, senior crew",
            "customer": "Telia Finland", "project_type": "implementation",
            "scope": "Customer portal rebuild",
            "quoted_eur": 120000, "duration_days": 120,
            "contract_type": "time_and_materials", "scope_clarity": "clear",
            "novelty": "proven", "customer_size": "enterprise",
            "team_seniority": "senior_heavy",
        },
        {
            "name": "Small client, small job",
            "note": "where the follow-on work does not come from",
            "customer": "Framery", "project_type": "design",
            "scope": "Brand identity refresh",
            "quoted_eur": 38000, "duration_days": 45,
            "contract_type": "fixed_price", "scope_clarity": "clear",
            "novelty": "proven", "customer_size": "small",
            "team_seniority": "mixed",
        },
    ],
    "metsa": [
        {
            "name": "Fixed price on a survey nobody finished",
            "note": "the classic construction overrun",
            "customer": "City of Tampere", "project_type": "construction",
            "scope": "Assembly hall foundation and frame",
            "quoted_eur": 240000, "duration_days": 180,
            "contract_type": "fixed_price", "scope_clarity": "unclear",
            "novelty": "proven", "customer_size": "mid",
            "team_seniority": "mixed",
        },
        {
            "name": "Routine maintenance contract",
            "note": "the work that pays the bills",
            "customer": "Wärtsilä Oy", "project_type": "maintenance",
            "scope": "Annual service contract, two shifts",
            "quoted_eur": 38000, "duration_days": 60,
            "contract_type": "capped", "scope_clarity": "clear",
            "novelty": "proven", "customer_size": "enterprise",
            "team_seniority": "senior_heavy",
        },
        {
            "name": "New telematics, new everything",
            "note": "unfamiliar kit across three sites",
            "customer": "Internal — Production", "project_type": "rollout",
            "scope": "Fleet telematics rollout across three sites",
            "quoted_eur": 95000, "duration_days": 120,
            "contract_type": "fixed_price", "scope_clarity": "evolving",
            "novelty": "new_stack", "customer_size": "enterprise",
            "team_seniority": "junior_heavy",
        },
    ],
}


def planner_options(client: AitoClient, tenant: str = "") -> dict:
    """The project types and customers this tenant has history for.

    The form offers these rather than free text: a customer Aito has
    never seen contributes nothing to `_predict won`, and a planner
    that silently degrades to the base rate looks the same on screen as
    one that is answering the question.
    """
    try:
        response = client.search("projects", {}, limit=500)
    except AitoError:
        return {"project_types": [], "customers_by_type": {},
                "sites": [], "site_by_customer": {},
                "roles": [], "seniorities": [], "examples": [],
                "technologies_by_type": {}, "domain_by_customer": {},
                "drivers": {},
                "domains": []}

    hits = response.get("hits") or []
    customers: dict[str, set[str]] = {}
    sites: set[str] = set()
    # Which site a customer's work usually runs at, so selecting the
    # customer pre-fills the site the way it would in a real CRM.
    site_by_customer: dict[str, str] = {}
    for hit in hits:
        ptype = hit.get("project_type")
        customer = hit.get("customer")
        site = hit.get("site")
        if ptype and customer:
            customers.setdefault(ptype, set()).add(customer)
        if site:
            sites.add(site)
            if customer:
                site_by_customer.setdefault(customer, site)
    # The role vocabulary and the sites people are actually based at,
    # read off `people` — the form should offer what exists, not what a
    # constant in this file guesses.
    # The driver vocabularies, read off the data so the form offers what
    # the history actually contains.
    driver_fields = ("contract_type", "scope_clarity", "novelty",
                     "customer_size", "team_seniority")
    drivers: dict[str, list[str]] = {f: [] for f in driver_fields}
    seen: dict[str, set[str]] = {f: set() for f in driver_fields}

    technologies: dict[str, set[str]] = {}
    domains_by_customer: dict[str, str] = {}
    for hit in hits:
        for field_name in driver_fields:
            value = hit.get(field_name)
            if value:
                seen[field_name].add(str(value))
        if hit.get("project_type") and hit.get("technology"):
            technologies.setdefault(hit["project_type"], set()).add(
                hit["technology"])
        if hit.get("customer") and hit.get("domain"):
            domains_by_customer.setdefault(hit["customer"], hit["domain"])

    drivers = {f: sorted(v) for f, v in seen.items()}

    disciplines: set[str] = set()
    person_sites: set[str] = set()
    seniorities: set[str] = set()
    try:
        for row in client.search("people", {}, limit=500).get("hits") or []:
            if row.get("discipline"):
                disciplines.add(row["discipline"])
            if row.get("site"):
                person_sites.add(row["site"])
            if row.get("seniority"):
                seniorities.add(row["seniority"])
    except AitoError:
        pass

    return {
        "project_types": sorted(customers),
        "customers_by_type": {k: sorted(v) for k, v in customers.items()},
        "sites": sorted(sites | person_sites),
        "site_by_customer": site_by_customer,
        "roles": sorted(disciplines),
        "seniorities": sorted(seniorities),
        "technologies_by_type": {k: sorted(v) for k, v in technologies.items()},
        "drivers": drivers,
        "examples": PLANNER_EXAMPLES.get(tenant, []),
        "domain_by_customer": domains_by_customer,
        "domains": sorted(set(domains_by_customer.values())),
    }


# The linked `people` columns to pull back alongside the ranking. Named
# explicitly because naming any `select` replaces Aito's default of
# returning the whole linked row.
PERSON_FIELDS = ["title", "discipline", "skills", "certifications",
                 "domains", "site", "seniority", "years_experience"]


def _hits(client: AitoClient, table: str, where: dict,
          predict_field: str, limit: int = 6,
          select_extra: list[str] | None = None) -> list[dict]:
    """`_predict`, tolerating a table this tenant doesn't carry.

    `quotes` is optional per persona (see data_loader.OPTIONAL_TABLES),
    so the planner degrades to "no sales read" rather than 500ing on a
    tenant that only has delivery data.
    """
    try:
        response = client.predict(table, where, predict_field, limit=limit,
                                  select_extra=select_extra)
    except AitoError:
        return []
    return response.get("hits") or []


def _p_of(hits: list[dict], value) -> tuple[float | None, dict]:
    """Probability and $why for one candidate value, or (None, {})."""
    for hit in hits:
        if hit.get("$value") == value or str(hit.get("$value")) == str(value):
            p = float(hit.get("$p", 0.0))
            return p, process_factors(hit.get("$why") or {}, p)
    return None, {}


def _band_for(ratio: float) -> str:
    for ceiling, name in PRICE_BANDS:
        if ratio < ceiling:
            return name
    return PRICE_BANDS[-1][1]


def _role_caps(client: AitoClient) -> dict[str, int]:
    """The most of each role that ever appeared on ONE project.

    `_predict role` returns a share of all assignments, and scaling a
    share to a big team happily asks for two project managers on eight
    people — which is not what the history says, it is what an
    unbounded proportion says. A role that has never appeared twice on
    one project is a singleton, and the data knows that without anyone
    writing down which roles are "management".
    """
    try:
        rows = client.search("assignments", {}, limit=4000).get("hits") or []
    except AitoError:
        return {}
    per_project: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row.get("project_id"), row.get("role"))
        if key[0] and key[1]:
            per_project[key] = per_project.get(key, 0) + 1
    caps: dict[str, int] = {}
    for (_, role), count in per_project.items():
        caps[role] = max(caps.get(role, 0), count)
    return caps


def _role_slots(client: AitoClient, project_type: str,
                team_size: int,
                caps: dict[str, int] | None = None) -> list[tuple[str, int, float]]:
    """The historical role mix for this kind of work, scaled to the team.

    Largest-remainder allocation, so the counts sum to exactly
    `team_size` instead of drifting by a head or two after rounding —
    a planner that asks for six people and staffs five is worse than
    useless.
    """
    hits = _hits(client, "assignments", {"project_type": project_type},
                 "role", limit=8)
    mix = [(str(h["$value"]), float(h.get("$p", 0.0))) for h in hits
           if h.get("$value") is not None]
    if not mix:
        return []

    caps = caps or {}
    total = sum(p for _, p in mix) or 1.0
    exact = [(role, p / total * team_size) for role, p in mix]
    counts = {role: min(int(value), caps.get(role, team_size))
              for role, value in exact}
    shortfall = team_size - sum(counts.values())
    # Largest remainder, but never past what the history ever staffed.
    # Rounds are repeated because capping one role hands its seat back
    # to the others.
    for _ in range(team_size + 1):
        if shortfall <= 0:
            break
        placed = False
        for role, value in sorted(exact, key=lambda rv: -(rv[1] % 1)):
            if shortfall <= 0:
                break
            if counts[role] >= caps.get(role, team_size):
                continue
            counts[role] += 1
            shortfall -= 1
            placed = True
        if not placed:
            break

    shares = dict(mix)
    return [(role, counts[role], shares[role] / total)
            for role, _ in mix if counts.get(role, 0) > 0]


def plan_engagement(
    client: AitoClient,
    *,
    customer: str,
    scope: str,
    project_type: str,
    quoted_eur: float,
    duration_days: int,
    # 0 means "you tell me" — the size is part of what is being
    # planned, not something a delivery lead should have to know before
    # asking. `_predict projects.team_size` answers it from comparable
    # work and the rest of the plan follows from the answer.
    team_size: int = 0,
    priority: str = "medium",
    site: str = "",
    start_month: str = "",
    technology: str = "",
    domain: str = "",
    contract_type: str = "",
    scope_clarity: str = "",
    novelty: str = "",
    customer_size: str = "",
    team_seniority: str = "",
    required_skills: str = "",
    seniority: str = "",
    local_only: bool = False,
    roles_override: list[dict] | None = None,
    competing_bid: bool = False,
    existing_customer: bool = True,
) -> EngagementPlan:
    """Everything the planner shows, for one proposed engagement."""
    # ── Price check, from comparable delivered work ──────────────
    # Done first because the price BAND it produces is an input to the
    # sales prediction — Aito reads "we quoted well over" far more
    # reliably than it reads a raw Decimal.
    shape = _suggest_team_size(client, project_type, duration_days, priority)
    if not team_size:
        team_size = shape.suggested_size or 4
    price = _price_check(client, project_type, team_size, quoted_eur)
    band = price.band if price else "at_market"

    # ── Staffing ────────────────────────────────────────────────
    # The project's own window: the months a candidate has to be free
    # across, not "now".
    start_month = start_month or month_label(_this_month())
    window_len = max(1, round(duration_days / 30.44))
    window = availability_in_window(client, start_month, window_len)
    phases = role_phases(client)
    all_months = window_months(start_month, window_len)
    loads = _current_loads(client)
    vocabulary = _skill_vocabulary(client)
    roles: list[RoleSlot] = []
    # An edited role list wins over the predicted mix. The prediction is
    # a starting point — a delivery lead who knows this job needs two
    # QA and no data engineer should not have to argue with it.
    mix: list[tuple[str, int, float, str, str]] = (
        [(r["role"], int(r["count"]), 0.0,
          str(r.get("skills") or ""), str(r.get("seniority") or ""))
         for r in roles_override]
        if roles_override else
        [(role, count, share, "", "")
         for role, count, share in _role_slots(client, project_type, team_size,
                                               _role_caps(client))])
    for role, count, share, role_skills, role_seniority in mix:
        # `assignments.person` is a link to `people.person`, so this one
        # call returns the ranking AND every column of the matched
        # person's row — title, skills, site, seniority. No second
        # lookup, and the metadata that justifies the match arrives with
        # the match itself.
        # Two kinds of clause here, and the difference matters.
        #
        # `project_type` / `role` / `site` describe the JOB, and they
        # are evidence: they say "work like this" and let Aito rank on
        # how such work was staffed before. Note `site` is the
        # PROJECT's site, denormalised onto the assignment.
        #
        # The `person.*` clauses are linked-field filters on the
        # CANDIDATE, and they are constraints: `person.site` is where
        # someone is based (not where the job is), `person.seniority`
        # and a `$match` over `person.skills` are properties of them.
        # Aito applies them in the query, so a filtered-out candidate
        # never reaches the shortlist rather than being ranked and then
        # dropped here.
        where: dict = {"project_type": project_type, "role": role}
        if site:
            where["site"] = site
        if technology:
            where["technology"] = technology
        if domain:
            where["domain"] = domain
        if local_only and site:
            where["person.site"] = site
        # Requirements are PER ROLE. "Must have Next.js" is a statement
        # about the frontend seat, and applying it to the QA and the
        # project manager — as a single proposal-wide filter did —
        # staffs those seats with frontend developers, because `role`
        # is evidence while `person.skills` is a hard filter. A
        # requirement that belongs to one seat has to travel with it.
        want_seniority = role_seniority or seniority
        want_skills = (role_skills or required_skills).strip()
        unknown_skills: list[str] = []
        if want_seniority:
            where["person.seniority"] = want_seniority
        if want_skills:
            # `skills` is a `String[]`, so membership is `$has` on the
            # whole skill — "UI design" matches people who have that
            # skill, not everyone with the word "design" somewhere.
            #
            # One clause per requirement under `$or`: requiring ALL of
            # them returns nobody once there are more than two or three,
            # and an empty shortlist is a worse answer than a ranked
            # one. Aito then ranks by how many a person actually has.
            #
            # Guarded on the RESOLVED terms, not on the raw string: an
            # input of "," is truthy and strips to nothing, which would
            # send `"$or": []` — an empty disjunction whose result
            # `_hits` swallows, leaving the seat unstaffed for a reason
            # nobody can see.
            wanted, unknown_skills = _resolve_skills(want_skills, vocabulary)
            if wanted:
                where["$or"] = [{"person.skills": {"$has": t}} for t in wanted]
        hits = _hits(client, "assignments", where, "person", limit=6,
                     select_extra=PERSON_FIELDS)
        # The months THIS seat occupies, from the historical phase of
        # the role. Availability is then asked about those months only.
        lo, hi = phases.get(role, (0.0, 1.0))
        first = min(int(len(all_months) * lo), len(all_months) - 1)
        last = max(first, min(int(len(all_months) * hi) - 1,
                              len(all_months) - 1))
        seat_months = all_months[first:last + 1] or all_months
        history = _history_counts(
            client, {"project_type": project_type, "role": role})
        candidates = []
        # The quality read is one Aito call per candidate, so fan the
        # shortlist out rather than paying for it six times in series.
        people_on_shortlist = [str(h.get("$value") or h.get("person"))
                               for h in hits]
        with ThreadPoolExecutor(max_workers=6) as pool:
            quality_results = dict(zip(people_on_shortlist, pool.map(
                lambda who: _quality_for(client, who, role, project_type),
                people_on_shortlist)))
        for hit in hits:
            person = str(hit.get("$value") or hit.get("person"))
            p = float(hit.get("$p", 0.0))
            load, status = loads.get(person, (0, "available"))
            standing = window.get(person) or WindowAvailability(
                person=person, booked_pct=0, peak_pct=0, free_pct=100)
            standing = restrict(standing, seat_months)
            candidate = Candidate(
                person=person,
                fit=p,
                current_load_pct=load,
                status=status,
                title=str(hit.get("title") or ""),
                discipline=str(hit.get("discipline") or ""),
                skills=_string_list(hit, "skills", person),
                certifications=str(hit.get("certifications") or ""),
                site=str(hit.get("site") or ""),
                seniority=str(hit.get("seniority") or ""),
                domains=_string_list(hit, "domains", person),
                years_experience=int(hit.get("years_experience") or 0),
                booked_pct=standing.booked_pct,
                free_pct=standing.free_pct,
                available=standing.available,
                absent_months=standing.absent_months,
                absence_kind=standing.absence_kind,
                contention=standing.contention,
                contention_pct=standing.contention_pct,
                quality_p=quality_results.get(person, (None, {}))[0],
                quality_why=quality_results.get(person, (None, {}))[1],
                history_count=history.get(person, 0),
                why=process_factors(hit.get("$why") or {}, p),
            )
            candidate.matches = _match_chips(
                candidate, role, site, technology, domain,
                _highlighted_fields(candidate.why))
            candidates.append(candidate)
        roles.append(RoleSlot(role=role, count=count, share=share,
                              skills=want_skills, seniority=want_seniority,
                              unknown_skills=unknown_skills,
                              from_month=seat_months[0],
                              to_month=seat_months[-1],
                              candidates=candidates))
    _fill_seats(roles)

    # ── Delivery risk ───────────────────────────────────────────
    # `budget_eur` is deliberately absent. It is a Decimal, and a
    # proposed quote is almost never a figure the history contains — so
    # it contributes no evidence and the prediction comes back
    # identical whether you propose 150k or 320k. Including it anyway
    # would put a field in the panel's query that changes nothing,
    # which teaches a reader of this demo the wrong thing about how
    # `_predict` weighs evidence. Price enters where it is actually
    # measurable: the sales read below, bucketed into a band.
    delivery_where = {
        "project_type": project_type,
        "team_size": team_size,
        "duration_days": duration_days,
        "priority": priority,
    }
    if site:
        delivery_where["site"] = site
    if technology:
        delivery_where["technology"] = technology
    if domain:
        delivery_where["domain"] = domain
    # The drivers a post-mortem actually turns up: fixed price on an
    # unclear scope, a new stack, a junior crew, a small customer. Each
    # moves the six outcomes DIFFERENTLY, which is what makes six
    # numbers worth showing instead of one.
    for key, value in (("contract_type", contract_type),
                       ("scope_clarity", scope_clarity),
                       ("novelty", novelty),
                       ("customer_size", customer_size),
                       ("team_seniority", team_seniority)):
        if value:
            delivery_where[key] = value
    success_p, success_why = _p_of(
        _hits(client, "projects", delivery_where, "success", limit=2), True)

    def outcomes(spec: list[tuple[str, str]]) -> list[Outcome]:
        out = []
        for field_name, label in spec:
            p, why = _p_of(
                _hits(client, "projects", delivery_where, field_name, limit=2),
                True)
            out.append(Outcome(field=field_name, label=label, p=p, why=why))
        return out

    core = outcomes(CORE_OUTCOMES)
    qualifying = outcomes(QUALIFYING_OUTCOMES)
    delivery = DeliveryRisk(
        success_p=success_p,
        core=core,
        qualifying=qualifying,
        success_why=success_why,
    )
    baseline = {o.field: o.p for o in core + qualifying}
    levers = _levers(client, delivery_where, baseline)

    sales = _sales_risk(client, customer=customer, project_type=project_type,
                        band=band, duration_days=duration_days,
                        team_size=team_size, priority=priority,
                        competing_bid=competing_bid,
                        existing_customer=existing_customer)

    return EngagementPlan(
        customer=customer,
        scope=scope,
        project_type=project_type,
        quoted_eur=quoted_eur,
        duration_days=duration_days,
        team_size=team_size,
        priority=priority,
        site=site,
        technology=technology,
        domain=domain,
        contract_type=contract_type,
        scope_clarity=scope_clarity,
        novelty=novelty,
        customer_size=customer_size,
        team_seniority=team_seniority,
        required_skills=required_skills,
        seniority=seniority,
        local_only=local_only,
        start_month=start_month,
        window_months=window_len,
        shape=shape,
        levers=levers,
        roles=roles,
        delivery=delivery,
        price=price,
        sales=sales,
    )


def _fill_seats(slots: list[RoleSlot]) -> None:
    """Name one person per seat, across the whole team at once.

    Aito ranks candidates per role. It does not allocate a team, and it
    should not be asked to: "who fits this role" is an inference, "who
    gets which seat given everyone else's seat" is an assignment
    problem, and pretending the second falls out of the first is how you
    end up with the same person booked into three roles.

    So this is a plain greedy pass over Aito's ranking with two rules a
    scheduler would apply by hand:

      * nobody takes two seats on the same project;
      * a candidate who is not free across the project's window is
        skipped while any free candidate remains — booked over, or on
        leave for part of it. The best fit is not an answer if they are
        on parental leave for the build.

    Both are visible in the UI — the dropdown still offers everyone, in
    Aito's order, so overriding this is one click.
    """
    taken: set[str] = set()
    for slot in slots:
        for _ in range(slot.count):
            free = [c for c in slot.candidates if c.person not in taken]
            if not free:
                slot.assignees.append("")
                continue
            # `available` is now window-aware: free enough across the
            # project's own months, and not on leave during any of them.
            available = [c for c in free if c.available]
            # Among available candidates, prefer the one fewest other
            # open bids are counting on. Aito's order is preserved
            # within a contention level, so this breaks ties rather
            # than re-ranking.
            available.sort(key=lambda c: c.contention)
            pick = (available or free)[0]
            taken.add(pick.person)
            slot.assignees.append(pick.person)


def _suggest_team_size(client: AitoClient, project_type: str,
                       duration_days: int, priority: str) -> TeamShape:
    """How big comparable work was staffed — `_predict team_size`.

    `team_size` is an Int column on `projects`, so it is predictable
    exactly like any other field. Deliberately conditioned on shape
    (type, duration, priority) and not on budget: an unseen Decimal
    contributes nothing (see the delivery-risk note below).
    """
    hits = _hits(client, "projects",
                 {"project_type": project_type,
                  "duration_days": duration_days,
                  "priority": priority},
                 "team_size", limit=4)
    if not hits:
        return TeamShape(suggested_size=None, size_p=None)
    top = hits[0]
    try:
        size = int(top.get("$value"))
    except (TypeError, ValueError):
        return TeamShape(suggested_size=None, size_p=None)
    return TeamShape(suggested_size=size, size_p=float(top.get("$p", 0.0)))


def _this_month() -> int:
    from datetime import date

    today = date.today()
    return month_index(f"{today.year}-{today.month:02d}")


def _string_list(hit: dict, field_name: str, person: str) -> list[str]:
    """Read a `String[]` column, refusing anything that is not one.

    `list()` would accept a string and hand back its CHARACTERS —
    `list("React Node")` is `['R', 'e', 'a', 'c', 't', ...]` — so a
    tenant still holding the old whitespace-joined `Text` column would
    render single-letter chips and a panel reading "Skills on record:
    R, e, a, c, t". That is the silent coercion this project forbids:
    plausible-looking output hiding a half-finished reload. The reload
    is a separate manual step per environment, so it WILL happen to
    someone.
    """
    value = hit.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise AitoError(
            f"{field_name!r} for {person!r} came back as "
            f"{type(value).__name__}, not a list. This tenant's `people` "
            f"table predates the String[] schema — re-run "
            f"`./do generate-personas` then `./do load-data --reset`."
        )
    return [str(v) for v in value]


def _resolve_skills(raw: str,
                    vocabulary: dict[str, str]) -> tuple[list[str], list[str]]:
    """Map typed skill names onto the ones this tenant actually has.

    Returns `(resolved, unknown)`, comma-separated and case-insensitive.

    `$has` on a `String[]` is EXACT, where the old `$match` on a Text
    column ran the analyzer and case-folded — so a typed "react" now
    matches nobody, `_hits` swallows the empty response, and the seat
    comes back unstaffed with nothing saying the filter caused it.
    Resolving against the real vocabulary fixes the common case; an
    unresolved term is handed back so the caller can say "we have
    nobody with that" instead of quietly showing an empty list.
    """
    resolved: list[str] = []
    unknown: list[str] = []
    for term in (t.strip() for t in raw.split(",")):
        if not term:
            continue
        canonical = vocabulary.get(term.lower())
        (resolved if canonical else unknown).append(canonical or term)
    return resolved, unknown


def _skill_vocabulary(client: AitoClient) -> dict[str, str]:
    """`lowercased skill -> canonical skill`, from this tenant's bench."""
    try:
        rows = client.search("people", {}, limit=500).get("hits") or []
    except AitoError:
        return {}
    vocabulary: dict[str, str] = {}
    for row in rows:
        for skill in row.get("skills") or []:
            vocabulary.setdefault(str(skill).lower(), str(skill))
    return vocabulary


def _match_chips(candidate: Candidate, role: str, site: str,
                 technology: str, domain: str,
                 highlighted: set[str]) -> list[dict]:
    """The candidate's own attributes, each marked with WHY it is shown.

    Three different claims, and conflating them was the problem:

      `aito`  — Aito's `$why` named this field as evidence behind the
                ranking. The strongest label, and the only one that
                says the database used it.
      `match` — this attribute coincides with something the proposal
                asked for. Client-side string comparison, honest but
                not inference.
      `fact`  — context. True, useful to read, argued nothing.

    They are returned as structured chips rather than strings so the UI
    can show the difference instead of implying they are all the same
    kind of reason.
    """
    def chip(label: str, kind: str, field: str = "") -> dict:
        # Aito's own evidence outranks a client-side coincidence.
        if field and field in highlighted:
            kind = "aito"
        return {"label": label, "kind": kind, "field": field}

    chips: list[dict] = []
    if candidate.title:
        chips.append(chip(candidate.title, "fact"))
    if candidate.discipline and candidate.discipline == role:
        chips.append(chip(f"does {role} work", "match", "role"))
    elif candidate.discipline:
        # Off-discipline, and worth saying out loud rather than leaving
        # the reader to notice the title. Narrowing the context far
        # enough (type + role + site + stack + sector) thins the matching
        # history until people who once covered a seat outrank the ones
        # who normally fill it — and `went_well` says working outside
        # your discipline is the single biggest drag on how it goes.
        chips.append({"label": f"not usually {role}", "kind": "warn",
                      "field": "role"})
    if site and candidate.site == site:
        chips.append(chip(f"based in {site}", "match", "site"))
    elif candidate.site:
        chips.append(chip(f"{candidate.site} — would travel", "fact", "site"))

    # `technology` is one term ("research"); a skill may be several
    # ("user research"). Equality alone stopped chipping those, so the
    # test is equality OR the technology appearing as a word of it.
    wanted = technology.lower()
    for skill in candidate.skills[:5]:
        lowered = skill.lower()
        hit_tech = bool(wanted) and (lowered == wanted
                                     or wanted in lowered.split())
        chips.append(chip(skill, "match" if hit_tech else "fact",
                          "technology" if hit_tech else ""))
    if domain and domain in candidate.domains:
        chips.append(chip(f"{domain} experience", "match", "domain"))
    if candidate.certifications:
        chips.append(chip(candidate.certifications.split(",")[0].strip(), "fact"))
    if candidate.years_experience:
        chips.append(chip(f"{candidate.years_experience}y", "fact"))
    return chips


def _highlighted_fields(why: dict) -> set[str]:
    """Which context fields Aito's `$why` actually named.

    `why_processor` has already flattened the tree; each lift carries
    the fields it highlighted as `$context.<field>`. Those are the
    chips that get to claim the database backed them.
    """
    fields: set[str] = set()
    for lift in (why or {}).get("lifts", []) or []:
        for hl in lift.get("highlights", []) or []:
            raw = str(hl.get("raw_field") or hl.get("field") or "")
            fields.add(raw.replace("$context.", ""))
    return fields


def _history_counts(client: AitoClient, where: dict) -> dict[str, int]:
    """`person → how many assignments of this kind they have`.

    One `_search`, counted here. `$f` would do it server-side but it is
    not available on v1 — it fails with `None.get`, the same unhandled
    Option family as the `_estimate` nullable bug (aito-core #1253).
    """
    try:
        rows = client.search("assignments", where, limit=1000).get("hits") or []
    except AitoError:
        return {}
    counts: dict[str, int] = {}
    for row in rows:
        person = row.get("person")
        if person:
            counts[person] = counts.get(person, 0) + 1
    return counts


def _quality_for(client: AitoClient, person: str, role: str,
                 project_type: str) -> tuple[float | None, dict]:
    """P(this person's work in this seat went well), with its drivers.

    `_predict went_well` with the PERSON in the where. The earlier
    version asked `_recommend ... goal={went_well: true}` once per role,
    which was cheaper and nearly useless: it came back 0.73-0.83 across
    every candidate while the underlying per-person rates run 10% to
    87%. Goal-ranking smooths across the candidate set; asking about one
    person at a time does not.

    One call per candidate, so the shortlist is fanned out in parallel.
    """
    where = {"person": person, "role": role, "project_type": project_type}
    hits = _hits(client, "assignments", where, "went_well", limit=2)
    return _p_of(hits, True)


def _levers(client: AitoClient, base_where: dict,
            baseline: dict[str, float | None]) -> list[LeverEffect]:
    """What each available change does to the outcomes.

    Six probabilities describe a risk; none of them says what to do
    about it. A lever re-runs the same `_predict` calls against an
    altered context and reports the difference, which is the form a
    delivery lead can act on: "three weeks buys eleven points of
    on-time" is a decision, "on-time is 55%" is a fact.

    Nothing here is a new query shape — it is the outcome predict from
    above, asked again about a project that differs in one field.
    """
    effects: list[LeverEffect] = []
    for label, change in LEVERS:
        where = dict(base_where)
        detail_bits = []
        for key, (op, value) in change.items():
            current = where.get(key)
            if op == "add":
                if not isinstance(current, (int, float)):
                    continue
                where[key] = max(1, int(current) + value)
            else:
                # A lever that changes nothing is not a lever. Skipping
                # it beats reporting a row of zeroes that implies the
                # option was tried and found not to matter.
                if current == value or current is None:
                    continue
                where[key] = value
            detail_bits.append(f"{key} {current} → {where[key]}")
        if not detail_bits:
            continue

        deltas = []
        for field_name, out_label in LEVER_OUTCOMES:
            before = baseline.get(field_name)
            after, _ = _p_of(
                _hits(client, "projects", where, field_name, limit=2), True)
            if before is None or after is None:
                continue
            deltas.append({
                "field": field_name, "label": out_label,
                "before": round(before, 4), "after": round(after, 4),
                "delta": round(after - before, 4),
            })
        if deltas:
            effects.append(LeverEffect(label=label,
                                       detail=", ".join(detail_bits),
                                       deltas=deltas))
    return effects


def _current_loads(client: AitoClient) -> dict[str, tuple[int, str]]:
    """person → (current allocation %, status), from the capacity view.

    Reuses `utilization_service` rather than re-deriving the same
    aggregation, so "overloaded" means the same thing on both screens.
    """
    try:
        overview = get_utilization(client)
    except AitoError:
        return {}
    return {row.person: (row.current_allocation_pct, row.status)
            for row in overview.rows}


def estimate_effort(client: AitoClient, *, project_type: str,
                    scope_clarity: str = "", contract_type: str = "",
                    novelty: str = "", customer_size: str = "",
                    technology: str = "", domain: str = "") -> Estimate:
    """What work of this shape actually cost, took and needed.

    Estimated from **actuals**, never from what was quoted. A quote is
    what someone hoped it would cost before they started; estimating
    the next one from a pile of those reproduces the same optimism and
    calls it evidence. `actual_cost_eur` and `actual_duration_days` are
    the only honest inputs, and the gap between them and `budget_eur`
    is itself worth reporting — this organisation historically delivers
    at 1.17× what it sold.

    `_estimate` rather than an average: its `why` is a weighted average
    over neighbouring rows, so the number arrives with the comparable
    projects that produced it.
    """
    # `deliveries`, not `projects`: finished work only, and every
    # numeric column non-nullable so `_estimate` can read it.
    where: dict = {"project_type": project_type}
    for key, value in (("scope_clarity", scope_clarity),
                       ("contract_type", contract_type),
                       ("novelty", novelty),
                       ("customer_size", customer_size),
                       ("technology", technology),
                       ("domain", domain)):
        if value:
            where[key] = value

    neighbours = 0

    def number(field_name: str) -> float | None:
        """The estimate, and how many past deliveries went into it.

        `_estimate` is neighbour-weighted, so it answers even when
        nothing matches the whole shape exactly — which is a feature,
        but it means an exact-match count of 0 sitting beside a
        confident number reads as nonsense. The `why` is a weighted
        average whose components ARE the comparable deliveries, so
        counting them says what the estimate is actually made of.
        """
        nonlocal neighbours
        try:
            response = client.estimate("deliveries", where, field_name)
        except AitoError:
            return None
        why = response.get("why") or {}
        neighbours = max(neighbours, len(why.get("components") or []))
        value = response.get("estimate")
        return float(value) if isinstance(value, (int, float)) else None

    cost = number("actual_cost_eur")
    duration = number("actual_duration_days")
    quoted = number("quoted_eur")

    team_hits = _hits(client, "deliveries", where, "team_size", limit=3)
    team = None
    if team_hits:
        try:
            team = int(team_hits[0].get("$value"))
        except (TypeError, ValueError):
            team = None

    try:
        comparable = client.search("deliveries", where, limit=0).get("total", 0)
    except AitoError:
        comparable = 0

    return Estimate(
        cost_eur=cost,
        duration_days=int(duration) if duration else None,
        team_size=team,
        comparable_count=comparable,
        neighbour_count=neighbours,
        quoted_vs_actual=(cost / quoted) if (cost and quoted) else None,
    )


def _price_check(client: AitoClient, project_type: str, team_size: int,
                 quoted_eur: float) -> PriceCheck | None:
    """Where this quote sits against comparable delivered projects.

    Comparables are completed projects of the same type within one head
    of the proposed team size. Falls back to the type alone if that is
    too thin to say anything — and returns None rather than inventing a
    band when even that has no history.
    """
    def budgets(where: dict) -> list[float]:
        try:
            response = client.search("projects", where, limit=400)
        except AitoError:
            return []
        return [float(h["budget_eur"]) for h in response.get("hits") or []
                if h.get("status") == "complete" and h.get("budget_eur")]

    values = [b for b in budgets({"project_type": project_type})]
    sized = [b for b in budgets({"project_type": project_type,
                                 "team_size": team_size})]
    # Prefer the tighter comparable set, but only when it is big enough
    # for a quartile to mean anything.
    if len(sized) >= 8:
        values = sized
    if len(values) < 4:
        return None

    values.sort()
    mid = median(values)
    low = values[len(values) // 4]
    high = values[(len(values) * 3) // 4]
    ratio = quoted_eur / mid if mid else 1.0
    return PriceCheck(
        comparable_count=len(values),
        median_eur=mid,
        low_eur=low,
        high_eur=high,
        quoted_eur=quoted_eur,
        ratio=ratio,
        band=_band_for(ratio),
    )


def _sales_risk(client: AitoClient, *, customer: str, project_type: str,
                band: str, duration_days: int, team_size: int,
                priority: str, competing_bid: bool,
                existing_customer: bool) -> SalesRisk | None:
    """P(win) and the objection ranking, from the quote history.

    The customer name is deliberately in the where clause: accounts
    differ in how much price they tolerate, and that is exactly the
    kind of thing a salesperson knows for their own accounts and
    nobody knows across all of them.
    """
    where = {
        "customer": customer,
        "project_type": project_type,
        "price_band": band,
        "duration_days": duration_days,
        "team_size": team_size,
        "priority": priority,
        "competing_bid": competing_bid,
        "existing_customer": existing_customer,
    }
    win_hits = _hits(client, "quotes", where, "won", limit=2)
    if not win_hits:
        return None
    win_p, win_why = _p_of(win_hits, True)

    # Objections are conditioned on the deal being lost. Without
    # `won: False` the ranking is dominated by the empty reason every
    # won quote carries, and every objection reads as unlikely.
    objection_hits = _hits(client, "quotes", {**where, "won": False},
                           "loss_reason", limit=5)
    objections = [
        Objection(reason=str(h["$value"]), p=float(h.get("$p", 0.0)))
        for h in objection_hits
        if h.get("$value") not in (None, "", "null")
    ]

    try:
        history = client.search(
            "quotes", {"project_type": project_type}, limit=0,
        ).get("total", 0)
    except AitoError:
        history = 0

    return SalesRisk(win_p=win_p, win_why=win_why,
                     objections=objections, quote_history=history)

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

from dataclasses import dataclass, field
from statistics import median

from src.aito_client import AitoClient, AitoError
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
    skills: str = ""
    certifications: str = ""
    site: str = ""
    seniority: str = ""
    years_experience: int = 0
    matches: list[str] = field(default_factory=list)
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
            "years_experience": self.years_experience,
            "matches": self.matches,
            "why": self.why,
        }


@dataclass
class RoleSlot:
    role: str
    count: int                 # how many of this role the mix implies
    share: float               # P(role) in comparable history
    candidates: list[Candidate]

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "count": self.count,
            "share": self.share,
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass
class DeliveryRisk:
    success_p: float | None
    on_time_p: float | None
    on_budget_p: float | None
    success_why: dict = field(default_factory=dict)
    on_time_why: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success_p": self.success_p,
            "on_time_p": self.on_time_p,
            "on_budget_p": self.on_budget_p,
            "success_why": self.success_why,
            "on_time_why": self.on_time_why,
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
class EngagementPlan:
    customer: str
    scope: str
    project_type: str
    quoted_eur: float
    duration_days: int
    team_size: int
    priority: str
    site: str
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
            "roles": [r.to_dict() for r in self.roles],
            "delivery": self.delivery.to_dict(),
            "price": self.price.to_dict() if self.price else None,
            "sales": self.sales.to_dict() if self.sales else None,
        }


def planner_options(client: AitoClient) -> dict:
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
                "sites": [], "site_by_customer": {}}

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
    return {
        "project_types": sorted(customers),
        "customers_by_type": {k: sorted(v) for k, v in customers.items()},
        "sites": sorted(sites),
        "site_by_customer": site_by_customer,
    }


# The linked `people` columns to pull back alongside the ranking. Named
# explicitly because naming any `select` replaces Aito's default of
# returning the whole linked row.
PERSON_FIELDS = ["title", "discipline", "skills", "certifications",
                 "site", "seniority", "years_experience"]


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


def _role_slots(client: AitoClient, project_type: str,
                team_size: int) -> list[tuple[str, int, float]]:
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

    total = sum(p for _, p in mix) or 1.0
    exact = [(role, p / total * team_size) for role, p in mix]
    counts = {role: int(value) for role, value in exact}
    shortfall = team_size - sum(counts.values())
    for role, value in sorted(exact, key=lambda rv: -(rv[1] % 1)):
        if shortfall <= 0:
            break
        counts[role] += 1
        shortfall -= 1

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
    team_size: int,
    priority: str = "medium",
    site: str = "",
    competing_bid: bool = False,
    existing_customer: bool = True,
) -> EngagementPlan:
    """Everything the planner shows, for one proposed engagement."""
    # ── Price check, from comparable delivered work ──────────────
    # Done first because the price BAND it produces is an input to the
    # sales prediction — Aito reads "we quoted well over" far more
    # reliably than it reads a raw Decimal.
    price = _price_check(client, project_type, team_size, quoted_eur)
    band = price.band if price else "at_market"

    # ── Staffing ────────────────────────────────────────────────
    loads = _current_loads(client)
    roles: list[RoleSlot] = []
    for role, count, share in _role_slots(client, project_type, team_size):
        # `assignments.person` is a link to `people.person`, so this one
        # call returns the ranking AND every column of the matched
        # person's row — title, skills, site, seniority. No second
        # lookup, and the metadata that justifies the match arrives with
        # the match itself.
        where = {"project_type": project_type, "role": role}
        if site:
            where["site"] = site
        hits = _hits(client, "assignments", where, "person", limit=6,
                     select_extra=PERSON_FIELDS)
        candidates = []
        for hit in hits:
            person = str(hit.get("$value") or hit.get("person"))
            p = float(hit.get("$p", 0.0))
            load, status = loads.get(person, (0, "available"))
            candidate = Candidate(
                person=person,
                fit=p,
                current_load_pct=load,
                status=status,
                title=str(hit.get("title") or ""),
                discipline=str(hit.get("discipline") or ""),
                skills=str(hit.get("skills") or ""),
                certifications=str(hit.get("certifications") or ""),
                site=str(hit.get("site") or ""),
                seniority=str(hit.get("seniority") or ""),
                years_experience=int(hit.get("years_experience") or 0),
                why=process_factors(hit.get("$why") or {}, p),
            )
            candidate.matches = _match_chips(candidate, role, site)
            candidates.append(candidate)
        roles.append(RoleSlot(role=role, count=count, share=share,
                              candidates=candidates))

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
    success_p, success_why = _p_of(
        _hits(client, "projects", delivery_where, "success", limit=2), True)
    on_time_p, on_time_why = _p_of(
        _hits(client, "projects", delivery_where, "on_time", limit=2), True)
    on_budget_p, _ = _p_of(
        _hits(client, "projects", delivery_where, "on_budget", limit=2), True)
    delivery = DeliveryRisk(
        success_p=success_p,
        on_time_p=on_time_p,
        on_budget_p=on_budget_p,
        success_why=success_why,
        on_time_why=on_time_why,
    )

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
        roles=roles,
        delivery=delivery,
        price=price,
        sales=sales,
    )


def _match_chips(candidate: Candidate, role: str, site: str) -> list[str]:
    """The candidate's own attributes that answer this request.

    These are read off the person's row, not inferred: the ranking is
    Aito's, and these say what about the person the ranking is made of.
    Kept to facts on the record so a delivery lead can argue with them
    — "Frontend Developer", "based in Tampere", "React", not a score.
    """
    chips: list[str] = []
    if candidate.title:
        chips.append(candidate.title)
    if candidate.discipline and candidate.discipline == role:
        chips.append(f"does {role} work")
    if site and candidate.site == site:
        chips.append(f"based in {site}")
    elif candidate.site:
        chips.append(f"{candidate.site} — would travel")
    # Two or three skills is a reason; the whole list is a CV dump.
    for skill in candidate.skills.split()[:3]:
        chips.append(skill)
    if candidate.certifications:
        chips.append(candidate.certifications.split(",")[0].strip())
    if candidate.years_experience:
        chips.append(f"{candidate.years_experience}y")
    return chips


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

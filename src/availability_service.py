"""Who is actually free between two dates.

The capacity view answers "how loaded is this person right now" with a
single running total. That is the wrong shape for staffing a proposal,
because a proposal has a *window*: a project starting in November does
not care that someone is at 300% today if two of those bookings end in
October. Answering it properly needs load per month, not load.

Two inputs, and the second is the one no scheduling spreadsheet has:

  * **Booked work** — `assignments` carries the window each booking
    occupies (`start_month` / `end_month`, denormalised off the
    project), so a person's load in a given month is the sum of the
    allocations whose window covers it.
  * **Absences** — planned leave, training, secondments. Not derivable
    from booked work: an empty calendar and parental leave look
    identical from the assignment table, and only one of them means
    the person is available.

Both are plain aggregation, deliberately. There is no prediction here
— a calendar is a fact, and dressing arithmetic up as inference would
be exactly the kind of thing this demo should not teach.
"""

from dataclasses import dataclass, field

from src.aito_client import AitoClient, AitoError


# Above this average load across the window, a person is not a
# realistic candidate however well they match.
BUSY_PCT = 100


def month_index(month: str) -> int:
    year, mon = month.split("-")
    return int(year) * 12 + int(mon) - 1


def month_label(index: int) -> str:
    return f"{index // 12}-{index % 12 + 1:02d}"


def window_months(start_month: str, months: int) -> list[str]:
    start = month_index(start_month)
    return [month_label(start + offset) for offset in range(max(months, 1))]


@dataclass
class WindowAvailability:
    """One person's standing over a specific date range."""
    person: str
    booked_pct: int             # mean allocation across the window
    peak_pct: int               # worst single month
    free_pct: int               # 100 − booked, floored at 0
    absent_months: list[str] = field(default_factory=list)
    absence_kind: str = ""
    by_month: dict[str, int] = field(default_factory=dict)
    # Open bids whose pencilled team includes this person, overlapping
    # the window. Not booked, so it does not reduce free capacity — but
    # it is a claim, and the first lead to press go wins.
    contention: int = 0
    contention_pct: int = 0

    @property
    def available(self) -> bool:
        """Free enough to take the work, and present for it.

        Any absence overlapping the window disqualifies outright rather
        than reducing a score: half a person for half a project is a
        different conversation, and one a planner should have
        explicitly.
        """
        return not self.absent_months and self.booked_pct < BUSY_PCT

    def to_dict(self) -> dict:
        return {
            "person": self.person,
            "booked_pct": self.booked_pct,
            "peak_pct": self.peak_pct,
            "free_pct": self.free_pct,
            "absent_months": self.absent_months,
            "absence_kind": self.absence_kind,
            "available": self.available,
            "contention": self.contention,
            "contention_pct": self.contention_pct,
            "by_month": self.by_month,
        }


def _fetch(client: AitoClient, table: str, limit: int) -> list[dict]:
    """All rows of a table, tolerating one this tenant doesn't carry."""
    try:
        response = client.search(table, {}, limit=limit)
    except AitoError as exc:
        if exc.status_code == 400 and f"failed to open '{table}'" in str(exc):
            return []
        raise
    return response.get("hits") or []


def role_phases(client: AitoClient) -> dict[str, tuple[float, float]]:
    """When each role is needed, as a fraction of a project's span.

    Measured from the data rather than declared here. The generator has
    its own table of phases, and copying it into this module would be
    the same mistake the booktest made with the reliability roster: a
    constant duplicated across a boundary drifts. Reading it back from
    `assignments` × `projects` means a fixture change moves the planner
    with it.

    Falls back to the whole span for a role with no usable history —
    booking someone for longer than needed is the safe direction.
    """
    projects = {p["project_id"]: p for p in _fetch(client, "projects", 500)}
    spans: dict[str, list[tuple[float, float]]] = {}
    for row in _fetch(client, "assignments", 4000):
        project = projects.get(row.get("project_id"))
        if not project or not row.get("start_month"):
            continue
        base = month_index(project["start_month"])
        total = max(1, round(int(project["duration_days"]) / 30.44))
        lo = (month_index(row["start_month"]) - base) / total
        hi = (month_index(row["end_month"]) - base + 1) / total
        if 0.0 <= lo <= 1.0 and 0.0 < hi <= 1.2:
            spans.setdefault(row["role"], []).append((lo, min(hi, 1.0)))

    phases: dict[str, tuple[float, float]] = {}
    for role, pairs in spans.items():
        if len(pairs) < 5:
            continue
        phases[role] = (sum(p[0] for p in pairs) / len(pairs),
                        sum(p[1] for p in pairs) / len(pairs))
    return phases


def restrict(standing: WindowAvailability,
             months: list[str]) -> WindowAvailability:
    """Re-read one person's standing over a SUB-window.

    A seat does not run for the whole project — the designer is wanted
    at the start, the QA engineer at the end — so the question "is this
    person free" has to be asked about the months the seat actually
    occupies. Derived from the `by_month` the full-window pass already
    built, so this costs no extra queries.
    """
    wanted = [m for m in months if m in standing.by_month]
    if not wanted:
        return standing
    loads = [standing.by_month[m] for m in wanted]
    booked = round(sum(loads) / len(loads))
    absent = sorted(set(standing.absent_months) & set(wanted))
    return WindowAvailability(
        person=standing.person,
        booked_pct=booked,
        peak_pct=max(loads),
        free_pct=max(0, 100 - booked),
        absent_months=absent,
        absence_kind=standing.absence_kind if absent else "",
        by_month={m: standing.by_month[m] for m in wanted},
        contention=standing.contention,
        contention_pct=standing.contention_pct,
    )


def availability_in_window(
    client: AitoClient, start_month: str, months: int,
) -> dict[str, WindowAvailability]:
    """`person → WindowAvailability` across `months` from `start_month`.

    People with no bookings and no absences are still returned, at 0%
    booked. Omitting them would make "nobody is free" and "nobody
    exists" look the same to the caller, and the whole point of this is
    to surface the people the capacity view buries.
    """
    window = window_months(start_month, months)
    window_set = set(window)
    first, last = month_index(window[0]), month_index(window[-1])

    people = _fetch(client, "people", limit=500)
    per_person: dict[str, WindowAvailability] = {
        p["person"]: WindowAvailability(
            person=p["person"], booked_pct=0, peak_pct=0, free_pct=100,
            by_month={m: 0 for m in window},
        )
        for p in people if p.get("person")
    }

    for row in _fetch(client, "assignments", limit=4000):
        person = row.get("person")
        entry = per_person.get(person)
        if entry is None or not row.get("start_month"):
            continue
        booked_from = month_index(row["start_month"])
        booked_to = month_index(row.get("end_month") or row["start_month"])
        if booked_to < first or booked_from > last:
            continue
        allocation = int(row.get("allocation_pct") or 0)
        for index in range(max(booked_from, first), min(booked_to, last) + 1):
            entry.by_month[month_label(index)] += allocation

    for row in _fetch(client, "absences", limit=1000):
        entry = per_person.get(row.get("person"))
        if entry is None:
            continue
        away = {month_label(i) for i in
                range(month_index(row["start_month"]),
                      month_index(row["end_month"]) + 1)}
        overlap = sorted(away & window_set)
        if overlap:
            entry.absent_months = sorted(set(entry.absent_months) | set(overlap))
            # Report the reason for the longest overlap, not the last
            # one read — "parental leave" beats "training" for whoever
            # has to reshuffle around it.
            if len(overlap) >= len(entry.absent_months) or not entry.absence_kind:
                entry.absence_kind = row.get("kind", "")

    # Provisional claims are counted SEPARATELY, never folded into
    # booked load. Treating a 40%-likely bid as booked time makes
    # everyone look busy and the planner useless; ignoring it makes
    # three leads each plan the same person. Reporting it apart is the
    # only honest option — the number is a warning, not a subtraction.
    for row in _fetch(client, "proposals", limit=2000):
        entry = per_person.get(row.get("person"))
        if entry is None or not row.get("start_month"):
            continue
        claim_from = month_index(row["start_month"])
        claim_to = month_index(row.get("end_month") or row["start_month"])
        if claim_to < first or claim_from > last:
            continue
        entry.contention += 1
        entry.contention_pct += int(row.get("allocation_pct") or 0)

    for entry in per_person.values():
        loads = list(entry.by_month.values()) or [0]
        entry.booked_pct = round(sum(loads) / len(loads))
        entry.peak_pct = max(loads)
        entry.free_pct = max(0, 100 - entry.booked_pct)
    return per_person

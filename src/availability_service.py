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

    for entry in per_person.values():
        loads = list(entry.by_month.values()) or [0]
        entry.booked_pct = round(sum(loads) / len(loads))
        entry.peak_pct = max(loads)
        entry.free_pct = max(0, 100 - entry.booked_pct)
    return per_person

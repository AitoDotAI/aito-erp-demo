"""Tests for the engagement planner.

The parts worth pinning are the ones that would be wrong *quietly*: a
team that doesn't add up to the size that was asked for, a price band
that drifts from the ratio it claims to describe, and an objection
ranking that silently includes the empty reason every won quote carries.
"""

import pytest
from src.planner_service import _band_for, _role_slots, _p_of


class _FakeClient:
    """Returns a canned `_predict` response per (table, predict_field)."""

    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def predict(self, table, where, predict_field, limit=6, select_extra=None):
        self.calls.append((table, where, predict_field))
        return self._responses.get((table, predict_field),
                                   {"hits": [], "offset": 0, "total": 0})


def _role_client(mix):
    return _FakeClient({
        ("assignments", "role"): {
            "hits": [{"$value": role, "$p": p} for role, p in mix],
        },
    })


def test_role_mix_scales_to_exactly_the_requested_team_size():
    """Largest-remainder, so eight people asked for is eight staffed."""
    client = _role_client([("engineer", 0.82), ("lead", 0.11), ("senior", 0.07)])
    slots = _role_slots(client, "construction", 8)
    assert sum(count for _, count, _ in slots) == 8
    counts = {role: count for role, count, _ in slots}
    assert counts["engineer"] == 6


@pytest.mark.parametrize("team_size", [1, 2, 3, 5, 7, 11, 20])
def test_team_always_adds_up(team_size):
    client = _role_client([("engineer", 0.55), ("lead", 0.25), ("senior", 0.20)])
    slots = _role_slots(client, "design", team_size)
    assert sum(count for _, count, _ in slots) == team_size


def test_roles_with_no_history_produce_no_slots():
    """An empty distribution is reported as no mix, not as a made-up one."""
    client = _FakeClient({})
    assert _role_slots(client, "construction", 6) == []


def test_price_bands_follow_the_ratio():
    assert _band_for(0.80) == "under"
    assert _band_for(1.00) == "at_market"
    assert _band_for(1.09) == "at_market"
    assert _band_for(1.20) == "over"
    assert _band_for(1.90) == "well_over"


def test_p_of_reports_a_missing_candidate_as_none():
    """No `true` hit means no opinion — not 0.0, which would render as
    'certain to lose' rather than 'we cannot say'."""
    p, why = _p_of([{"$value": False, "$p": 0.9}], True)
    assert p is None
    assert why == {}


def test_p_of_matches_across_boolean_spellings():
    """Aito answers Booleans as `true` on one surface and `True` on
    another; both are the same candidate."""
    p, _ = _p_of([{"$value": "True", "$p": 0.42}], True)
    assert p == 0.42


def _cand(name, load, fit=0.3, absent=()):
    """A candidate with a window standing.

    `available` is what `_fill_seats` reads — it means "free across THIS
    project's months", which is not the same as today's running total.
    A person at 300% whose bookings end before the project starts is
    available for it.
    """
    from src.planner_service import Candidate

    status = "overloaded" if load > 110 else "available" if load < 60 else "balanced"
    return Candidate(person=name, fit=fit, current_load_pct=load, status=status,
                     booked_pct=load, free_pct=max(0, 100 - load),
                     available=(load < 100 and not absent),
                     absent_months=list(absent),
                     absence_kind="annual leave" if absent else "")


def test_seats_are_filled_without_double_booking():
    """One person, one seat. Aito ranks per role and knows nothing about
    the other roles, so nothing stops the same name topping all of them."""
    from src.planner_service import RoleSlot, _fill_seats

    shared = [_cand("A", 0), _cand("B", 0), _cand("C", 0)]
    slots = [
        RoleSlot("frontend", 2, 0.5, list(shared)),
        RoleSlot("backend", 1, 0.5, list(shared)),
    ]
    _fill_seats(slots)
    picked = [p for s in slots for p in s.assignees]
    assert picked == ["A", "B", "C"]
    assert len(set(picked)) == 3


def test_a_best_fit_who_is_busy_in_the_window_yields():
    """The strongest match, booked solid across the project's months, is
    not a staffing answer — but they are still offered in the picker, so
    this is a default, not a veto."""
    from src.planner_service import RoleSlot, _fill_seats

    slots = [RoleSlot("frontend", 1, 0.5,
                      [_cand("Busy", 300, fit=0.9), _cand("Free", 40, fit=0.1)])]
    _fill_seats(slots)
    assert slots[0].assignees == ["Free"]


def test_everyone_busy_still_staffs_the_seat():
    """When there is no un-overloaded option the seat is filled anyway.
    Leaving it blank would hide the problem rather than show it."""
    from src.planner_service import RoleSlot, _fill_seats

    slots = [RoleSlot("frontend", 1, 0.5,
                      [_cand("Busy", 300, fit=0.9), _cand("Busier", 400, fit=0.1)])]
    _fill_seats(slots)
    assert slots[0].assignees == ["Busy"]


def test_a_seat_with_no_candidates_left_is_reported_empty():
    from src.planner_service import RoleSlot, _fill_seats

    slots = [RoleSlot("frontend", 3, 0.5, [_cand("A", 0)])]
    _fill_seats(slots)
    assert slots[0].assignees == ["A", "", ""]


def test_leave_in_the_window_disqualifies_even_with_capacity():
    """Half a person for half a project is a conversation, not a
    default — an absence overlapping the window steps aside for anyone
    who is actually there."""
    from src.planner_service import RoleSlot, _fill_seats

    slots = [RoleSlot("frontend", 1, 0.5, [
        _cand("OnLeave", 10, fit=0.9, absent=("2026-12",)),
        _cand("Present", 60, fit=0.1),
    ])]
    _fill_seats(slots)
    assert slots[0].assignees == ["Present"]

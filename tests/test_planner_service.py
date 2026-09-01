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

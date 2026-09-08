"""Tests for the revenue outlook.

The money model is the part worth pinning: percentage-of-completion
plus a risk shift is easy to get subtly wrong in a way that still looks
plausible on a chart. These assert the invariants a reader of the view
is entitled to rely on — nothing is created, nothing is lost, and a
missing prediction is reported as missing rather than as zero.
"""

from src.forecast_service import (_build_timeline, _month_index, _month_span,
                                  _outlook_for)


def _project(**overrides) -> dict:
    base = {
        "project_id": "PRJ-1",
        "name": "Construction — City of Tampere #1",
        "customer": "City of Tampere",
        "project_type": "construction",
        "manager": "M. Hakala",
        "status": "active",
        "budget_eur": 120000.0,
        "duration_days": 120,      # four months
        "start_month": "2026-08",
    }
    base.update(overrides)
    return base


NOW = _month_index("2026-09")


def test_month_span_rounds_to_whole_months():
    assert _month_span(30) == 1
    assert _month_span(120) == 4
    # A project shorter than a month still occupies one.
    assert _month_span(5) == 1


def test_percentage_of_completion_leaves_only_the_unearned_share():
    """One month elapsed of four → three quarters still to recognise."""
    outlook = _outlook_for(_project(), NOW)
    assert outlook.months_total == 4
    assert outlook.months_remaining == 3
    assert outlook.remaining_eur == 90000.0
    assert outlook.scheduled_end_month == "2026-11"
    assert outlook.overdue is False


def test_a_project_past_its_schedule_is_overdue_not_negative():
    """Elapsed is clamped, so an old project reports its whole value as
    unbilled and overdue rather than a negative remainder."""
    outlook = _outlook_for(_project(start_month="2025-01"), NOW)
    assert outlook.overdue is True
    assert outlook.months_remaining == 0
    assert outlook.remaining_eur == 120000.0


def test_timeline_moves_money_without_creating_it():
    """Scheduled total == expected + slipped total. The prediction
    shifts revenue in time; it never invents or destroys any."""
    outlook = _outlook_for(_project(), NOW)
    outlook.on_time_p = 0.5
    months = _build_timeline([outlook], NOW, horizon=9)

    scheduled = sum(m.scheduled_eur for m in months)
    expected = sum(m.expected_eur for m in months)
    assert round(scheduled, 6) == 90000.0
    assert round(expected, 6) == 90000.0
    # Half of it lands in the month after the scheduled end.
    slip_month = next(m for m in months if m.month == "2026-12")
    assert round(slip_month.slipped_eur, 6) == 45000.0


def test_no_prediction_leaves_the_schedule_untouched():
    """A project Aito has no opinion on must not be silently treated as
    certain to slip — the schedule is the forecast, unadjusted."""
    outlook = _outlook_for(_project(), NOW)
    outlook.on_time_p = None
    months = _build_timeline([outlook], NOW, horizon=9)
    for month in months:
        assert month.scheduled_eur == month.expected_eur
        assert month.slipped_eur == 0.0
    assert outlook.at_risk_eur == 0.0


def test_overdue_value_never_enters_the_timeline():
    """Overdue money is reported as overdue, not smeared into future
    months where it would read as revenue we expect to collect."""
    outlook = _outlook_for(_project(start_month="2025-01"), NOW)
    outlook.on_time_p = 0.9
    months = _build_timeline([outlook], NOW, horizon=9)
    assert sum(m.scheduled_eur for m in months) == 0.0
    assert sum(m.expected_eur for m in months) == 0.0

"""Tests for window availability.

This is arithmetic over a calendar, and the failure modes are all
boundary conditions: a booking that ends the month the project starts,
an absence that clips the window's edge, a person with nothing booked
at all. Each of those silently produces a plausible wrong answer, which
is the kind that ships.
"""

from src.availability_service import (WindowAvailability, month_label,
                                      window_months)


def test_window_months_is_inclusive_of_the_first_month():
    assert window_months("2026-09", 4) == ["2026-09", "2026-10", "2026-11", "2026-12"]
    assert window_months("2026-12", 2) == ["2026-12", "2027-01"]


def test_a_zero_length_window_still_covers_one_month():
    """A project shorter than a month occupies the month it runs in."""
    assert window_months("2026-09", 0) == ["2026-09"]


def test_month_label_rolls_the_year():
    from src.availability_service import month_index

    assert month_label(month_index("2026-12") + 1) == "2027-01"


def test_available_needs_both_capacity_and_presence():
    """Free hours and being there are separate conditions. Someone at
    20% booked who is on leave for one month of a four-month build is
    not available for it."""
    free = WindowAvailability("A", booked_pct=20, peak_pct=40, free_pct=80)
    assert free.available is True

    on_leave = WindowAvailability("B", booked_pct=20, peak_pct=40, free_pct=80,
                                  absent_months=["2026-12"],
                                  absence_kind="parental leave")
    assert on_leave.available is False

    booked = WindowAvailability("C", booked_pct=140, peak_pct=200, free_pct=0)
    assert booked.available is False


def test_contention_never_reduces_free_capacity():
    """A pencilled bid is a claim, not a booking.

    Folding a 40%-likely proposal into booked load makes everyone look
    busy and the planner useless; ignoring it entirely lets three leads
    each plan the same architect. It is reported alongside, never
    subtracted — the number is a warning.
    """
    standing = WindowAvailability("A", booked_pct=30, peak_pct=40, free_pct=70,
                                  contention=2, contention_pct=90)
    assert standing.free_pct == 70
    assert standing.available is True
    assert standing.contention == 2

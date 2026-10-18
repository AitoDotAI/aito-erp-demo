"""An active project is forecast on all six outcomes, not just `success`.

The data already carried money / team / customer / on-time / works /
door-opened per project, and the portfolio showed one composite of them.
The composite averages away the point: drivers move the outcomes in
different directions. A failing predict is an error, never a project
shown with a blank forecast.
"""

import pytest

from src.aito_client import AitoError
from src.project_service import ProjectRow, _forecast_active
from src.planner_service import CORE_OUTCOMES, QUALIFYING_OUTCOMES

DRIVERS = ("contract_type", "scope_clarity", "novelty", "customer_size", "team_seniority")


class _Predict:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def predict(self, table, where, field, limit=10, **_):
        self.calls.append((table, field, where))
        if field == self.fail_on:
            raise AitoError("Aito v2 returned 500")
        p = {"success": 0.7, "financial_ok": 0.3, "team_happy": 0.9}.get(field, 0.5)
        return {"hits": [{"$value": True, "$p": p, "$why": {}},
                         {"$value": False, "$p": 1 - p, "$why": {}}]}


def _row():
    return ProjectRow(
        project_id="PRJ-1", name="n", project_type="implementation", customer="c",
        manager="m", team_lead="l", team_size=5, team_members="a b",
        budget_eur=50000.0, duration_days=120, priority="high", status="active",
        start_month="2026-09", on_time=None, on_budget=None, success=None,
        contract_type="fixed_price", scope_clarity="unclear", novelty="new_stack",
        customer_size="small", team_seniority="junior_heavy")


def test_success_and_all_six_outcomes_are_asked_separately():
    client = _Predict()
    row = _forecast_active(client, _row())
    asked = [f for _, f, _ in client.calls]
    assert asked == ["success"] + [f for f, _ in CORE_OUTCOMES + QUALIFYING_OUTCOMES]
    assert [o["field"] for o in row.outcomes] == asked[1:]
    by_field = {o["field"]: o for o in row.outcomes}
    assert by_field["financial_ok"]["p"] == 0.3 and by_field["team_happy"]["p"] == 0.9
    assert {o["group"] for o in row.outcomes} == {"core", "qualifying"}


def test_every_question_carries_the_outcome_drivers():
    """Without them the six answers come from type and size alone and barely differ."""
    client = _Predict()
    _forecast_active(client, _row())
    for _, field, where in client.calls:
        assert all(where[d] for d in DRIVERS), field
        assert "team_members" not in where


def test_a_failed_predict_is_an_error_not_a_blank_forecast():
    with pytest.raises(AitoError):
        _forecast_active(_Predict(fail_on="team_happy"), _row())

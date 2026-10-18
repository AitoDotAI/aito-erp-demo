"""An active project is forecast on all six outcomes and on `outcome_score`.

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
        if field == "outcome_score":
            return {"hits": [{"$value": "2", "$p": 0.5, "$why": {}},
                             {"$value": "3", "$p": 0.3, "$why": {}},
                             {"$value": "1", "$p": 0.2, "$why": {}}]}
        p = {"financial_ok": 0.3, "team_happy": 0.9}.get(field, 0.5)
        return {"hits": [{"$value": True, "$p": p, "$why": {}},
                         {"$value": False, "$p": 1 - p, "$why": {}}]}


def _row():
    return ProjectRow(
        project_id="PRJ-1", name="n", project_type="implementation", customer="c",
        manager="m", team_lead="l", team_size=5, team_members="a b",
        budget_eur=50000.0, duration_days=120, priority="high", status="active",
        start_month="2026-09", on_time=None, on_budget=None, success=None, outcome_score=None,
        contract_type="fixed_price", scope_clarity="unclear", novelty="new_stack",
        customer_size="small", team_seniority="junior_heavy")


def test_the_combined_reading_is_the_expected_score_over_three():
    row = _forecast_active(_Predict(), _row())
    assert row.combined["expected_score"] == pytest.approx(2 * 0.5 + 3 * 0.3 + 1 * 0.2)
    assert row.combined["p"] == pytest.approx(row.combined["expected_score"] / 3)
    assert [d["value"] for d in row.combined["distribution"]] == ["1", "2", "3"]
    assert row.combined["top_value"] == "2"


def test_an_outcome_score_outside_zero_to_three_is_an_error():
    class Bad(_Predict):
        def predict(self, table, where, field, limit=10, **_):
            return {"hits": [{"$value": "7", "$p": 1.0, "$why": {}}]}
    with pytest.raises(AssertionError):
        _forecast_active(Bad(), _row())


def test_outcome_score_and_all_six_outcomes_are_asked_separately():
    client = _Predict()
    row = _forecast_active(client, _row())
    asked = [f for _, f, _ in client.calls]
    assert asked == ["outcome_score"] + [f for f, _ in CORE_OUTCOMES + QUALIFYING_OUTCOMES]
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


def test_the_score_counts_the_core_three_and_success_is_two_or_more():
    from data.generate_personas import core_outcome_score
    assert [core_outcome_score(*bits) for bits in
            [(False, False, False), (True, False, False), (True, True, False), (True, True, True)]] == ["0", "1", "2", "3"]


def test_fixture_scores_match_the_booleans_they_count():
    """Fixtures are gitignored; where present, the column must be the count."""
    from pathlib import Path
    import json
    root = Path(__file__).parent.parent / "data"
    checked = 0
    for t in ("metsa", "aurora", "studio"):
        f = root / t / "projects.json"
        if not f.exists():
            continue
        for r in json.loads(f.read_text()):
            want = None if r["financial_ok"] is None else str(
                sum([r["financial_ok"], r["team_happy"], r["customer_happy"]]))
            assert r["outcome_score"] == want, (t, r["project_id"])
            checked += 1
    if not checked:
        pytest.skip("no fixtures generated")


def _done(pid, score, **outcomes):
    r = _row()
    r.project_id, r.status, r.outcome_score = pid, "complete", score
    for f in ("financial_ok", "team_happy", "customer_happy", "on_time", "outcome_ok", "doors_opened"):
        setattr(r, f, outcomes.get(f, False))
    return r


def test_history_rates_per_kpi_and_combined_is_the_mean_score_over_three():
    from src.project_service import COMBINED, _compute_kpis
    rows = [_done("A", "3", financial_ok=True, team_happy=True, customer_happy=True),
            _done("B", "1", financial_ok=True), _row()]
    k = _compute_kpis(rows)
    assert (k.completed, k.active) == (2, 1)
    assert k.rates["financial_ok"] == 1.0 and k.rates["team_happy"] == 0.5
    assert k.rates[COMBINED] == pytest.approx((3 + 1) / 6)


def test_a_completed_project_without_a_recorded_score_is_an_error():
    from src.project_service import _compute_kpis
    with pytest.raises(AssertionError):
        _compute_kpis([_done("A", None)])

"""A PO rule decides only what it measurably decides, at its measured precision.

Every rule row showed a constant 0.99 on all three fields. Measured
against each supplier's own history, the cost centres and approvers the
rules set were mostly right 0 times in N — "Facilities", "IT", "Grocery"
and "Office" are not cost centres in the data at all — and Metsä's Elisa
rule matched no purchases. The account codes held (94-96%). So a rule now
sets a field only when history bears it out, shows how often it was
right, and leaves every other field to Aito. Same decision as the
accounting demo's ADR 0028.
"""

import json
from pathlib import Path

import pytest

from src.po_service import RULE_MIN_PRECISION, RULES_BY_TENANT, measure_rule, predict_single

DATA = Path(__file__).parent.parent / "data"


class _Client:
    def __init__(self, history, predicted):
        self.history, self.predicted = history, predicted

    def search(self, table, where, limit=10):
        rows = [r for r in self.history if all(r.get(k) == v for k, v in where.items())]
        return {"total": len(rows), "hits": rows[:limit]}

    def predict(self, table, where, field, limit=10):
        value, p = self.predicted[field]
        return {"hits": [{"$value": value, "$p": p, "$why": {}}]}


RULE = {"name": "Elenia → 6110", "supplier": "Elenia Oy", "sets": {"account_code": "6110"}}
HISTORY = ([{"supplier": "Elenia Oy", "account_code": "6110", "cost_center": "Site-Helsinki"}] * 140
           + [{"supplier": "Elenia Oy", "account_code": "4250", "cost_center": "Site-Helsinki"}] * 5)
PREDICTED = {"cost_center": ("Site-Helsinki", 0.95), "account_code": ("6110", 0.97),
             "approver": ("M. Hakala", 0.85)}
PO = {"purchase_id": "PO-1", "supplier": "Elenia Oy", "description": "Electricity",
      "amount_eur": 4820.0, "category": "utilities"}


def _predict(rules=(RULE,), history=HISTORY):
    import src.po_service as po
    saved = po.RULES_BY_TENANT["metsa"]
    po.RULES_BY_TENANT["metsa"] = list(rules)
    try:
        return predict_single(_Client(history, PREDICTED), PO, tenant="metsa")
    finally:
        po.RULES_BY_TENANT["metsa"] = saved


def test_a_rules_confidence_is_how_often_history_bore_it_out():
    row = _predict()
    assert row.account_code == "6110"
    assert row.account_code_confidence == round(140 / 145, 3)
    assert "140 of 145" in row.rule_fields["account_code"]


def test_a_rule_sets_only_the_fields_it_decides():
    row = _predict()
    assert set(row.rule_fields) == {"account_code"}
    assert (row.cost_center, row.cost_center_confidence) == ("Site-Helsinki", 0.95)
    assert (row.approver, row.approver_confidence) == ("M. Hakala", 0.85)
    assert row.confidence == 0.85        # the weakest field decides, as for any row


def test_a_rule_without_history_is_refused():
    with pytest.raises(ValueError, match="no purchases"):
        measure_rule(_Client([], PREDICTED), {"name": "Elisa", "supplier": "Elisa Oyj",
                                              "sets": {"account_code": "5510"}})


def test_a_rule_field_history_does_not_bear_out_is_refused():
    wrong = {"name": "Elenia → Facilities", "supplier": "Elenia Oy",
             "sets": {"cost_center": "Facilities"}}
    with pytest.raises(ValueError, match="0 of 145"):
        measure_rule(_Client(HISTORY, PREDICTED), wrong)


@pytest.mark.skipif(not (DATA / "metsa" / "purchases.json").exists(), reason="fixtures not generated")
@pytest.mark.parametrize("tenant", sorted(RULES_BY_TENANT))
def test_every_shipped_rule_holds_on_its_tenants_history(tenant):
    """The rules as written, against the fixtures that are loaded."""
    history = json.loads((DATA / tenant / "purchases.json").read_text())
    for rule in RULES_BY_TENANT[tenant]:
        measured = measure_rule(_Client(history, PREDICTED), rule)
        assert all(right / n >= RULE_MIN_PRECISION for _, right, n in measured.values()), rule["name"]


def test_a_rule_row_below_the_bar_says_which_field_to_check():
    """Most rule rows land in review because the field the rule does not
    decide — usually the approver — is Aito's, at 0.57-0.74. The row says
    so instead of a bare "review", as in the accounting demo."""
    row = _predict()                      # approver predicted at 0.85 → clears 0.75
    assert row.status_label == "Rule"
    import src.po_service as po
    low = dict(PREDICTED, approver=("M. Hakala", 0.60))
    saved = po.RULES_BY_TENANT["metsa"]
    po.RULES_BY_TENANT["metsa"] = [RULE]
    try:
        row = predict_single(_Client(HISTORY, low), PO, tenant="metsa")
    finally:
        po.RULES_BY_TENANT["metsa"] = saved
    assert row.source == "review"
    assert row.status_label == "Rule, check approver"


def test_an_aito_row_is_labelled_by_the_same_bar():
    import src.po_service as po
    saved = po.RULES_BY_TENANT["metsa"]
    po.RULES_BY_TENANT["metsa"] = []
    try:
        row = predict_single(_Client(HISTORY, PREDICTED), PO, tenant="metsa")
        low = predict_single(_Client(HISTORY, dict(PREDICTED, approver=("X", 0.6))), PO, tenant="metsa")
    finally:
        po.RULES_BY_TENANT["metsa"] = saved
    assert (row.status_label, low.status_label) == ("Aito", "Review")

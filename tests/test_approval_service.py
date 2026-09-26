"""Approval routing: an escalation rule overrides the level, never the approver's `$p`.

The explanation shown beside the approver is the approver's own `$why`, and
the confidence beside it must be the probability that explanation adds up
to. See org/demo-why-integrity-audit.md ("substitute-and-keep").
"""

from src.approval_service import predict_approval


def _hit(field, value, p):
    return {"$value": value, "$p": p, "$why": {"type": "product", "factors": [
        {"type": "baseP", "value": p, "proposition": {field: {"$has": value}}}]}}


class _FakeClient:
    def predict(self, table, where, field, limit=10):
        if field == "approval_level":
            return {"hits": [_hit(field, "Manager", 0.7)]}
        return {"hits": [_hit(field, "Anna Virtanen", 0.4), _hit(field, "Pekka Laine", 0.3)]}


def test_escalation_changes_the_level_but_keeps_the_approvers_own_confidence():
    item = {"purchase_id": "PO-1", "supplier": "S", "amount": 60000, "category": "capex"}

    result = predict_approval(_FakeClient(), item)

    assert result.predicted_level == "Board"          # the rule fired
    assert result.escalation_reason
    assert result.predicted_approver == "Anna Virtanen"
    # Used to be 0.99: Aito's approver pick shown as near-certain because a
    # rule about the LEVEL had fired.
    assert result.confidence == 0.4
    assert result.why["final_p"] == result.confidence


def test_no_escalation_leaves_the_prediction_alone():
    item = {"purchase_id": "PO-2", "supplier": "S", "amount": 100, "category": "office"}

    result = predict_approval(_FakeClient(), item)

    assert result.predicted_level == "Manager"
    assert result.escalation_reason is None
    assert result.confidence == 0.4

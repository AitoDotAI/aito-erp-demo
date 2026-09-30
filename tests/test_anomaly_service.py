"""Tests for anomaly detection — inverse prediction approach."""

from unittest.mock import MagicMock
from src.anomaly_service import (
    evaluate_transaction, detect_anomalies, _classify_severity, DEMO_ANOMALIES
)


def _client_returning_low_p_for_actual(actual_value, p=0.02):
    """Client where the actual value has very low predicted probability.
    `search` answers with a real count: a MagicMock would answer the
    "has this supplier any history" check with a truthy Mock and the
    check would never be exercised."""
    client = MagicMock()
    client.predict.return_value = {
        "hits": [
            {"$p": 0.85, "$value": "common_value", "$why": {}},
            {"$p": p, "$value": actual_value, "$why": {}},
        ]
    }
    client.search.return_value = {"total": 12, "hits": []}
    return client


def test_classify_severity_thresholds():
    assert _classify_severity(95) == "high"
    assert _classify_severity(86) == "high"
    assert _classify_severity(75) == "medium"
    assert _classify_severity(60) == "medium"
    assert _classify_severity(50) == "low"


def test_evaluate_transaction_high_anomaly_score():
    """A combination with very low probability should get a high anomaly score."""
    client = _client_returning_low_p_for_actual("4220", p=0.03)
    transaction = {
        "purchase_id": "PO-7812",
        "supplier": "Wärtsilä Components",
        "amount": 1450,
        "account_code": "4220",
        "flagged_field": "account_code",
    }
    flag = evaluate_transaction(client, transaction)
    # 1 - 0.03 = 0.97 → score 97 → high
    assert flag.anomaly_score >= 90
    assert flag.severity == "high"


def test_evaluate_transaction_uses_predict_not_evaluate():
    """We use _predict (inverse prediction), not _evaluate."""
    client = _client_returning_low_p_for_actual("4220")
    transaction = {
        "purchase_id": "PO-001",
        "supplier": "Test",
        "amount": 1000,
        "account_code": "4220",
        "flagged_field": "account_code",
    }
    evaluate_transaction(client, transaction)
    client.predict.assert_called_once()


def test_detect_anomalies_sorts_by_score_descending():
    """Multiple transactions should be sorted highest-anomaly first."""
    client = _client_returning_low_p_for_actual("4220", p=0.03)
    transactions = [
        {"purchase_id": "PO-1", "supplier": "A", "amount": 100, "account_code": "4220",
         "flagged_field": "account_code"},
        {"purchase_id": "PO-2", "supplier": "B", "amount": 200, "account_code": "5710",
         "flagged_field": "account_code"},
    ]
    flags = detect_anomalies(client, transactions)
    assert len(flags) == 2
    assert flags[0].anomaly_score >= flags[1].anomaly_score


def test_demo_anomalies_have_required_fields():
    """The incoming transaction only; conclusions are computed (see
    tests/test_anomaly_from_data.py)."""
    required = {"purchase_id", "supplier", "amount", "account_code", "flagged_field"}
    for tx in DEMO_ANOMALIES:
        assert required.issubset(tx.keys()), f"Missing keys in {tx}"

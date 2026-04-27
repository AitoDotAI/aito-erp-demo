"""Tests for anomaly detection — inverse prediction approach."""

from unittest.mock import MagicMock
from src.anomaly_service import (
    evaluate_transaction, detect_anomalies, _classify_severity, DEMO_ANOMALIES
)


def _client_returning_low_p_for_actual(actual_value, p=0.02):
    """Client where the actual value has very low predicted probability."""
    client = MagicMock()
    client.predict.return_value = {
        "hits": [
            {"$p": 0.85, "feature": "common_value", "$why": {}},
            {"$p": p, "feature": actual_value, "$why": {}},
        ]
    }
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
        "supplier": "Fazer Food Services",
        "amount": 14200,
        "account_code": "4220",
        "flagged_field": "account_code",
        "expected_value": "5710 (catering)",
        "actual_value": "4220 (raw mat.)",
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
        "expected_value": "x",
        "actual_value": "y",
    }
    evaluate_transaction(client, transaction)
    client.predict.assert_called_once()


def test_detect_anomalies_sorts_by_score_descending():
    """Multiple transactions should be sorted highest-anomaly first."""
    client = _client_returning_low_p_for_actual("4220", p=0.03)
    transactions = [
        {"purchase_id": "PO-1", "supplier": "A", "amount": 100, "account_code": "4220",
         "flagged_field": "x", "expected_value": "x", "actual_value": "y"},
        {"purchase_id": "PO-2", "supplier": "B", "amount": 200, "account_code": "4220",
         "flagged_field": "x", "expected_value": "x", "actual_value": "y"},
    ]
    flags = detect_anomalies(client, transactions)
    assert len(flags) == 2
    assert flags[0].anomaly_score >= flags[1].anomaly_score


def test_demo_anomalies_have_required_fields():
    """All demo anomalies must have the keys the service expects."""
    required = {"purchase_id", "supplier", "amount", "account_code",
                "flagged_field", "expected_value", "actual_value"}
    for tx in DEMO_ANOMALIES:
        assert required.issubset(tx.keys()), f"Missing keys in {tx}"

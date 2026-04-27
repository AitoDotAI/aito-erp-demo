"""Tests for Smart Entry — multi-field prediction."""

from unittest.mock import MagicMock
from src.smartentry_service import predict_fields, KNOWN_SUPPLIERS, INPUT_FIELDS, PREDICT_FIELDS


def _make_client(p=0.85):
    """Make a mocked client where every predict returns a high-confidence result."""
    client = MagicMock()
    client.predict.return_value = {
        "hits": [
            {"$p": p, "feature": "predicted_value", "$why": {}},
            {"$p": 0.10, "feature": "alt1", "$why": {}},
            {"$p": 0.05, "feature": "alt2", "$why": {}},
        ]
    }
    return client


def test_predict_fields_returns_all_predictable_fields_when_only_supplier_provided():
    """Given only a supplier, the service should predict all PREDICT_FIELDS."""
    client = _make_client()
    result = predict_fields(client, {"supplier": "Neste Oyj"})
    d = result.to_dict()

    assert "fields" in d
    assert d["predicted_count"] == len(PREDICT_FIELDS)
    field_names = [f["field"] for f in d["fields"]]
    for f in PREDICT_FIELDS:
        assert f in field_names


def test_predict_fields_skips_already_known_fields():
    """If cost_center is provided, the service should not predict it."""
    client = _make_client()
    result = predict_fields(client, {"supplier": "Neste Oyj", "cost_center": "Logistics"})
    field_names = [f.field_name for f in result.predictions]
    assert "cost_center" not in field_names
    assert "account_code" in field_names  # Still predicts the others


def test_predict_fields_includes_alternatives_and_confidence():
    """Each prediction should include top alternatives and confidence."""
    client = _make_client(p=0.92)
    result = predict_fields(client, {"supplier": "Neste Oyj"})
    d = result.to_dict()

    first_field = d["fields"][0]
    assert first_field["confidence"] == 0.92
    assert first_field["predicted"] is True
    assert "alternatives" in first_field


def test_known_suppliers_match_input_fields():
    """The supplier dropdown must work with INPUT_FIELDS."""
    assert "supplier" in INPUT_FIELDS
    assert len(KNOWN_SUPPLIERS) >= 5  # Spec wants 5+ suppliers


def test_to_dict_matches_frontend_contract():
    """to_dict() output must match the SmartEntryResponse TypeScript type."""
    client = _make_client()
    result = predict_fields(client, {"supplier": "Caverion Suomi"})
    d = result.to_dict()

    # Required keys per frontend types
    assert "where" in d
    assert "fields" in d
    assert "predicted_count" in d
    assert "avg_confidence" in d

    # Field structure
    f = d["fields"][0]
    assert "field" in f
    assert "value" in f
    assert "confidence" in f
    assert "predicted" in f

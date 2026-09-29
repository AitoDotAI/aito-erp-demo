"""Tests for PO service — rules + Aito prediction logic."""

import pytest
from unittest.mock import MagicMock
from src.po_service import predict_single, predict_batch, compute_metrics, DEMO_POS


def _make_client(predict_response=None):
    client = MagicMock()
    if predict_response is None:
        predict_response = {
            "hits": [
                {"$p": 0.88, "$value": "Production", "$why": {}},
                {"$p": 0.08, "$value": "Facilities", "$why": {}},
            ]
        }
    client.predict.return_value = predict_response
    return client


def test_rule_match_elenia():
    """Elenia Oy should match the Facilities/6110 rule."""
    client = _make_client()
    inv = {"purchase_id": "PO-001", "supplier": "Elenia Oy",
           "description": "Electricity", "amount_eur": 1000, "category": "utilities"}
    result = predict_single(client, inv)
    assert result.source == "rule"
    assert result.cost_center == "Facilities"
    assert result.account_code == "6110"
    assert result.confidence == 0.99
    # Rules should not call Aito
    client.predict.assert_not_called()


def test_rule_match_telia():
    """Telia Finland should match the IT/5510 rule."""
    client = _make_client()
    inv = {"purchase_id": "PO-002", "supplier": "Telia Finland Oyj",
           "description": "Mobile subs", "amount_eur": 500, "category": "telecom"}
    result = predict_single(client, inv)
    assert result.source == "rule"
    assert result.cost_center == "IT"
    assert result.account_code == "5510"


def test_aito_prediction_high_confidence():
    """Non-rule supplier should fall back to Aito prediction."""
    client = _make_client({
        "hits": [
            {"$p": 0.91, "$value": "Logistics", "$why": {}},
            {"$p": 0.05, "$value": "Production", "$why": {}},
        ]
    })
    inv = {"purchase_id": "PO-003", "supplier": "Neste Oyj",
           "description": "Fuel", "amount_eur": 2000, "category": "fuel"}
    result = predict_single(client, inv)
    assert result.source == "aito"
    assert result.confidence >= 0.50
    assert client.predict.call_count == 3  # cost_center, account_code, approver


def test_aito_prediction_low_confidence_flagged_for_review():
    """Low confidence predictions should be flagged for review."""
    client = _make_client({
        "hits": [
            {"$p": 0.35, "$value": "Unknown", "$why": {}},
        ]
    })
    inv = {"purchase_id": "PO-004", "supplier": "Berner Oy",
           "description": "Chemicals", "amount_eur": 400, "category": "cleaning"}
    result = predict_single(client, inv)
    assert result.source == "review"
    assert result.confidence < 0.50


def test_compute_metrics():
    """Metrics should correctly count sources."""
    client = _make_client()
    predictions = predict_batch(client, DEMO_POS[:4])
    metrics = compute_metrics(predictions)
    assert metrics["total"] == 4
    assert "automation_rate" in metrics
    assert "rule_count" in metrics
    assert "aito_count" in metrics


def test_prediction_to_dict():
    """to_dict should return all expected keys."""
    client = _make_client()
    inv = {"purchase_id": "PO-001", "supplier": "Elenia Oy",
           "description": "Electricity", "amount_eur": 1000, "category": "utilities"}
    result = predict_single(client, inv)
    d = result.to_dict()
    assert "purchase_id" in d
    assert "cost_center" in d
    assert "account_code" in d
    assert "approver" in d
    assert "source" in d
    assert "confidence" in d


def test_no_demo_po_description_names_a_place():
    """`purchases` records a store or site only in `cost_center`, never in
    the description, so a place name in a demo PO is a word Aito has no
    evidence for. "Cosmetics restock — Tampere" was routed by supplier to
    Store-Helsinki at 0.93: right by the data, and a headline screen
    contradicting its own input."""
    from src.po_service import DEMO_POS_BY_TENANT
    places = ("helsinki", "tampere", "oulu", "vantaa", "turku", "espoo",
              "kouvola", "tallinn", "riga")
    for tenant, pos in DEMO_POS_BY_TENANT.items():
        for po in pos:
            named = [p for p in places if p in po["description"].lower()]
            assert not named, f"{tenant} {po['purchase_id']}: {po['description']!r} names {named}"


def test_a_62_percent_coding_goes_to_a_human():
    """At a 0.50 bar a coin-flip-plus coding counted as coded, and every
    demo row cleared it, so the queue never showed the review path. The
    weakest of the three fields decides."""
    from src.po_service import REVIEW_THRESHOLD
    client = _make_client({"hits": [{"$p": 0.62, "$value": "Production", "$why": {}}]})
    inv = {"purchase_id": "PO-005", "supplier": "Wärtsilä Components",
           "description": "Seals", "amount_eur": 900, "category": "production"}
    assert REVIEW_THRESHOLD == 0.75
    assert predict_single(client, inv).source == "review"

"""The Overview says which of its figures describe the data generator.

`purchases.routed_by` is drawn by data/generate_personas.py from a fixed
random mix, independent of the purchase. The automation rate, "POs
automated" and the learning curve count it, so they describe how the
fixture was generated, not what Aito achieved — and the page said
"computed live, not hardcoded", which was true and misleading at once.
The accuracy bands, by contrast, are measured, and held out: the live
test below checks that `_evaluate` leaves each test row out.
"""

import pytest

from src.overview_service import AutomationBreakdown, OverviewMetrics, ROUTED_BY_PROVENANCE


def test_the_response_says_routed_by_is_synthetic():
    metrics = OverviewMetrics(
        automation=AutomationBreakdown(**{f: 0 for f in AutomationBreakdown.__dataclass_fields__}),
        prediction_quality=[], learning_curve=[], summary={})
    provenance = metrics.to_dict()["provenance"]
    assert provenance["routed_by"] == ROUTED_BY_PROVENANCE
    assert "random" in ROUTED_BY_PROVENANCE


def _live_client():
    from src.aito_client import AitoClient
    from src.config import load_config
    try:
        cfg = load_config()
        cr = cfg.creds_for("metsa")
    except Exception as exc:   # noqa: BLE001 — no credentials means no live test
        pytest.skip(f"no Aito credentials: {exc}")
    return AitoClient.from_creds(cr.api_url, cr.api_key, api_version=cfg.api_version)


def test_evaluate_leaves_each_test_row_out():
    """The Overview's bands evaluate the first 200 rows of the very table
    Aito predicts from. That is held out only if `_evaluate` hides each
    test row from its own prediction. Proof: a row's `purchase_id` is
    unique, so if the row were visible, its exact supplier, description,
    amount and month would recover it. Measured 2026-09-30: 0 of 30."""
    client = _live_client()
    result = client.evaluate_with_cases(
        table="purchases", predict_field="purchase_id",
        feature_fields=["supplier", "description", "amount_eur", "order_month"], limit=30)
    assert result["accuracy"] == 0.0

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


needs_aito = pytest.mark.skipif(
    not __import__("os").environ.get("AITO_API_URL"),
    reason="AITO_API_URL not set — live Aito tests are opt-in",
)


def _live_client():
    from src.aito_client import AitoClient
    from src.config import load_config
    cfg = load_config()
    cr = cfg.creds_for("metsa")
    return AitoClient.from_creds(cr.api_url, cr.api_key, api_version=cfg.api_version)


@needs_aito
def test_evaluate_leaves_each_test_row_out():
    """The Overview's bands evaluate the first rows of the very table
    Aito predicts from. That is held out only if `_evaluate` hides each
    test row from its own prediction.

    The evidence is the row's own `purchase_id`, a unique String, so it
    says something only while that row is visible:
      - visible (`_predict`): the id points at its own row, and the
        cost centre comes back right nearly every time — the control
        that shows this probe CAN tell the two cases apart;
      - `_evaluate`: an id never seen, so accuracy falls to the base
        rate.
    Measured 2026-09-30 on metsa: visible 29/30; _evaluate 0.667 = base.
    (A first probe predicted the id itself and got 0/30 — but a visible
    row does not recover its id either, so it proved nothing.)"""
    client = _live_client()
    rows = client.search("purchases", {}, limit=30)["hits"]
    visible = sum(
        client.predict("purchases", {"purchase_id": r["purchase_id"]}, "cost_center",
                       limit=1)["hits"][0]["$value"] == r["cost_center"]
        for r in rows)
    assert visible >= 27, f"control: a visible row's id should point at its own row ({visible}/30)"

    held_out = client.evaluate_with_cases(
        table="purchases", predict_field="cost_center", feature_fields=["purchase_id"], limit=30)
    assert held_out["accuracy"] <= held_out["baseAccuracy"] + 0.05

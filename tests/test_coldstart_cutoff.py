"""The Cold Start slider's cutoff must cut the history Aito learns from.

`/api/coldstart/live?cutoff=2022-09` is meant to answer "what would Aito get right with only the
purchases up to September 2022?". It once returned the full-history accuracy at every cutoff
(td-20261030213014404900): the cutoff was in `evaluate.where`, which conditions the predicted row
and leaves the evidence untouched. `_evaluate` learned from 3,073 rows at every position. The
evidence is restricted by giving `evaluate` a nested `from` that holds only the rows up to the cutoff.
"""

from __future__ import annotations

import os

import pytest



@pytest.fixture(scope="module")
def app_module():
    """`src.app`, imported with a placeholder Aito if none is configured: the offline tests never send a request."""
    saved = {k: os.environ.get(k) for k in ("AITO_API_URL", "AITO_API_KEY")}
    os.environ.setdefault("AITO_API_URL", "https://example.invalid")
    os.environ.setdefault("AITO_API_KEY", "not-a-real-key")
    import src.app
    yield src.app
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)


class RecordingAito:
    """Remembers how `evaluate_with_cases` was called and answers like a small `_evaluate`."""

    def __init__(self, train_samples: int = 57):
        self.calls: list[dict] = []
        self._train_samples = train_samples

    def evaluate_with_cases(self, **kwargs):
        self.calls.append(kwargs)
        return {"accuracy": 0.9, "baseAccuracy": 0.3, "cases": [], "trainSamples": self._train_samples,
                "testSamples": 14}


def test_the_cutoff_limits_the_rows_the_prediction_learns_from(app_module):
    aito = RecordingAito()

    app_module._coldstart_evaluate_one(aito, "2022-09", "cost_center")

    (call,) = aito.calls
    assert call["population_where"] == {"order_month": {"$lte": "2022-09"}}


def test_the_cutoff_is_not_a_condition_on_the_predicted_row(app_module):
    aito = RecordingAito()

    app_module._coldstart_evaluate_one(aito, "2022-09", "cost_center")

    (call,) = aito.calls
    assert not call.get("evaluate_extra_where"), "a cutoff in evaluate.where leaves the evidence uncut"


def test_the_response_says_how_many_rows_it_learned_from(app_module):
    result = app_module._coldstart_evaluate_one(RecordingAito(train_samples=225), "2022-09", "cost_center")

    assert result["training_rows"] == 225


def test_the_held_out_rows_are_part_of_the_cutoff_history_and_leave_something_to_learn_from(app_module):
    """A test selection that is every row of the history leaves nothing to train on (the engine refuses)."""
    aito = RecordingAito()

    app_module._coldstart_evaluate_one(aito, "2022-06", "cost_center")

    (call,) = aito.calls
    assert call["test_where"] == {"order_month": {"$lte": "2022-06"}}
    assert call["limit"] < next(c["approx_rows"] for c in app_module.COLDSTART_CUTOFFS if c["cutoff"] == "2022-06")


needs_aito = pytest.mark.skipif(not os.environ.get("AITO_API_URL"),
                                reason="AITO_API_URL not set: live Aito tests are opt-in")


@needs_aito
def test_live_an_early_cutoff_learns_from_fewer_rows_and_scores_differently_than_the_full_history(app_module):
    from src.aito_client import AitoClient
    from src.config import load_config

    cfg = load_config()
    cred = cfg.creds_for("metsa")
    aito = AitoClient.from_creds(cred.api_url, cred.api_key, api_version=cfg.api_version)

    early = app_module._coldstart_evaluate_one(aito, "2022-09", "cost_center")
    late = app_module._coldstart_evaluate_one(aito, "2026-03", "cost_center")

    assert early["training_rows"] < late["training_rows"] / 5, (early, late)
    assert (early["accuracy"], early["base_accuracy"]) != (late["accuracy"], late["base_accuracy"])

"""The Cold Start slider answers "how good would Aito have been at that point in time".

`/api/coldstart/live?cutoff=2022-09` once returned the full-history accuracy at every cutoff
(td-20261030213014404900): the cutoff was in `evaluate.where`, which conditions the predicted row and
leaves the evidence untouched, so `_evaluate` learned from 3,073 rows at every position. A first fix
cut the evidence but tested on the history's earliest rows, so the model learned from later purchases
to predict earlier ones. The shape here: learn from the purchases up to the cutoff, test on the month
after it. `_evaluate` takes its test rows from inside the population it is given and holds them out,
so the population runs to the end of the test month and the training rows are exactly those up to the cutoff.
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
                "testSamples": 70}


@pytest.fixture
def positions(app_module):
    return app_module.COLDSTART_CUTOFFS


def run(app_module, cutoff: str, train_samples: int = 57):
    aito = RecordingAito(train_samples)
    result = app_module._coldstart_evaluate_one(aito, cutoff, "cost_center")
    (call,) = aito.calls
    return call, result


def test_every_test_row_is_dated_after_the_rows_the_model_learns_from(app_module, positions):
    for position in positions:
        call, _ = run(app_module, position["cutoff"])

        assert call["test_where"] == {"order_month": position["test_month"]}
        assert position["test_month"] > position["train_through"], position


def test_the_population_stops_at_the_end_of_the_test_month_so_nothing_later_is_learned_from(app_module, positions):
    for position in positions:
        call, _ = run(app_module, position["cutoff"])

        assert call["population_where"] == {"order_month": {"$lte": position["test_month"]}}


def test_the_test_month_is_the_one_right_after_the_training_history(app_module, positions):
    for position in positions:
        year, month = map(int, position["train_through"].split("-"))
        following = f"{year + (month == 12)}-{month % 12 + 1:02d}"

        assert position["test_month"] == following, position


def test_the_cutoff_is_not_a_condition_on_the_predicted_row(app_module):
    call, _ = run(app_module, "2022-09")

    assert not call.get("evaluate_extra_where"), "a cutoff in evaluate.where leaves the evidence uncut"


def test_the_cap_does_not_clip_a_month_of_purchases(app_module):
    """A month holds about 70 purchases; clipping it would make the test sample depend on table order."""
    call, _ = run(app_module, "2022-09")

    assert call["limit"] >= 100


def test_the_response_says_how_many_rows_it_learned_from_and_was_tested_on(app_module):
    _, result = run(app_module, "2022-09", train_samples=281)

    assert result["training_rows"] == 281
    assert "total_cases" in result


needs_aito = pytest.mark.skipif(not os.environ.get("AITO_API_URL"),
                                reason="AITO_API_URL not set: live Aito tests are opt-in")


def live_aito():
    from src.aito_client import AitoClient
    from src.config import load_config

    cfg = load_config()
    cred = cfg.creds_for("metsa")
    return AitoClient.from_creds(cred.api_url, cred.api_key, api_version=cfg.api_version)


@needs_aito
def test_live_the_model_learns_from_exactly_the_purchases_up_to_each_cutoff(app_module, positions):
    aito = live_aito()
    for position in positions:
        up_to_cutoff = aito.search("purchases", where={"order_month": {"$lte": position["train_through"]}},
                                   limit=0)["total"]

        result = app_module._coldstart_evaluate_one(aito, position["cutoff"], "cost_center")

        assert result["training_rows"] == up_to_cutoff, (position, result)


@needs_aito
def test_live_an_early_cutoff_learns_from_far_fewer_rows_and_scores_differently(app_module):
    aito = live_aito()

    early = app_module._coldstart_evaluate_one(aito, "2022-09", "account_code")
    late = app_module._coldstart_evaluate_one(aito, "2026-03", "account_code")

    assert early["training_rows"] < late["training_rows"] / 5, (early, late)
    assert (early["accuracy"], early["base_accuracy"]) != (late["accuracy"], late["base_accuracy"])

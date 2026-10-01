"""A failed match is shown as a failure, never as "no candidates".

Found pre-registering the dragon hunt (docs/notes/dragon-hunt-demo-path-
preregistration.md, findings 2 and 3). `rank_line` caught every
AitoError and returned an empty shortlist, so an engine 500 rendered as
a line Aito had no opinion on, and it scored as a miss in the batch's
accuracy. It also dropped any hit without a `$value`, so a malformed
answer shrank the shortlist without a word. The planner was fixed for
the same pattern; this is the matcher's turn.
"""

import pytest

from src.aito_client import AitoError
from src.matching_service import MalformedAnswer, rank_line, run_batch

LINE = {"line_id": "TST-1", "invoice_id": "INV-1", "billing_supplier": "Vendor Oy",
        "description": "Ruusu punainen 40cm", "quantity": 2, "sku": "SKU-1"}


class _Client:
    api_version = "v2"

    def __init__(self, answer=None, fail_on=()):
        self.answer, self.fail_on = answer, set(fail_on)

    def predict(self, table, where, field, **kwargs):
        if where.get("description") in self.fail_on:
            raise AitoError("Aito v2 returned 500 [internal]")
        return self.answer or {"hits": [{"$value": "SKU-1", "$p": 0.9, "name": "Ruusu"}]}


def test_an_engine_error_is_raised_not_an_empty_shortlist():
    with pytest.raises(AitoError):
        rank_line(_Client(fail_on={LINE["description"]}), LINE)


def test_a_hit_without_a_sku_is_a_malformed_answer_not_a_shorter_list():
    answer = {"hits": [{"$value": "SKU-1", "$p": 0.6}, {"$value": None, "$p": 0.3}]}
    with pytest.raises(MalformedAnswer, match="without a sku"):
        rank_line(_Client(answer), LINE)


def test_a_failed_line_shows_as_an_error_and_is_not_scored():
    other = {**LINE, "line_id": "TST-2", "description": "Tulppaani keltainen"}
    result = run_batch(_Client(fail_on={other["description"]}), [LINE, other], workers=2).to_dict()
    failed = next(x for x in result["lines"] if x["line_id"] == "TST-2")
    assert failed["decision"] == "error" and "500" in failed["error"]
    assert failed["correct"] is None, "a failure is not a miss"
    assert result["batch"]["errors"] == 1
    assert result["batch"]["top1"] == 1.0, "accuracy is over the lines that were answered"
    ok = next(x for x in result["lines"] if x["line_id"] == "TST-1")
    assert ok["error"] is None and ok["candidates"]

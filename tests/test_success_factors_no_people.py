"""The Success factors panel lists properties of the work, never people.

It used to relate `assignments.person` and `projects.manager`, which put
named colleagues in a ranked list of what goes with success. Antti: "The
success predictor list should not contain people names." It now relates
project type, priority and the five outcome drivers, and a failing
relate is an error rather than a silently shorter list.
"""

import pytest

from src.aito_client import AitoError
from src.project_service import _PROJECT_FACTOR_FIELDS, _success_factors


class _Relate:
    def __init__(self, fail_on=None):
        self.asked, self.fail_on = [], fail_on

    def relate(self, table, where, field, limit=None):
        self.asked.append((table, field))
        if field == self.fail_on:
            raise AitoError("Aito v2 returned 500")
        return {"hits": [{"related": {field: "x"}, "lift": 1.4,
                          "fs": {"f": 40, "fOnCondition": 30, "fCondition": 100, "n": 200},
                          "ps": {"p": 0.2, "pOnCondition": 0.3, "pOnNotCondition": 0.1}}]}


def test_only_properties_of_the_work_are_related():
    client = _Relate()
    factors = _success_factors(client)
    assert {t for t, _ in client.asked} == {"projects"}
    fields = {f for _, f in client.asked}
    assert not fields & {"person", "manager", "team_lead", "team_members"}
    assert fields == {f for f, _ in _PROJECT_FACTOR_FIELDS}
    assert all(f.kind not in ("person", "manager") for f in factors)


def test_a_failed_relate_is_an_error_not_a_shorter_list():
    with pytest.raises(AitoError):
        _success_factors(_Relate(fail_on="scope_clarity"))

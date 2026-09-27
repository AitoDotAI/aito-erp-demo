"""Supplier delivery risk: the number shown has to be the one described.

`_relate` over `where={delivery_late: true}`, `relate=supplier` reports
`ps.pOnCondition` = P(supplier | late) — the supplier's SHARE of all late
deliveries. The view labelled that "late rate". A big supplier therefore
looked like the worst performer: Neste read 19.4% "late" because 31 of the
160 late deliveries were theirs, while its real late rate is 31/477 = 6.5%.
NCC Suomi, the supplier the lift ranking correctly put first, read 5.6%.

The hits below are real responses from env.master, trimmed.
"""

from src.supplier_service import _classify_risk, get_delivery_risk

_NCC = {"related": {"supplier": {"$has": "NCC Suomi"}}, "lift": 1.52,
        "ps": {"p": 0.027, "pOnCondition": 0.056, "pOnNotCondition": 0.026},
        "fs": {"f": 89.0, "fOnCondition": 9.0, "fCondition": 160.0, "n": 3273.0}}
_NESTE = {"related": {"supplier": {"$has": "Neste Oyj"}}, "lift": 1.16,
          "ps": {"p": 0.146, "pOnCondition": 0.194, "pOnNotCondition": 0.143},
          "fs": {"f": 477.0, "fOnCondition": 31.0, "fCondition": 160.0, "n": 3273.0}}
_ONE_LATE = {"related": {"supplier": {"$has": "Siemens Finland"}}, "lift": 2.4,
             "ps": {"pOnCondition": 0.006}, "fs": {"f": 20.0, "fOnCondition": 1.0}}


class _Relate:
    def __init__(self, hits): self.hits = hits
    def relate(self, table, where, field): return {"hits": self.hits}


def _by_name(hits):
    return {r.supplier: r for r in get_delivery_risk(_Relate(hits))}


def test_late_rate_is_late_deliveries_over_the_suppliers_own_deliveries():
    risks = _by_name([_NCC, _NESTE])
    assert risks["NCC Suomi"].late_rate == round(9 / 89, 3)
    assert risks["Neste Oyj"].late_rate == round(31 / 477, 3)


def test_the_riskiest_supplier_also_has_the_highest_late_rate():
    """The contradiction a reader spots first: the risk ordering and the
    late-rate column must not disagree."""
    risks = get_delivery_risk(_Relate([_NESTE, _NCC]))
    assert risks[0].supplier == "NCC Suomi"
    assert risks[0].late_rate == max(r.late_rate for r in risks)


def test_one_late_delivery_is_not_a_high_risk_however_large_the_lift():
    """Lift on one event is noise. The rule needs evidence as well as lift."""
    assert _by_name([_ONE_LATE])["Siemens Finland"].risk_level == "low"


def test_the_rule_is_defined_on_lift_and_evidence():
    assert _classify_risk(lift=2.1, late=6) == "high"
    assert _classify_risk(lift=1.52, late=9) == "medium"
    assert _classify_risk(lift=1.16, late=31) == "low"
    assert _classify_risk(lift=3.0, late=1) == "low"

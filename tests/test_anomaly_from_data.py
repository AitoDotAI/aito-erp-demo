"""Anomalies: every figure about a flagged row comes from the data.

The flagged rows used to carry their conclusions typed in — "~€2,400
avg" for Neste when its history averages ~€3,000, "unknown vendor, first
PO" for Bauhaus with 170 POs on file — and scores came from made-up
curves (a fixed 0.02 / 0.15, 0.60/ratio, residual × 0.05). A CTO checks
one supplier and the whole view stops being believable. Here the seed
row is only the incoming transaction; the expected value, the
explanation and the score are computed.
"""

import pytest

from src.anomaly_service import DEMO_ANOMALIES_BY_TENANT, evaluate_transaction


class _History:
    """`search` answers from in-memory purchases; `predict` returns set hits."""

    def __init__(self, rows, hits=None):
        self.rows, self.hits = rows, hits or []

    def search(self, table, where, limit=10):
        rows = [r for r in self.rows if all(r.get(k) == v for k, v in where.items())]
        return {"total": len(rows), "hits": rows[:limit]}

    def predict(self, table, where, field, limit=10):
        return {"hits": self.hits[:limit]}


def _po(**over):
    return {"purchase_id": "PO-1", "supplier": "Neste Oyj", "amount": 9800.0,
            "account_code": "4310", **over}


def test_a_mis_coded_account_is_judged_against_aitos_own_expectation():
    client = _History([{"supplier": "Fazer"}] * 5, hits=[{"$value": "5710", "$p": 0.80}, {"$value": "4220", "$p": 0.03}])
    flag = evaluate_transaction(client, _po(supplier="Fazer", account_code="4220",
                                            flagged_field="account_code"))
    assert flag.expected_value == "5710"
    assert flag.actual_value == "4220"
    assert flag.anomaly_score == 97
    assert "5710" in flag.explanation and "3%" in flag.explanation


def test_an_account_below_every_listed_prediction_is_scored_by_the_bound():
    """Not in the list means its probability is at most the smallest one
    listed — a bound, not a formula."""
    hits = [{"$value": "5710", "$p": 0.90}, {"$value": "4010", "$p": 0.06}, {"$value": "6810", "$p": 0.04}]
    flag = evaluate_transaction(_History([{"supplier": "Neste Oyj"}] * 5, hits=hits),
                                _po(account_code="9999", flagged_field="account_code"))
    assert flag.anomaly_score == 96
    assert "at most 4%" in flag.explanation


def test_an_amount_is_compared_with_the_suppliers_whole_history():
    """The first 50 rows are not the supplier's average."""
    history = ([{"supplier": "Neste Oyj", "amount_eur": 1000.0}] * 50
               + [{"supplier": "Neste Oyj", "amount_eur": 4000.0}] * 30)
    flag = evaluate_transaction(_History(history), _po(flagged_field="amount"))
    assert "80" in flag.explanation            # POs it rests on
    assert "2" in flag.expected_value and "125" in flag.expected_value   # €2 125, locale-formatted
    assert flag.anomaly_score == 99            # none of 80 this large: 1/81


def test_an_amount_score_is_the_share_of_past_pos_this_large():
    history = [{"supplier": "Neste Oyj", "amount_eur": a} for a in [1000.0] * 18 + [12000.0] * 2]
    flag = evaluate_transaction(_History(history), _po(flagged_field="amount"))
    # 2 of 20 at least as large → p = 3/21 → score 86
    assert flag.anomaly_score == 86


def test_a_new_vendor_claim_is_checked_against_the_history():
    history = [{"supplier": "Bauhaus", "amount_eur": 100.0}] * 170
    with pytest.raises(ValueError, match="170"):
        evaluate_transaction(_History(history), _po(supplier="Bauhaus", flagged_field="supplier"))


def test_a_vendor_with_no_history_says_how_much_history_there_is():
    history = [{"supplier": "Someone Else", "amount_eur": 100.0}] * 3272
    flag = evaluate_transaction(_History(history),
                                _po(supplier="Harjula Consulting", flagged_field="supplier"))
    assert flag.anomaly_score == 100
    assert "0 of" in flag.explanation and "3" in flag.explanation


def test_the_seed_rows_carry_no_conclusions():
    """Only the incoming transaction is written down; the rest is computed."""
    for tenant, rows in DEMO_ANOMALIES_BY_TENANT.items():
        for row in rows:
            leaked = {"expected_value", "actual_value", "explanation"} & set(row)
            assert not leaked, f"{tenant} {row['purchase_id']} carries {leaked}"


def test_an_account_cannot_be_unusual_for_a_supplier_with_no_history():
    """Metsä's example named Fazer Food Services, which has no purchases
    there: Aito answered from its prior (21% vs 20%) and the page called
    it a mis-coding."""
    client = _History([], hits=[{"$value": "6120", "$p": 0.21}, {"$value": "4220", "$p": 0.20}])
    with pytest.raises(ValueError, match="no purchases on file"):
        evaluate_transaction(client, _po(supplier="Fazer Food Services", account_code="4220",
                                         flagged_field="account_code"))


def test_a_tiny_probability_reads_as_below_one_percent_not_zero():
    client = _History([{"supplier": "Valio"}] * 5,
                      hits=[{"$value": "4010", "$p": 0.93}, {"$value": "4030", "$p": 0.002}])
    flag = evaluate_transaction(client, _po(supplier="Valio", account_code="4030",
                                            flagged_field="account_code"))
    assert "<1%" in flag.explanation and " 0%" not in flag.explanation

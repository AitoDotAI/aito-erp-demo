"""Invoice-line matching: the parts that are decisions, not queries.

The query itself is exercised by `./do match-eval` against held-out
data — that is where "is it any good" gets answered. What is worth
pinning here is the reasoning around it: that a chip says who made the
claim, that a routing decision follows the confidence, and that the
held-out label is scored rather than assumed.
"""

from src.matching_service import (
    MEASURED, PRESELECT_THRESHOLD, BatchResult, Candidate, MatchedLine,
    _reasons, _terms,
)


def _hit(p: float, why: dict | None = None, **row) -> dict:
    return {"$p": p, "$value": row.get("sku", "SKU-1"), "$why": why, **row}


def _lift(field: str, html: str, value: float) -> dict:
    return {"type": "relatedPropositionLift", "value": value,
            "proposition": {field: {"$has": "x"}},
            "highlight": [{"field": f"$context.{field}", "highlight": html}]}


def test_highlighted_terms_are_unescaped():
    """The highlight arrives as markup. A chip reading `L'Or&eacute;al`
    tells a viewer the demo is broken, not that the match was good."""
    assert _terms("«L'Or&eacute;al» Finland") == ["L'Oréal"]
    assert _terms("no markers here") == []


def test_a_chip_says_who_made_the_claim():
    """Three kinds, and conflating them is the failure this repo is
    under a ticket about: `aito` is evidence the database put forward,
    `against` is evidence it weighed the other way, `match` is computed
    in the service and argued by nobody."""
    why = {"factors": [
        {"type": "baseP", "value": 0.01, "proposition": {"sku": "SKU-1"}},
        _lift("description", "«Laundry» «Detergent»", 24.0),
        _lift("billing_supplier", '<font color="red">Uusi Kanava</font>', 0.6),
    ]}
    line = {"unit_of_measure": "L", "unit_price_eur": 47.0}
    hit = _hit(0.5, why, sku="SKU-1", unit_of_measure="L", unit_price=45.9)

    reasons = _reasons(hit, line)
    kinds = {r["kind"] for r in reasons}
    assert kinds == {"aito", "against", "match"}

    aito = next(r for r in reasons if r["kind"] == "aito")
    assert aito["text"] == '"Laundry" · "Detergent"'
    against = next(r for r in reasons if r["kind"] == "against")
    assert against["field"] == "billing_supplier"
    # Unit and price agree, and neither is something Aito argued.
    assert {r["text"] for r in reasons if r["kind"] == "match"} == {
        "unit L", "price within 2% of list"}


def test_a_matched_term_outside_the_description_carries_its_field():
    """`"6"` as a bare chip tells nobody anything. Out of the free-text
    field a quoted word explains itself; out of `quantity` it does not."""
    why = {"factors": [_lift("quantity", "«6»", 3.0)]}
    reasons = _reasons(_hit(0.2, why), {})
    assert reasons[0]["text"] == "quantity 6"


def test_price_agreement_needs_the_prices_to_agree():
    """The invoiced price drifts from list on purpose in the fixture, so
    the chip has to be earned rather than always present."""
    line = {"unit_price_eur": 299.47}
    assert not [r for r in _reasons(_hit(0.1, None, unit_price=84.51), line)
                if r["field"] == "unit_price"]


def _line(p: float, sku: str, truth: str, name: str = "n",
          truth_name: str | None = None) -> MatchedLine:
    return MatchedLine(
        line_id="L", invoice_id="I", billing_supplier="S", description="d",
        quantity=1, unit_of_measure="ea", unit_price_eur=1.0,
        line_amount_eur=1.0, ms=100.0, truth=truth, truth_name=truth_name,
        candidates=[Candidate(sku=sku, name=name, category=None, supplier=None,
                              unit_price=None, unit_of_measure=None, p=p)])


def test_confidence_decides_whether_the_top_pick_is_pre_filled():
    """Both branches end in front of a human. Above the bar the top
    candidate arrives already chosen; below it the shortlist arrives
    open. Neither posts an invoice line unattended, because the
    measured precision does not support one."""
    assert _line(PRESELECT_THRESHOLD + 0.01, "SKU-1", "SKU-1").decision == "prefilled"
    assert _line(PRESELECT_THRESHOLD - 0.01, "SKU-1", "SKU-1").decision == "open"
    # No candidate at all stays open rather than silently passing.
    bare = _line(0.9, "SKU-1", "SKU-1")
    bare.candidates = []
    assert bare.decision == "open"


def test_the_threshold_is_read_off_the_measured_curve():
    """The bar is not a taste decision. If someone moves it, the number
    the view quotes beside it has to still be a measured one — a
    threshold with no row in the table is a threshold nobody checked."""
    bars = [row["bar"] for row in MEASURED["curve"]]
    assert PRESELECT_THRESHOLD in bars, (
        f"PRESELECT_THRESHOLD={PRESELECT_THRESHOLD} has no measured row. "
        f"Re-run `./do match-eval` and add it to MEASURED['curve'].")


def test_the_batch_scores_what_it_pre_filled():
    """Coverage without precision is the misleading half of the pair —
    "we pre-filled 40% of your invoice lines" means nothing until you
    say how often the 40% was right."""
    result = BatchResult(
        lines=[_line(0.9, "SKU-1", "SKU-1"),   # pre-filled, right
               _line(0.9, "SKU-2", "SKU-9"),   # pre-filled, wrong
               _line(0.1, "SKU-3", "SKU-3")],  # open, right
        wall_s=3.0, workers=2, server_ms_median=100.0)
    batch = result.to_dict()["batch"]
    assert batch["prefilled"] == 2 and batch["open"] == 1
    assert batch["prefill_precision"] == 0.5
    assert batch["top1"] == round(2 / 3, 3)
    assert batch["rows_per_s"] == 1.0


def test_a_line_is_marked_against_its_held_out_label():
    """These lines were never loaded, so there IS a right answer and the
    view shows it. A queue in production has no truth column; a demo
    that hides the one it has is asking to be trusted."""
    assert _line(0.5, "SKU-1", "SKU-1").to_dict()["correct"] is True
    assert _line(0.5, "SKU-1", "SKU-2").to_dict()["correct"] is False


def test_a_pick_the_catalogue_calls_the_same_thing_is_its_own_outcome():
    """Half this catalogue shares a name with another row. Marking such
    a pick wrong overstates the failure; counting it correct overstates
    the success. It gets a third outcome and never the first."""
    twin = _line(0.5, "SKU-1", "SKU-2", name="Tape Measure 10pk",
                 truth_name="Tape Measure 10pk").to_dict()
    assert twin["same_name"] is True and twin["correct"] is False

    other = _line(0.5, "SKU-1", "SKU-2", name="Kettle 1.7L",
                  truth_name="Tape Measure 10pk").to_dict()
    assert other["same_name"] is False

    # An exact hit is never also "same name" — that would double-count
    # it in any tally built off these flags.
    exact = _line(0.5, "SKU-1", "SKU-1", name="Kettle 1.7L",
                  truth_name="Kettle 1.7L").to_dict()
    assert exact["correct"] is True and exact["same_name"] is False

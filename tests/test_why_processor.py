"""Tests for `$why` proposition rendering.

These strings land in the WhyTooltip, so an unhandled operator is
visible to a demo visitor as a raw Python dict — which is how v2's
`$group` was caught. See docs/v2-migration.md.
"""

from src.why_processor import _proposition_to_string


def test_field_clause():
    assert _proposition_to_string({"supplier": {"$has": "Telia"}}) == "supplier has Telia"


def test_and_clause():
    prop = {"$and": [{"supplier": {"$has": "Telia"}},
                     {"category": {"$is": "telecom"}}]}
    assert _proposition_to_string(prop) == "supplier has Telia AND category is telecom"


def test_v2_match_operator():
    """v2 conditions text evidence with `$match` where v1 used `$has`."""
    assert (_proposition_to_string({"description": {"$match": "pump"}})
            == "description matches pump")


def test_v2_group_is_not_rendered_as_a_conjunction():
    """`$group` votes as one correlated theme, not as independent AND."""
    prop = {"$group": [{"description": "Cleaning"},
                       {"description": "chemicals"},
                       {"supplier": "Berner Oy"}]}
    rendered = _proposition_to_string(prop)
    assert rendered == "description = Cleaning + description = chemicals + supplier = Berner Oy"
    assert "AND" not in rendered
    assert "{" not in rendered


# ── The $why-belongs-to-its-row invariant ────────────────────────────
#
# From org/demo-why-integrity-audit.md, opened after the accounting demo
# showed a prospect explanations belonging to a different row than the
# match on screen. An accuracy evaluation would not have caught it: the
# answer was scored, the explanation was not. This is the control.


def _why_for(value, operator_wrapped=True):
    """A minimal `$why` tree whose baseP names `value`."""
    target = {"$has": value} if operator_wrapped else value
    return {
        "type": "product",
        "factors": [
            {"type": "baseP", "value": 0.02, "proposition": {"sku": target}},
            {"type": "relatedPropositionLift", "value": 3.1,
             "proposition": {"description": {"$has": "Tote"}}},
        ],
    }


def test_why_target_reads_the_baseP_proposition():
    """v1 wraps the target in the operator that matched it; v2 leaves it
    bare. Both name the same candidate."""
    from src.why_processor import why_target

    assert why_target(_why_for("SKU-1234")) == "SKU-1234"
    assert why_target(_why_for("SKU-1234", operator_wrapped=False)) == "SKU-1234"
    assert why_target(None) is None
    assert why_target({"type": "product", "factors": []}) is None


def test_why_target_finds_a_nested_baseP():
    """The tree nests products inside products; baseP is not always at
    the top level."""
    from src.why_processor import why_target

    nested = {"type": "product",
              "factors": [{"type": "product",
                           "factors": [_why_for("SKU-9")]}]}
    assert why_target(nested) == "SKU-9"


def test_an_explanation_for_another_row_is_refused():
    """The exact 4.9 defect: code substitutes a different row and carries
    the discarded row's `$why` across. It must fail loudly rather than
    render authoritative-looking evidence for a match never made."""
    import pytest
    from src.why_processor import assert_why_belongs_to

    # The honest case passes.
    assert_why_belongs_to(_why_for("SKU-1234"), "SKU-1234", "test")

    with pytest.raises(ValueError, match="must belong to the row"):
        assert_why_belongs_to(_why_for("SKU-1234"), "SKU-9999", "test")


def test_nothing_to_check_is_not_a_failure():
    """A prediction without `$why` selected, or a tree with no baseP, is
    not a violation — there is simply no claim to verify."""
    from src.why_processor import assert_why_belongs_to

    assert_why_belongs_to(None, "SKU-1", "test")
    assert_why_belongs_to({"type": "product", "factors": []}, "SKU-1", "test")
    assert_why_belongs_to(_why_for("SKU-1"), None, "test")


def test_the_client_enforces_it_on_every_prediction():
    """Wired into `AitoClient.predict`, which is the one place every
    prediction in this repo passes through — so a new ranked view cannot
    add explanations and forget the check."""
    import pytest
    from src.aito_client import _assert_why_integrity

    good = {"hits": [{"$value": "SKU-1", "$why": _why_for("SKU-1")},
                     {"$value": "SKU-2", "$why": _why_for("SKU-2")}]}
    assert _assert_why_integrity(good, "invoice_lines", "sku") is good

    swapped = {"hits": [{"$value": "SKU-1", "$why": _why_for("SKU-2")}]}
    with pytest.raises(ValueError, match=r"\$why integrity"):
        _assert_why_integrity(swapped, "invoice_lines", "sku")

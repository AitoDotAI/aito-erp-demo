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

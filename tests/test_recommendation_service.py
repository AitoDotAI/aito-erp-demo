"""Cross-sell: "bought together" means MORE likely given the anchor.

Two earlier versions answered other questions. Goal `_recommend` over
impressions ranked products seen once or twice anywhere above ones
bought with the anchor hundreds of times (aito-core#1525). A
non-exclusive `_predict products.$feature` answered "how likely is X in
this basket", which fills every list with the store's best-sellers.
`_relate` over `baskets` answers the cross-sell question — lift — and
carries the counts that say what each ratio rests on.

The stub answers the way v2 does after `AitoClient` has unwrapped the
feature form: `related` is the bare SKU.
"""

import pytest

from src.aito_client import AitoError, _canonical_relate_hits
from src.recommendation_service import MIN_TOGETHER, get_cross_sell

_PRODUCTS = {
    "SKU-2": {"sku": "SKU-2", "name": "Wrench Set", "category": "DIY", "supplier": "Bauhaus", "unit_price": 20.0},
    "SKU-3": {"sku": "SKU-3", "name": "Paint Roller", "category": "DIY", "supplier": "Tikkurila", "unit_price": 9.0},
    "SKU-4": {"sku": "SKU-4", "name": "Tape Measure", "category": "DIY", "supplier": "Bauhaus", "unit_price": 7.0},
}


def _hit(sku, lift, together, anchor_baskets=21):
    return {"related": {"products": sku}, "lift": lift,
            "fs": {"fOnCondition": together, "fCondition": anchor_baskets, "f": 100, "n": 8000}}


class _Baskets:
    def __init__(self, hits):
        self.hits, self.asked = hits, []

    def relate(self, table, where, field, limit=None):
        self.asked.append((table, where, field, limit))
        return {"hits": self.hits}

    def search(self, table, where, limit=10):
        row = _PRODUCTS.get(where.get("sku"))
        return {"hits": [row] if row else []}


def test_the_question_is_lift_over_baskets_containing_the_anchor():
    client = _Baskets([_hit("SKU-1", 380.0, 21), _hit("SKU-2", 30.7, 17), _hit("SKU-3", 27.8, 3)])
    items = get_cross_sell(client, "SKU-1")
    table, where, field, _ = client.asked[0]
    assert (table, where, field) == ("baskets", {"products": {"$has": "SKU-1"}}, "products")
    assert [i.sku for i in items] == ["SKU-2", "SKU-3"], "the anchor relates to itself and says nothing"


def test_a_pairing_on_too_few_baskets_is_not_listed():
    """A lift of 180x on two shared baskets is two coincidences."""
    items = get_cross_sell(_Baskets([_hit("SKU-2", 180.0, MIN_TOGETHER - 1), _hit("SKU-3", 6.0, 12)]), "SKU-1")
    assert [i.sku for i in items] == ["SKU-3"]


def test_each_row_carries_the_counts_behind_its_ratio():
    item = get_cross_sell(_Baskets([_hit("SKU-2", 30.7, 17, 21)]), "SKU-1")[0]
    assert (item.lift, item.together, item.anchor_baskets, item.name) == (30.7, 17, 21, "Wrench Set")


def test_rows_are_ranked_by_lift_not_by_count():
    """Counting alone ranks best-sellers first; lift ranks what the anchor pulls in."""
    items = get_cross_sell(_Baskets([_hit("SKU-2", 2.0, 40), _hit("SKU-4", 12.0, 5)]), "SKU-1")
    assert [i.sku for i in items] == ["SKU-4", "SKU-2"]


def test_a_basket_product_missing_from_the_catalogue_is_loud():
    with pytest.raises(RuntimeError, match="not in products"):
        get_cross_sell(_Baskets([_hit("SKU-99", 5.0, 9)]), "SKU-1")


def test_an_engine_error_surfaces_rather_than_reading_as_no_suggestions():
    class _Failing(_Baskets):
        def relate(self, *a, **kw):
            raise AitoError("Aito v2 returned 500 [internal]")
    with pytest.raises(AitoError):
        get_cross_sell(_Failing([]), "SKU-1")


def test_v2_answers_an_array_member_as_a_feature_and_the_client_unwraps_it():
    """On v2 a distinct value comes back bare, but a member of a String[]
    is a FEATURE and comes back as {"$has": ...} — correct, and a caller
    that read only the bare form would find a dict where a SKU belongs."""
    response = {"hits": [{"related": {"products": {"$has": "SKU-2"}}, "lift": 3.0,
                          "fs": {"f": 10, "fOnCondition": 5, "fCondition": 20, "n": 100}},
                         {"related": {"supplier": "Neste Oyj"}, "lift": 1.2,
                          "fs": {"f": 10, "fOnCondition": 2, "fCondition": 20, "n": 100}}]}
    hits = _canonical_relate_hits(response, "v2")["hits"]
    assert [h["related"] for h in hits] == [{"products": "SKU-2"}, {"supplier": "Neste Oyj"}]

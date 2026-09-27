"""Cross-sell: what the engine answers has to reach the screen.

On v2, a `_recommend` over a link returns `$p` and `$value` per hit and
nothing else unless the columns are named in `select`. The service read
`hit["sku"]`, found None on every hit and skipped them all, so "frequently
bought together" was empty for every product in production — while the
query itself was answering correctly. A blanket `except` made sure nothing
said so either.

The stub below answers in the v2 shape: columns only when selected.
"""

import pytest

from src.aito_client import AitoError
from src.recommendation_service import get_cross_sell

_ROWS = {
    "SKU-2": {"name": "Glass Set", "category": "Homeware",
              "supplier": "Tikkurila", "unit_price": 23.12},
    "SKU-3": {"name": "Candle", "category": "Homeware",
              "supplier": "Tikkurila", "unit_price": 9.5},
}


class _V2Recommend:
    """Answers like rep2: `$p` + `$value`, plus exactly the selected columns."""

    def __init__(self):
        self.select = None

    def recommend(self, table, where, recommend_field, goal, select=None, limit=8):
        self.select = select
        hits = []
        for sku, p in (("SKU-1", 0.9), ("SKU-2", 0.8), ("SKU-3", 0.7)):
            hit = {"$p": p, "$value": sku}
            for col in select or []:
                if col in _ROWS.get(sku, {}):
                    hit[col] = _ROWS[sku][col]
            hits.append(hit)
        return {"hits": hits}


class _Failing:
    def recommend(self, *a, **kw):
        raise AitoError("Aito v2 returned 500 [internal]: NoSuchElementException")


def test_the_engine_answer_reaches_the_list():
    """The regression itself: three hits in, the anchor dropped, two out."""
    items = get_cross_sell(_V2Recommend(), "SKU-1")
    assert [i.sku for i in items] == ["SKU-2", "SKU-3"], (
        "the engine returned ranked products and the list is empty or wrong — "
        "the sku lives in `$value`, not in a `sku` column")


def test_product_columns_are_asked_for_by_name():
    """Without an explicit select, v2 returns no product columns at all."""
    client = _V2Recommend()
    items = get_cross_sell(client, "SKU-1")
    assert client.select and {"$p", "$value", "name"} <= set(client.select)
    assert items[0].name == "Glass Set" and items[0].unit_price == 23.12


def test_an_engine_error_surfaces_rather_than_reading_as_no_suggestions():
    """An empty list says "nothing is bought with this". A failed query
    has not said that, and the view must not claim it did."""
    with pytest.raises(AitoError):
        get_cross_sell(_Failing(), "SKU-1")

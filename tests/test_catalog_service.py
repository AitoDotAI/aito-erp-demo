"""Catalog enrichment: say what the database knows, and how.

`unit_price` and `weight_kg` are continuous. They were filled with
`_predict`, which scores exact values, so the view offered "weight_kg:
0.63 (0%)" — a probability that any number is exactly right, which is
always near zero and tells the reader nothing. A number comes from
`_estimate` and is shown as an estimate.

And a field that no product in the category carries is not missing, it
does not apply: an hour of electrical inspection has no weight, and the
view invented 4.87 kg for one.
"""

from src.catalog_service import predict_attributes

_PRODUCT = {"sku": "SKU-1", "name": "Electrical Inspection (hr)", "supplier": "Vesto",
            "category": "Maintenance Services", "unit_price": None, "hs_code": None,
            "unit_of_measure": "hr", "weight_kg": None, "account_code": None,
            "tax_class": None}
_PEERS = [  # the category: priced and taxed, never weighed, never HS-coded
    {"category": "Maintenance Services", "unit_price": 120.0, "weight_kg": None,
     "hs_code": None, "account_code": "4220", "tax_class": "Standard"},
    {"category": "Maintenance Services", "unit_price": 95.0, "weight_kg": None,
     "hs_code": None, "account_code": "4220", "tax_class": "Standard"},
]


class _Stub:
    api_version = "v2"

    def __init__(self):
        self.predicted, self.estimated = [], []

    def search(self, table, where, limit=10):
        if where.get("sku"):
            return {"hits": [dict(_PRODUCT)]}
        return {"hits": list(_PEERS)}

    def predict(self, table, where, field, limit=10):
        self.predicted.append(field)
        return {"hits": [{"$p": 0.9, "$value": "4220" if field == "account_code" else "Standard"}]}

    def estimate(self, table, where, field, select=None):
        self.estimated.append(field)
        return {"estimate": 107.5, "why": {"components": [{}, {}]}}


def _by_field(stub):
    return {p.field_name: p for p in predict_attributes(stub, "SKU-1").predictions}


def test_a_number_is_estimated_and_carries_no_fake_confidence():
    stub = _Stub()
    price = _by_field(stub)["unit_price"]
    assert "unit_price" in stub.estimated and "unit_price" not in stub.predicted
    assert price.kind == "estimate"
    assert price.confidence is None
    assert float(price.predicted_value) == 107.5


def test_a_field_the_category_never_has_is_not_applicable_not_invented():
    stub = _Stub()
    by = _by_field(stub)
    assert by["weight_kg"].kind == "not_applicable"
    assert by["hs_code"].kind == "not_applicable"
    assert "weight_kg" not in stub.estimated and "hs_code" not in stub.predicted


def test_a_categorical_field_is_still_predicted_with_its_probability():
    by = _by_field(_Stub())
    assert by["account_code"].kind == "predict"
    assert by["account_code"].predicted_value == "4220"
    assert by["account_code"].confidence == 0.9


def test_a_raw_number_is_never_used_as_context():
    """A product's own unit_price (1256.54) in the `where` was matched as
    an EXACT categorical value. Nothing matches it, so `_estimate` fell
    back to zero-similarity rows and every weight came out 0.05 — a
    speaker, dishwasher tablets and a storage box alike."""
    seen = []

    class _Recording(_Stub):
        def search(self, table, where, limit=10):
            if where.get("sku"):
                return {"hits": [dict(_PRODUCT, unit_price=1256.54, category="Electronics",
                                      weight_kg=None)]}
            return {"hits": [{"category": "Electronics", "weight_kg": 3.0, "unit_price": 99.0,
                              "hs_code": "8528.72", "account_code": "4520", "tax_class": "Standard"}]}

        def estimate(self, table, where, field, select=None):
            seen.append(where)
            return super().estimate(table, where, field, select)

        def predict(self, table, where, field, limit=10):
            seen.append(where)
            return super().predict(table, where, field, limit)

    predict_attributes(_Recording(), "SKU-1")
    assert seen, "nothing was queried"
    for where in seen:
        assert "unit_price" not in where and "weight_kg" not in where, where


def test_a_product_is_never_its_own_neighbour():
    """`sku` (and for an estimate, `name`) identify the row itself. With
    either in the `where`, the nearest neighbour is the product being
    enriched, still blank in the field we ask about — and the estimate
    collapsed to one value for every product."""
    calls = {"estimate": [], "predict": []}

    class _Recording(_Stub):
        def search(self, table, where, limit=10):
            if where.get("sku"):
                return {"hits": [dict(_PRODUCT, category="Electronics", tax_class=None)]}
            return {"hits": [{"category": "Electronics", "weight_kg": 3.0, "unit_price": 99.0,
                              "tax_class": "Standard", "account_code": "4520", "hs_code": "8528"}]}

        def estimate(self, table, where, field, select=None):
            calls["estimate"].append(where)
            return super().estimate(table, where, field, select)

        def predict(self, table, where, field, limit=10):
            calls["predict"].append(where)
            return super().predict(table, where, field, limit)

    predict_attributes(_Recording(), "SKU-1")
    assert calls["estimate"] and calls["predict"], calls
    for where in calls["estimate"]:
        assert "sku" not in where and "name" not in where, where
    for where in calls["predict"]:
        assert "sku" not in where, where
        assert "name" in where, "the name's words are evidence for a category"

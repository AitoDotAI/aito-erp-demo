"""Tests for the Aito HTTP client."""

import pytest
from src.aito_client import AitoClient, AitoError
from src.config import Config


def _make_client(api_version="v1"):
    # The unit tests don't exercise multi-tenant routing; from_creds
    # bypasses Config and avoids needing to fill in the tenants dict.
    return AitoClient.from_creds("https://test.aito.app", "test-key",
                                 api_version=api_version)


def test_url_construction():
    client = _make_client()
    assert client._url("/schema") == "https://test.aito.app/api/v1/schema"
    assert client._url("/_predict") == "https://test.aito.app/api/v1/_predict"


def test_url_construction_v2():
    client = _make_client("v2")
    assert client._url("/_predict") == "https://test.aito.app/api/v2/_predict"


def test_predict_query_shape(httpx_mock):
    """_predict should send correct query structure."""
    httpx_mock.add_response(json={"hits": [{"$p": 0.9, "feature": "IT"}]})
    client = _make_client()
    result = client.predict("purchases", {"supplier": "Telia"}, "cost_center")
    assert "hits" in result
    request = httpx_mock.get_requests()[0]
    import json
    body = json.loads(request.content)
    assert body["from"] == "purchases"
    assert body["predict"] == "cost_center"
    assert body["where"] == {"supplier": "Telia"}
    assert "feature" in body["select"]


def test_predict_normalises_v1_feature_to_value(httpx_mock):
    """v1's `feature` hit key is handed back as v2's `$value`."""
    httpx_mock.add_response(json={"hits": [{"$p": 0.9, "feature": "IT"}]})
    client = _make_client()
    result = client.predict("purchases", {"supplier": "Telia"}, "cost_center")
    assert result["hits"][0]["$value"] == "IT"
    assert "feature" not in result["hits"][0]


def test_predict_v2_selects_value_token(httpx_mock):
    """v2 rejects `feature` in select, so the client must ask for $value."""
    httpx_mock.add_response(json={"hits": [{"$p": 0.9, "$value": "IT"}]})
    client = _make_client("v2")
    result = client.predict("purchases", {"supplier": "Telia"}, "cost_center")
    import json
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert "$value" in body["select"]
    assert "feature" not in body["select"]
    assert result["hits"][0]["$value"] == "IT"


def test_relate_query_shape(httpx_mock):
    """_relate should send correct query structure."""
    httpx_mock.add_response(json={"hits": []})
    client = _make_client()
    client.relate("purchases", {"delivery_late": True}, "supplier")
    request = httpx_mock.get_requests()[0]
    import json
    body = json.loads(request.content)
    assert body["from"] == "purchases"
    assert body["relate"] == "supplier"


def test_relate_v2_takes_a_field_list(httpx_mock):
    httpx_mock.add_response(json={"hits": []})
    client = _make_client("v2")
    client.relate("purchases", {"delivery_late": True}, "supplier")
    import json
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["relate"] == ["supplier"]


def test_relate_v1_unwraps_the_matched_operator(httpx_mock):
    """v1 wraps the related value in the operator that matched it."""
    httpx_mock.add_response(json={"hits": [
        {"related": {"supplier": {"$has": "Neste Oyj"}}, "lift": 2.0,
         "fs": {"f": 10.0, "fOnCondition": 4.0, "fCondition": 20.0, "n": 100.0},
         "ps": {"p": 0.1, "pOnCondition": 0.2}},
    ]})
    client = _make_client()
    hits = client.relate("purchases", {"delivery_late": True}, "supplier")["hits"]
    assert hits[0]["related"] == {"supplier": "Neste Oyj"}
    assert hits[0]["ps"]["pOnCondition"] == 0.2


def test_relate_v2_derives_the_missing_ps_block(httpx_mock):
    """v2 returns frequencies only; the client recomputes p/pOnCondition."""
    httpx_mock.add_response(json={"hits": [
        {"related": {"supplier": "Neste Oyj"}, "lift": 2.0,
         "fs": {"f": 10.0, "fOnCondition": 4.0, "fOnNotCondition": 6.0,
                "fCondition": 20.0, "n": 100.0}},
    ]})
    client = _make_client("v2")
    hits = client.relate("purchases", {"delivery_late": True}, "supplier")["hits"]
    assert hits[0]["related"] == {"supplier": "Neste Oyj"}
    assert hits[0]["ps"] == {"p": 0.1, "pOnCondition": 0.2, "pOnNotCondition": 0.075}


def test_evaluate_v2_unwraps_the_envelope(httpx_mock):
    httpx_mock.add_response(json={"kind": "evaluation",
                                  "data": {"accuracy": 0.9, "baseAccuracy": 0.2}})
    client = _make_client("v2")
    result = client.evaluate("purchases", {"supplier": "Telia"}, "cost_center")
    assert result == {"accuracy": 0.9, "baseAccuracy": 0.2}


def test_evaluate_v2_rejects_an_unexpected_envelope(httpx_mock):
    """A `kind` we didn't ask for is a bug, not something to unwrap."""
    httpx_mock.add_response(json={"kind": "estimate", "data": {"value": 1.0}})
    client = _make_client("v2")
    with pytest.raises(AitoError):
        client.evaluate("purchases", {"supplier": "Telia"}, "cost_center")


def test_missing_table_tolerated_on_both_versions(httpx_mock):
    """v1 says `failed to open '<t>'` (400); v2 says `<t> not found` (404)."""
    httpx_mock.add_response(status_code=400,
                            text='{"error": "failed to open \'ghost\'"}')
    v1 = AitoClient.from_creds("https://test.aito.app", "k", tolerate_missing=True)
    assert v1.search("ghost", {}) == {"hits": [], "offset": 0, "total": 0}

    httpx_mock.add_response(status_code=404,
                            text='{"data": {"message": "ghost not found"}}')
    v2 = AitoClient.from_creds("https://test.aito.app", "k", tolerate_missing=True,
                               api_version="v2")
    assert v2.search("ghost", {}) == {"hits": [], "offset": 0, "total": 0}


def test_search_query_shape(httpx_mock):
    """_search should send correct query structure."""
    httpx_mock.add_response(json={"hits": [], "total": 0})
    client = _make_client()
    client.search("products", {}, limit=50)
    request = httpx_mock.get_requests()[0]
    import json
    body = json.loads(request.content)
    assert body["from"] == "products"
    assert body["limit"] == 50


def test_error_handling(httpx_mock):
    """Non-2xx responses should raise AitoError."""
    httpx_mock.add_response(status_code=400, text='{"error": "bad query"}')
    client = _make_client()
    with pytest.raises(AitoError) as exc_info:
        client.predict("bad_table", {}, "field")
    assert exc_info.value.status_code == 400


def test_check_connectivity_success(httpx_mock):
    httpx_mock.add_response(json={"schema": {}})
    client = _make_client()
    assert client.check_connectivity() is True


def test_check_connectivity_failure(httpx_mock):
    httpx_mock.add_response(status_code=401, text="unauthorized")
    client = _make_client()
    assert client.check_connectivity() is False

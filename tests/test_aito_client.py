"""Tests for the Aito HTTP client."""

import pytest
from src.aito_client import AitoClient, AitoError
from src.config import Config


def _make_client():
    # The unit tests don't exercise multi-tenant routing; from_creds
    # bypasses Config and avoids needing to fill in the tenants dict.
    return AitoClient.from_creds("https://test.aito.app", "test-key")


def test_url_construction():
    client = _make_client()
    assert client._url("/schema") == "https://test.aito.app/api/v1/schema"
    assert client._url("/_predict") == "https://test.aito.app/api/v1/_predict"


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

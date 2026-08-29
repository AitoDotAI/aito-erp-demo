"""Tests for the Aito HTTP client.

The v1 path is `httpx` and is mocked with `pytest-httpx`. The v2 path runs on
the `aitoai` SDK, which talks `requests` — `httpx_mock` does not intercept it,
so those calls would escape to the network. The v2 tests below drive the SDK
through a stand-in session instead.
"""

import json

import pytest
from src.aito_client import AitoClient, AitoError
from src.config import Config


def _make_client(api_version="v1"):
    # The unit tests don't exercise multi-tenant routing; from_creds
    # bypasses Config and avoids needing to fill in the tenants dict.
    return AitoClient.from_creds("https://test.aito.app", "test-key",
                                 api_version=api_version)


class _FakeResponse:
    """The parts of a `requests.Response` the SDK reads."""

    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class _FakeSession:
    """Stands in for the SDK's pooled `requests.Session`.

    Replaces `AitoClientV2._session`, which is private — the SDK publishes no
    transport seam for tests, so a consumer that wants to assert on the bodies
    it sends has to reach for the private attribute or stand up a real server.
    """

    def __init__(self, responses):
        self.calls = []
        self.headers = {}
        self._responses = list(responses)

    def request(self, method, url, json=None, params=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json})
        return self._responses.pop(0) if self._responses else _FakeResponse(
            200, {"hits": [], "offset": 0, "total": 0})

    @property
    def body(self):
        """The JSON body of the last request."""
        return self.calls[-1]["json"]


def _v2_client(*responses, tolerate_missing=False):
    """A v2 client whose SDK transport is a `_FakeSession`.

    Returns `(client, session)` so a test can assert on what was sent.
    """
    client = AitoClient.from_creds("https://test.aito.app", "test-key",
                                   tolerate_missing=tolerate_missing,
                                   api_version="v2")
    session = _FakeSession(responses)
    client._v2._session = session
    return client, session


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


def test_predict_v2_selects_value_token():
    """v2 rejects `feature` in select, so the client must ask for $value."""
    client, session = _v2_client(
        _FakeResponse(200, {"hits": [{"$p": 0.9, "$value": "IT"}], "offset": 0, "total": 1}))
    result = client.predict("purchases", {"supplier": "Telia"}, "cost_center")
    assert "$value" in session.body["select"]
    assert "feature" not in session.body["select"]
    assert session.body["from"] == "purchases"
    assert session.body["predict"] == "cost_center"
    assert session.calls[-1]["url"].endswith("/api/v2/_predict")
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


def test_relate_v2_takes_a_field_list():
    """v2 rejects the bare string form; the SDK wraps it."""
    client, session = _v2_client(
        _FakeResponse(200, {"hits": [], "offset": 0, "total": 0}))
    client.relate("purchases", {"delivery_late": True}, "supplier")
    assert session.body["relate"] == ["supplier"]
    assert session.calls[-1]["url"].endswith("/api/v2/_relate")


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


def test_relate_v2_derives_the_missing_ps_block():
    """v2 returns frequencies only; the client recomputes p/pOnCondition."""
    client, _ = _v2_client(_FakeResponse(200, {"offset": 0, "total": 1, "hits": [
        {"related": {"supplier": "Neste Oyj"}, "lift": 2.0,
         "fs": {"f": 10.0, "fOnCondition": 4.0, "fOnNotCondition": 6.0,
                "fCondition": 20.0, "n": 100.0}},
    ]}))
    hits = client.relate("purchases", {"delivery_late": True}, "supplier")["hits"]
    assert hits[0]["related"] == {"supplier": "Neste Oyj"}
    assert hits[0]["ps"] == {"p": 0.1, "pOnCondition": 0.2, "pOnNotCondition": 0.075}


def test_evaluate_v2_unwraps_the_envelope():
    client, _ = _v2_client(_FakeResponse(200, {
        "kind": "evaluation", "data": {"accuracy": 0.9, "baseAccuracy": 0.2}}))
    result = client.evaluate("purchases", {"supplier": "Telia"}, "cost_center")
    assert result == {"accuracy": 0.9, "baseAccuracy": 0.2}


def test_evaluate_v2_reads_a_bare_rep1_body():
    """A legacy table answers `_evaluate` flat, with no envelope at all.

    The SDK's unwrap dispatches on the operation asked for rather than on
    `kind`, so both shapes read the same. Following the response-format spec's
    own `kind ?? "rows"` rule here would call this a page of hits.
    """
    client, _ = _v2_client(_FakeResponse(200, {"accuracy": 0.9, "baseAccuracy": 0.2}))
    result = client.evaluate("purchases", {"supplier": "Telia"}, "cost_center")
    assert result == {"accuracy": 0.9, "baseAccuracy": 0.2}


def test_evaluate_v2_rejects_an_unexpected_envelope():
    """A `kind` we didn't ask for is a bug, not something to unwrap."""
    client, _ = _v2_client(_FakeResponse(200, {"kind": "estimate", "data": {"value": 1.0}}))
    with pytest.raises(AitoError):
        client.evaluate("purchases", {"supplier": "Telia"}, "cost_center")


def test_missing_table_tolerated_on_both_versions(httpx_mock):
    """v1 says `failed to open '<t>'` (400); v2 says `<t> not found` (404)."""
    httpx_mock.add_response(status_code=400,
                            text='{"error": "failed to open \'ghost\'"}')
    v1 = AitoClient.from_creds("https://test.aito.app", "k", tolerate_missing=True)
    assert v1.search("ghost", {}) == {"hits": [], "offset": 0, "total": 0}

    # The real v2 error shape: a structured `error` kind carrying a machine code.
    v2, _ = _v2_client(
        _FakeResponse(404, {"kind": "error",
                            "data": {"code": "not_found", "message": "ghost not found"}}),
        tolerate_missing=True)
    assert v2.search("ghost", {}) == {"hits": [], "offset": 0, "total": 0}


def test_missing_other_table_is_not_tolerated_on_v2():
    """`tolerate_missing` must not swallow a 404 about a *different* table.

    The SDK's `is_not_found` reports that something was missing, not what, so
    the client still matches the table name — the same guard the v1 path has.
    """
    v2, _ = _v2_client(
        _FakeResponse(404, {"kind": "error",
                            "data": {"code": "not_found", "message": "other_table not found"}}),
        tolerate_missing=True)
    with pytest.raises(AitoError):
        v2.search("ghost", {})


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

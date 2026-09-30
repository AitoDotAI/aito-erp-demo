"""The query a pane shows is the query that was sent.

Side panels used to hand-write their queries, and the audit of
2026-09-30 found them inventing tables (`deliveries`, `approval_history`)
and dropping the clauses the client adds. `query_log` records every
query body at the two send seams of `AitoClient`; the panes render what
it recorded. These tests pin that it records the wire body, that it
follows work into thread pools, that it never holds a credential, and
that a cached response keeps the queries that produced it.
"""

import json

import pytest

from src import query_log
from src.concurrency import parallel_map

SENTINEL_KEY = "sk-test-SENTINEL-4f1c9"


def test_records_the_body_and_endpoint_only():
    with query_log.recording() as queries:
        query_log.record("/api/v2/_predict", {"from": "purchases", "where": {"supplier": "X"},
                                              "predict": "cost_center"})
    assert queries == [{"endpoint": "_predict", "body": {"from": "purchases",
                                                         "where": {"supplier": "X"},
                                                         "predict": "cost_center"}}]


def test_non_query_calls_are_not_recorded():
    with query_log.recording() as queries:
        query_log.record("/schema", None)
        query_log.record("/data/purchases/batch", [{"a": 1}])
    assert queries == []


def test_work_fanned_out_to_a_thread_pool_is_still_recorded():
    """A ContextVar does not follow a plain ThreadPoolExecutor; the latency
    pill missed every pooled call for that reason."""
    def ask(i):
        query_log.record("_predict", {"from": "t", "where": {"i": i}, "predict": "x"})
        return i
    with query_log.recording() as queries:
        assert parallel_map(ask, range(5), workers=3) == [0, 1, 2, 3, 4]
    assert sorted(q["body"]["where"]["i"] for q in queries) == [0, 1, 2, 3, 4]


def test_the_client_records_what_it_sends_and_never_the_key(monkeypatch):
    from src.aito_client import AitoClient
    client = AitoClient.from_creds("https://example.invalid/db/x", SENTINEL_KEY, api_version="v1")

    class _Response:
        status_code = 200
        headers = {}
        def json(self):
            return {"hits": []}
    monkeypatch.setattr(client._client, "request", lambda *a, **k: _Response())
    with query_log.recording() as queries:
        client.predict("purchases", {"supplier": "X"}, "cost_center")
    assert queries and queries[0]["endpoint"] == "_predict"
    assert queries[0]["body"]["predict"] == "cost_center"
    assert "select" in queries[0]["body"], "the pane must show the clauses the client adds"
    assert SENTINEL_KEY not in json.dumps(queries)


def test_a_cached_value_keeps_the_queries_that_produced_it():
    from src import cache
    key = "test:query_log:cached"
    cache._cache.pop(key, None)

    def compute():
        query_log.record("_relate", {"from": "baskets", "relate": ["products"]})
        return {"items": [1]}
    first = cache.get_or_compute(key, compute)
    second = cache.get_or_compute(key, compute)
    assert first["_queries"] == second["_queries"] == [
        {"endpoint": "_relate", "body": {"from": "baskets", "relate": ["products"]}}]

"""Every Aito query body sent while producing a response, kept with it.

Side panels used to hand-write the query behind a view, and they drifted:
invented tables, missing clauses, samples unrelated to the screen. The
panes now render bodies recorded here, at the two send seams of
`AitoClient` (v2's `request()` override and v1's `_request`), so what a
pane shows is what was sent — including the `select` and `limit` the
client adds.

Only the endpoint name and the JSON body are kept. Headers, the host and
any query string never are, so a key cannot reach a response
(tests/test_query_log.py sends a sentinel key and checks).

Recording is a ContextVar like `timing`; `concurrency.parallel_map`
carries it into thread pools. `cache.get_or_compute` records around the
computation and stores the bodies WITH the value, so a cache hit still
shows the query that produced it.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

_active: ContextVar[list[dict] | None] = ContextVar("aito_query_log", default=None)

# A row's pane shows that row's own query, so a list keeps one per row
# up to the longest list a view shows (a 60-line matching batch). The
# total bounds a plan that fans out; measured overhead is in the PR.
MAX_PER_SHAPE = 60
MAX_TOTAL = 300


# Named rather than "anything starting with _": `/data/_delete`,
# `/data/_modify` and `/schema/_copy` also carry dict bodies, and they
# are writes, not the query behind a view.
QUERY_ENDPOINTS = frozenset({"_search", "_predict", "_relate", "_evaluate", "_estimate",
                             "_recommend", "_match", "_similarity", "_query", "_aggregate"})


def _endpoint(path: str) -> str | None:
    """`/api/v2/_predict` → `_predict`; anything that is not a query → None."""
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return last if last in QUERY_ENDPOINTS else None


def record(path: str, body: Any) -> None:
    bucket = _active.get()
    endpoint = _endpoint(path)
    if bucket is None or endpoint is None or not isinstance(body, dict):
        return
    bucket.append({"endpoint": endpoint, "body": body})


def current() -> list[dict] | None:
    """The queries recorded so far in the active block, or None outside one."""
    return _active.get()


@contextmanager
def recording() -> Iterator[list[dict]]:
    """Collect the queries sent inside the block. Nested blocks also
    report to the enclosing one, so a request sees what its parts sent."""
    outer = _active.get()
    mine: list[dict] = []
    token = _active.set(mine)
    try:
        yield mine
    finally:
        _active.reset(token)
        if outer is not None:
            outer.extend(mine)


@contextmanager
def unrecorded() -> Iterator[None]:
    """Send without recording — for the demo's own plumbing (the
    persistent cache's lookup), which is not a query behind any view."""
    token = _active.set(None)
    try:
        yield
    finally:
        _active.reset(token)


def attach(value: Any) -> Any:
    """Stamp a dict response with the queries recorded so far, under
    `_queries`, in place, and return it. Cached values get this in
    `cache.set`; an uncached endpoint calls it on what it returns."""
    recorded = current()
    if isinstance(value, dict) and "_queries" not in value and recorded:
        value["_queries"] = capped(recorded)
    return value


def _shape(query: dict) -> tuple:
    body = query["body"]
    frm = body.get("from")
    return (query["endpoint"], frm if isinstance(frm, str) else "nested",
            str(body.get("predict") or body.get("estimate") or body.get("relate")
                or body.get("recommend") or ""))


def capped(queries: list[dict]) -> list[dict]:
    """Up to MAX_PER_SHAPE of each shape, MAX_TOTAL in all, in send order.

    Every shape gets its first query in before any shape gets a second,
    so a response with many shapes (a staffing plan) never loses one
    to the total cap."""
    by_shape: dict[tuple, list[int]] = {}
    for i, q in enumerate(queries):
        by_shape.setdefault(_shape(q), []).append(i)
    kept: list[int] = []
    for rank in range(MAX_PER_SHAPE):
        for positions in by_shape.values():
            if rank < len(positions) and len(kept) < MAX_TOTAL:
                kept.append(positions[rank])
    return [queries[i] for i in sorted(kept)]

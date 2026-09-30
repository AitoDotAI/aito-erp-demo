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

# A pane needs one representative query per shape, not all of them — a
# 30-line matching batch would otherwise ship 30 near-identical bodies.
MAX_PER_SHAPE = 4
MAX_TOTAL = 40


def _endpoint(path: str) -> str | None:
    """`/api/v2/_predict` → `_predict`; anything that is not a query → None."""
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return last if last.startswith("_") else None


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


def _shape(query: dict) -> tuple:
    body = query["body"]
    frm = body.get("from")
    return (query["endpoint"], frm if isinstance(frm, str) else "nested",
            str(body.get("predict") or body.get("estimate") or body.get("relate")
                or body.get("recommend") or ""))


def capped(queries: list[dict]) -> list[dict]:
    """Keep the first few of each shape, in the order they were sent."""
    seen: dict[tuple, int] = {}
    out = []
    for q in queries:
        shape = _shape(q)
        if seen.get(shape, 0) < MAX_PER_SHAPE:
            seen[shape] = seen.get(shape, 0) + 1
            out.append(q)
        if len(out) >= MAX_TOTAL:
            break
    return out

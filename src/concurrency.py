"""One way to fan work out over threads, carrying the request's context.

A plain `ThreadPoolExecutor` does not copy ContextVars into its workers,
so per-request recorders (`timing` for the latency pill, `query_log` for
the query panes) silently missed every call made inside a pool. Each
task here runs in a copy of the caller's context.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(fn: Callable[[T], R], items: Iterable[T], workers: int = 8) -> list[R]:
    """`list(pool.map(fn, items))`, with each call in the caller's context."""
    items = list(items)
    contexts = [contextvars.copy_context() for _ in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda pair: pair[0].run(fn, pair[1]), zip(contexts, items)))

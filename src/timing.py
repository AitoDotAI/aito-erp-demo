"""Per-request Aito call timings.

The backend records every Aito HTTP call's endpoint + wall time on a
request-scoped list, then surfaces it back to the browser via an
`X-Aito-Calls` response header. The frontend's latency pill reads
that header and shows `_predict 32ms · _relate 118ms` so visitors
*see* that "predictive database" means actually-fast database calls,
not magic.

Design choice — `contextvars` over thread-locals: FastAPI's request
handlers are async, so async-aware context propagation is needed.
ContextVar handles the async-task boundary correctly while still
being drop-in for sync code (the AitoClient is sync — `httpx.request`
is blocking — so the recording call happens in whichever event-loop
thread served the request, and the contextvar binding is per-task).
"""

from contextvars import ContextVar


# Per-request list of `(endpoint_path, duration_ms)` tuples. The list
# is reset by the FastAPI middleware on each incoming request. Code
# that runs *outside* a request (e.g. the warmup thread) sees an empty
# list and recording is a no-op — the recorded data simply isn't read.
_calls: ContextVar[list[tuple[str, float]] | None] = ContextVar(
    "aito_request_calls", default=None,
)


def start_request() -> None:
    """Bind a fresh empty call list for the current request."""
    _calls.set([])


def record_call(endpoint: str, duration_ms: float) -> None:
    """Append one Aito call's timing to the current request list.

    `endpoint` is the Aito API path (e.g. `/_predict`, `/_relate`).
    The leading slash is stripped before storing — the header format
    we ship to the browser uses bare names (`_predict:32`).
    """
    bucket = _calls.get()
    if bucket is None:
        return
    bucket.append((endpoint.lstrip("/"), duration_ms))


def current_calls() -> list[tuple[str, float]]:
    """Return the calls recorded so far on the current request."""
    return list(_calls.get() or [])


def render_header() -> str:
    """Render the call list as the `X-Aito-Calls` header value.

    Format: `_predict:32,_relate:118,_predict:18`. Multiple calls to
    the same endpoint are listed individually, in call order — the
    frontend can sum + group as it likes. Empty when no calls were
    made (e.g. cache hit) — the middleware skips emitting the header
    in that case.
    """
    return ",".join(f"{name}:{int(round(ms))}"
                    for name, ms in current_calls())

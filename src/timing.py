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

# Twelve, because that is exactly what the latency pill renders — see
# `LatencyBadge.tsx`, which already sliced to 12 so a big plan "doesn't
# unfurl forever". The display was capped and the wire was not.
MAX_HEADER_CALLS = 12


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

    Format: `_predict:32.4,_relate:118.0,_predict:1.6`. One decimal
    place — enough to show sub-ms `_search` resolution honestly
    without making the header grow. Multiple calls to the same
    endpoint are listed individually, in call order — the frontend
    can sum + group as it likes. Empty when no calls were made
    (e.g. cache hit); the middleware skips emitting the header in
    that case.

    CAPPED, and that cap is load-bearing. A generated project plan
    makes 328 Aito calls, which rendered to a 4882-byte header — and
    nginx's default `proxy_buffer_size` is 4096, so it answered the
    whole request with a 502 rather than pass the header on. The view
    worked locally, where nothing sits in front of uvicorn, and failed
    in production only for the project types large enough to cross the
    line: `maintenance` (1186 bytes) served fine while `construction`
    (4872) did not.

    A response header is a debug channel, not a data channel. The
    frontend already showed at most twelve entries; it was the other
    316 that broke the page.
    """
    calls = current_calls()
    return ",".join(f"{name}:{ms:.1f}" for name, ms in calls[:MAX_HEADER_CALLS])


def render_total_header() -> str:
    """`<count>,<total_ms>` — the honest totals, whatever the cap.

    The per-call list is truncated, so the pill cannot count entries
    any more without under-reporting. This carries what it actually
    wants to show: how many calls the request made and how long they
    took together.
    """
    calls = current_calls()
    if not calls:
        return ""
    return f"{len(calls)},{sum(ms for _, ms in calls):.1f}"

"""The `X-Aito-Calls` header has to fit through nginx.

A generated project plan makes 328 Aito calls. Rendered one per entry
that was a 4882-byte response header, and nginx's default
`proxy_buffer_size` is 4096 — so it refused to forward the response and
answered 502 Bad Gateway instead. The view worked locally, where
nothing sits in front of uvicorn, and failed in production only for the
project types big enough to cross the line: `maintenance` (1186 bytes)
served fine while `construction` (4872) did not.

A response header is a debug channel. Nothing should be able to make
one grow without bound.
"""

from src import timing

# nginx's default proxy_buffer_size, which is what the deployed demo
# server runs with. Staying well under it is the whole point.
NGINX_BUFFER_BYTES = 4096


def _record(n: int) -> None:
    timing.start_request()
    for i in range(n):
        timing.record_call("/_predict", 1234.5 + i)


def test_the_header_stays_far_under_the_proxy_buffer():
    _record(500)
    header = timing.render_header()
    assert len(header.encode()) < NGINX_BUFFER_BYTES / 4, (
        f"{len(header.encode())} bytes for 500 calls — a header this big "
        "is what made nginx answer 502")


def test_the_totals_stay_exact_when_the_list_is_capped():
    """The cap is why this header exists: counting the truncated entries
    would under-report, and the pill shows the count."""
    _record(328)
    count, total = timing.render_total_header().split(",")
    assert int(count) == 328
    assert float(total) == sum(1234.5 + i for i in range(328))
    assert len(timing.render_header().split(",")) == timing.MAX_HEADER_CALLS


def test_a_small_request_is_unchanged():
    """The cap must not alter the common case, which is a handful of
    calls rendered in full."""
    _record(3)
    assert timing.render_header() == "_predict:1234.5,_predict:1235.5,_predict:1236.5"
    assert timing.render_total_header().startswith("3,")


def test_no_calls_means_no_headers():
    timing.start_request()
    assert timing.render_header() == ""
    assert timing.render_total_header() == ""

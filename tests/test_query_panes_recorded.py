"""A side panel shows a query the backend sent, never one a page wrote.

The audit of 2026-09-30 found most panes hand-written and drifted:
tables that do not exist (`deliveries`, `approval_history`), the
`select` and `limit` the client always adds left out, a Planner sample
for a customer not on screen. Panes now render bodies recorded by
`src/query_log.py` via `frontend/lib/query.ts`, which is the only file
allowed to produce query markup.
"""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "frontend"
RENDERER = FRONTEND / "lib" / "query.ts"

# The span classes the renderer emits, or a JSON "from"/"where" key
# inside a string — either means a page is typing a query itself.
QUERY_MARKUP = re.compile(r'class=\\?"q-(?:k|v|p|n|op)\\?"|&quot;from&quot;|["\'`]\s*\\?"(?:from|where|predict)\\?"\s*:')


def _sources():
    for path in sorted([*FRONTEND.joinpath("app").rglob("*.tsx"),
                        *FRONTEND.joinpath("components").rglob("*.tsx"),
                        *FRONTEND.joinpath("lib").rglob("*.ts")]):
        if path != RENDERER:
            yield path


def test_no_page_writes_query_markup():
    bad = [f"{p.relative_to(FRONTEND)}:{n}: {line.strip()[:90]}"
           for p in _sources()
           for n, line in enumerate(p.read_text().splitlines(), 1)
           if QUERY_MARKUP.search(line)]
    assert not bad, "hand-written query panes (use findQuery over _queries):\n" + "\n".join(bad)


def test_the_guard_would_catch_the_old_panes():
    """Positive control: lines as the pages used to write them."""
    old = ['query: `<span class="q-k">POST</span> /api/{version}/_predict<br/>',
           '&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>,<br/>']
    assert all(QUERY_MARKUP.search(line) for line in old)


def test_the_renderer_is_the_one_place_markup_is_made():
    assert 'class="q-k"' in RENDERER.read_text() or "q-k" in RENDERER.read_text()

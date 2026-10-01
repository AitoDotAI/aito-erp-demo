"""A read meant to cover a whole table must actually cover it.

Supplier spend, Rule Mining, Catalog and the Overview each read a table
with `search(table, {}, limit=N)` and treated the page as the table. On
Aurora — 5259 purchases, 3200 products — every one of them summed,
mined or checked a subset and said nothing. The whole-table reads now
go through `_whole_table`, which asserts the count; this fails if a
fixed page smaller than a tenant's fixture comes back.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
# A fixed page over a whole table — except a read used only for its
# "total", which is a count, not a page.
FIXED = re.compile(r'(?:\.search\(\s*"(\w+)",\s*\{\}|_fetch\(\s*client,\s*"(\w+)"),\s*limit=([\d_]+)\)'
                   r'(?!\s*\[\s*"total"\s*\]|\.get\(\s*"total")')


def _largest_fixture(table: str) -> int:
    sizes = [len(json.loads(p.read_text())) for p in DATA.glob(f"*/{table}.json")]
    return max(sizes, default=0)


def _fixed_pages(source: str):
    for m in FIXED.finditer(source):
        yield (m.group(1) or m.group(2)), int(m.group(3).replace("_", ""))


@pytest.mark.skipif(not (DATA / "aurora" / "purchases.json").exists(), reason="fixtures not generated")
def test_no_fixed_page_is_smaller_than_the_table_it_reads():
    bad = [f"{p.relative_to(ROOT)}: {table} limit={limit} < {_largest_fixture(table)} rows"
           for p in sorted((ROOT / "src").glob("*.py"))
           for table, limit in _fixed_pages(p.read_text())
           if limit < _largest_fixture(table)]
    assert not bad, "\n".join(bad)


def test_the_guard_reads_the_shape_that_shipped():
    """Positive control: the line that under-counted Aurora's spend."""
    assert list(_fixed_pages('result = client.search("purchases", {}, limit=5000)')) == [("purchases", 5000)]
    assert list(_fixed_pages('total = client.search("purchases", {}, limit=1)["total"]')) == []

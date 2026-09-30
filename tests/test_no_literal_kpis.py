"""No page renders a KPI whose value is typed into the page.

Approval Routing showed "71% auto-routed", "1.4h average approval time"
and "3.1% override rate" as literals in the JSX, with no data behind
any of them; PO Queue had "47 POs today" and "82% auto-coded" the same
way. A KPI either comes from the response or it is not on the page.
This fails on any `kpi-val` whose content starts with a digit or a
currency sign rather than an expression.
"""

import re
from pathlib import Path

PAGES = Path(__file__).parent.parent / "frontend" / "app"
LITERAL_KPI = re.compile(r'className="kpi-val"[^>]*>\s*[0-9€$£]')


def test_no_kpi_value_is_a_literal():
    offenders = []
    for page in sorted(PAGES.rglob("*.tsx")):
        for n, line in enumerate(page.read_text().splitlines(), 1):
            if LITERAL_KPI.search(line):
                offenders.append(f"{page.relative_to(PAGES)}:{n}: {line.strip()}")
    assert not offenders, "literal KPI values:\n" + "\n".join(offenders)

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


# A template literal and a plain string are matched separately: a quote
# inside `${...}` must not end a template early — "47" sat after one.
SUBTITLE = re.compile(r'subtitle=\{?(?:`([^`]*)`|"([^"]*)")')


def test_no_top_bar_subtitle_carries_a_typed_in_count():
    """PO Queue's header said "47 received today" after the same figure
    had been removed from its KPI strip. Counts in a subtitle come from
    an expression, never a literal."""
    offenders = []
    for page in sorted(PAGES.rglob("*.tsx")):
        for n, line in enumerate(page.read_text().splitlines(), 1):
            for template, plain in SUBTITLE.findall(line):
                text = template or plain
                if re.search(r"\d", re.sub(r"\$\{[^}]*\}", "", text)):
                    offenders.append(f"{page.relative_to(PAGES)}:{n}: {text}")
    assert not offenders, "literal counts in subtitles:\n" + "\n".join(offenders)

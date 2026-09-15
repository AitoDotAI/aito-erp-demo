"""Every guide a panel links to has to exist.

The Aito panel is the part of this demo that does the explaining, and
the guide is the next thing a developer reading it wants. A link that
404s there is worse than no link: it is the sales collateral failing in
front of the person we most want to reach.

This is a real risk and not a theoretical one — three views had no
guide at all until recently, and four guides pointed at screenshots
that did not exist. Both were found by looking, which is not a method.
"""

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend"
GUIDES = REPO / "docs" / "use-cases"

_URL = re.compile(r"https://github\.com/AitoDotAI/aito-erp-demo/blob/main/([^\"']+)")


def _sources() -> list[pathlib.Path]:
    return [p for p in (list((FRONTEND / "app").rglob("page.tsx"))
                        + list((FRONTEND / "lib").glob("*.ts")))]


def test_every_linked_repo_path_exists():
    """Covers the guides AND the `Source code` links, which point at
    service modules and rot the same way when a module is renamed."""
    missing = []
    for source in _sources():
        for path in _URL.findall(source.read_text()):
            if not (REPO / path).exists():
                missing.append(f"{source.relative_to(REPO)} → {path}")
    assert not missing, "panel links pointing at files that do not exist:\n  " \
        + "\n  ".join(missing)


def test_every_view_offers_its_guide():
    """A view without a guide link is a view whose reader has to go
    and find the repo themselves."""
    pages = sorted((FRONTEND / "app").rglob("page.tsx"))
    # Landing and persona-picker routes explain the demo, not a query.
    skip = {"industrial", "retail", "services"}
    unlinked = [
        p.parent.name for p in pages
        if p.parent.name not in skip
        and p.parent != FRONTEND / "app"          # the landing page
        and "docs/use-cases/" not in p.read_text()
        # The shared panels carry their links in panel-content.ts.
        and "panel-content" not in p.read_text()
    ]
    assert not unlinked, f"views with no use-case guide link: {unlinked}"


def test_no_guide_is_orphaned():
    """A guide nothing links to is a guide nobody reads."""
    linked = set()
    for source in _sources():
        for path in _URL.findall(source.read_text()):
            if path.startswith("docs/use-cases/"):
                linked.add(pathlib.Path(path).name)
    on_disk = {p.name for p in GUIDES.glob("*.md")} - {"README.md"}
    assert not (on_disk - linked), \
        f"guides no view links to: {sorted(on_disk - linked)}"

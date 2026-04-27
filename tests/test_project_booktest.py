"""Booktest for project portfolio quality.

Two layers:

1. **Offline fixture signal** — protects the demo's *data*. The
   generator embeds engineered patterns (manager × type fits,
   reliable people boost, chaotic people drag). If a future fixture
   regen weakens the signal, these tests fail loudly so we don't ship
   a demo where Aito can't actually learn anything.

2. **Live Aito backtest** — skipped without AITO_API_URL +
   AITO_API_KEY. Validates that Aito picks up the signal through
   `_predict` and `_relate`:

     - project success accuracy via `_evaluate` (cross-validated by
       Aito itself) beats base rate by a margin
     - `_relate` ranks reliable people as boost (lift > 1) and
       chaotic people as drag (lift < 1)
     - per-person staffing simulator: swapping a chaotic engineer
       for a reliable one increases P(success)

Run with: `./do booktest` (or `pytest tests/test_project_booktest.py -v`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Mirrors the generator's reliability profile. Keep in sync with
# data/generate_projects.py — these are the people whose effect on
# project outcomes is engineered into the fixtures.
RELIABLE = {"A. Lindgren", "K. Saari", "P. Korhonen", "M. Salo", "H. Mattila"}
CHAOTIC = {"V. Jokinen", "T. Rinne"}

# `team_members` is stored as a Text field with each person rendered as
# two tokens ("A. Lindgren" → ["A.", "Lindgren"]). We match on surname.
RELIABLE_SURNAMES = {p.split()[-1] for p in RELIABLE}
CHAOTIC_SURNAMES = {p.split()[-1] for p in CHAOTIC}


# ── Helpers ─────────────────────────────────────────────────────────

# Per-tenant fixtures live under data/<tenant>/. Tests that look at
# fixture data parametrize over every tenant directory we find — the
# offline guarantees should hold for each persona's universe
# independently. Falls back to the flat data/projects.json so the
# tests still run on a fresh checkout that hasn't generated personas.

def _tenant_fixture_dirs() -> list[Path]:
    found = [DATA_DIR / t for t in ("metsa", "aurora", "studio")
             if (DATA_DIR / t / "projects.json").exists()]
    if found:
        return found
    if (DATA_DIR / "projects.json").exists():
        return [DATA_DIR]
    return []


TENANT_DIRS = _tenant_fixture_dirs()
TENANT_PARAMS = pytest.mark.parametrize(
    "tenant_dir",
    TENANT_DIRS,
    ids=[d.name if d.name in ("metsa", "aurora", "studio") else "flat"
         for d in TENANT_DIRS],
)


def _load_projects(tenant_dir: Path) -> list[dict]:
    with open(tenant_dir / "projects.json") as f:
        return json.load(f)


def _completed(projects: list[dict]) -> list[dict]:
    return [p for p in projects if p["status"] == "complete"]


def _success_rate(projects: list[dict]) -> float:
    if not projects:
        return 0.0
    return sum(1 for p in projects if p.get("success")) / len(projects)


def _surnames(p: dict) -> set[str]:
    """Return the set of surname tokens on a project's team."""
    return set(p["team_members"].split())


def _aito_available() -> bool:
    return bool(os.environ.get("AITO_API_URL") and os.environ.get("AITO_API_KEY"))


needs_aito = pytest.mark.skipif(
    not _aito_available(),
    reason="AITO_API_URL / AITO_API_KEY not set — skipping live Aito backtest",
)


# ── Layer 1: offline fixture-signal tests ───────────────────────────


@TENANT_PARAMS
def test_fixture_has_completed_and_active(tenant_dir: Path):
    """Generator should produce both completed and active projects."""
    projects = _load_projects(tenant_dir)
    completed = _completed(projects)
    active = [p for p in projects if p["status"] != "complete"]
    assert len(completed) >= 30, f"too few completed projects: {len(completed)}"
    assert len(active) >= 8, f"too few active projects: {len(active)}"


@TENANT_PARAMS
def test_fixture_success_rate_in_band(tenant_dir: Path):
    """Completed projects should succeed in a realistic 55-85% band.

    Too high → Aito can't distinguish failure cases (no signal in
    minority class). Too low → demo looks broken.
    """
    completed = _completed(_load_projects(tenant_dir))
    rate = _success_rate(completed)
    assert 0.55 <= rate <= 0.85, (
        f"[{tenant_dir.name}] completed success rate {rate:.0%} "
        f"outside 55-85% band — regenerate fixtures."
    )


def test_fixture_signal_reliable_people_boost_outcomes_combined():
    """Across all personas combined, projects with a high *share* of
    reliable people should succeed measurably more often.

    Why combined and not per-persona: the engineered effect is small
    (~1.08× per reliable team member), and confounds with project
    type, team size, and manager fit. With ~35 completed projects in
    a single persona, random bucketing dominates the signal. Pooling
    across personas gives ~325 projects — enough for the engineered
    effect to surface stably.

    The chaotic-drag test below is per-persona because chaotic
    multipliers (0.82× per chaotic member) are larger and survive in
    smaller samples.
    """
    all_completed: list[dict] = []
    for tenant_dir in TENANT_DIRS:
        all_completed.extend(_completed(_load_projects(tenant_dir)))

    if len(all_completed) < 100:
        pytest.skip("not enough total completed projects across personas")

    def reliable_share(p: dict) -> float:
        members = _surnames(p)
        return len(members & RELIABLE_SURNAMES) / max(len(members), 1)

    # Thresholds tuned to the share distribution (max ~0.5 because
    # the team pool is ~35% reliable).
    high = [p for p in all_completed if reliable_share(p) >= 0.33]
    low = [p for p in all_completed if reliable_share(p) < 0.15]

    assert len(high) >= 30 and len(low) >= 30, (
        f"buckets too small to test reliably (high={len(high)}, low={len(low)})"
    )

    rate_high = _success_rate(high)
    rate_low = _success_rate(low)
    lift = rate_high / max(rate_low, 0.01)

    assert lift >= 1.05, (
        f"reliable-share boost too weak across all personas: "
        f"high-share={rate_high:.0%} ({len(high)} projects) vs "
        f"low-share={rate_low:.0%} ({len(low)} projects), lift={lift:.2f}"
    )


@TENANT_PARAMS
def test_fixture_signal_chaotic_people_drag_outcomes(tenant_dir: Path):
    """Projects that include any chaotic person should succeed at a
    measurably lower rate."""
    completed = _completed(_load_projects(tenant_dir))
    with_cha = [p for p in completed if _surnames(p) & CHAOTIC_SURNAMES]
    without_cha = [p for p in completed if not (_surnames(p) & CHAOTIC_SURNAMES)]

    if len(with_cha) < 5 or len(without_cha) < 5:
        pytest.skip(
            f"[{tenant_dir.name}] too few projects with/without chaotic people."
        )

    rate_with = _success_rate(with_cha)
    rate_without = _success_rate(without_cha)

    assert rate_with < rate_without - 0.05, (
        f"[{tenant_dir.name}] chaotic-people drag too weak: "
        f"with={rate_with:.0%}, without={rate_without:.0%}"
    )


@TENANT_PARAMS
def test_fixture_assignments_link_to_projects(tenant_dir: Path):
    """Every assignment must reference a real project — broken links
    will cause _relate over the join to silently return nothing."""
    projects = {p["project_id"] for p in _load_projects(tenant_dir)}
    with open(tenant_dir / "assignments.json") as f:
        assignments = json.load(f)

    assert len(assignments) > 100
    orphans = [a for a in assignments if a["project_id"] not in projects]
    assert not orphans, f"{len(orphans)} assignments reference missing projects"

    leads = [a for a in assignments if a["role"] == "lead"]
    assert len(leads) >= 30, "every project should have a lead assignment"


# ── Layer 2: live Aito backtests ────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    from src.aito_client import AitoClient, AitoError
    from src.config import load_config

    cfg = load_config()
    c = AitoClient(cfg)
    if not c.check_connectivity():
        pytest.skip("Aito not reachable")

    # The booktest is meaningless without the projects table loaded.
    # Skip rather than fail so it slots cleanly into pre-merge runs.
    try:
        c.search("projects", {}, limit=1)
    except AitoError as exc:
        if exc.status_code == 400 and "failed to open 'projects'" in str(exc):
            pytest.skip(
                "projects table not loaded in Aito — run `./do load-data` first"
            )
        raise
    return c


@needs_aito
def test_aito_predict_success_beats_base_rate(client):
    """Aito's `_evaluate` on `success` should beat the base rate.

    `_evaluate` runs leave-one-out cross-validation across the table,
    so we get an honest accuracy without holding out fixture rows.
    """
    response = client.evaluate(
        table="projects",
        where={"status": "complete"},
        predict_field="success",
    )
    accuracy = response.get("accuracy")
    base = response.get("baseAccuracy")
    assert accuracy is not None and base is not None, (
        f"unexpected _evaluate response shape: {response}"
    )

    # Demand a meaningful margin — engineered fixtures should leave
    # 8+ percentage points of headroom over predicting the majority class.
    margin = accuracy - base
    assert margin >= 0.08, (
        f"Aito success prediction lift too small: "
        f"accuracy={accuracy:.0%}, base={base:.0%}, margin={margin:.0%}"
    )


@needs_aito
def test_aito_relate_ranks_reliable_people_as_boost(client):
    """For each engineered-reliable person, Aito's `_relate` over
    `team_members` should return a boost (lift > 1.0) when relating
    against `success: true`."""
    response = client.relate(
        table="projects",
        where={"success": True},
        relate_field="team_members",
    )
    hits = response.get("hits") or []

    by_token: dict[str, float] = {}
    for h in hits:
        related = h.get("related") or {}
        for v in related.values():
            if isinstance(v, dict):
                token = v.get("$has") or v.get("$is")
                if token:
                    by_token[str(token)] = float(h.get("lift", 1.0))

    # Names are tokenized; we look for the surname token (e.g. "Lindgren").
    boost_hits = []
    for person in RELIABLE:
        surname = person.split()[-1].rstrip(".")
        # Look for any token that matches surname or full string
        match_lift = None
        for tok, lift in by_token.items():
            if surname.lower() in tok.lower():
                match_lift = lift
                break
        if match_lift is not None:
            boost_hits.append((person, match_lift))

    assert len(boost_hits) >= 2, (
        f"_relate did not surface enough reliable people. "
        f"Tokens seen: {list(by_token.keys())[:20]}"
    )
    # At least 60% of the reliable people that show up should have lift > 1.
    boosting = [p for p, l in boost_hits if l >= 1.0]
    assert len(boosting) / len(boost_hits) >= 0.6, (
        f"reliable people not consistently boosting: {boost_hits}"
    )


@needs_aito
def test_aito_relate_ranks_chaotic_people_as_drag(client):
    """Chaotic people should appear with lift < 1.0 against success=true."""
    response = client.relate(
        table="projects",
        where={"success": True},
        relate_field="team_members",
    )
    hits = response.get("hits") or []

    found = []
    for h in hits:
        related = h.get("related") or {}
        for v in related.values():
            if isinstance(v, dict):
                tok = v.get("$has") or v.get("$is")
                if not tok:
                    continue
                for person in CHAOTIC:
                    surname = person.split()[-1].rstrip(".")
                    if surname.lower() in str(tok).lower():
                        found.append((person, float(h.get("lift", 1.0))))

    if not found:
        pytest.skip("no chaotic people surfaced by _relate (small sample)")

    drags = [p for p, l in found if l <= 1.0]
    assert len(drags) >= 1, f"chaotic people did not appear as drag: {found}"


@needs_aito
def test_aito_staffing_swap_reliable_for_chaotic_improves_p(client):
    """Per-project staffing simulator: holding everything else fixed,
    swapping a chaotic engineer for a reliable one should raise
    P(success).

    This is the test that validates the "predict project/task success
    and how assignments relate to that" feature end-to-end.
    """
    base_where = {
        "project_type": "implementation",
        "manager": "J. Lehtinen",
        "team_size": 5,
        "duration_days": 90,
        "priority": "medium",
        "budget_eur": 80000,
    }

    def p_success(team: str) -> float:
        resp = client.predict(
            table="projects",
            where={**base_where, "team_members": team},
            predict_field="success",
            limit=2,
        )
        for h in resp.get("hits") or []:
            if h.get("feature") in (True, "true", "True"):
                return float(h.get("$p", 0.0))
        return 0.0

    chaotic_team = "A. Lindgren K. Saari V. Jokinen T. Rinne L. Aho"
    reliable_team = "A. Lindgren K. Saari M. Salo P. Korhonen L. Aho"

    p_chaotic = p_success(chaotic_team)
    p_reliable = p_success(reliable_team)

    # Need at least 5 percentage points of separation.
    assert p_reliable - p_chaotic >= 0.05, (
        f"staffing swap had no measurable effect: "
        f"reliable={p_reliable:.0%}, chaotic={p_chaotic:.0%}"
    )


@needs_aito
def test_aito_active_predictions_have_meaningful_spread(client):
    """The portfolio should show predicted-success values spread
    across the confidence range. If Aito returns ~50% for everything
    (uniform prior), we have no signal — the demo would be flat."""
    from src.project_service import get_portfolio

    overview = get_portfolio(client)
    active = [p for p in overview.projects if p.status != "complete"]
    ps = [p.success_p for p in active if p.success_p is not None]
    assert len(ps) >= 10, "not enough active projects to evaluate spread"

    spread = max(ps) - min(ps)
    assert spread >= 0.20, (
        f"P(success) spread too narrow ({spread:.0%}) — "
        f"Aito probably can't distinguish projects."
    )

    mean_p = sum(ps) / len(ps)
    assert 0.30 <= mean_p <= 0.85, (
        f"mean P(success) {mean_p:.0%} suggests miscalibration"
    )

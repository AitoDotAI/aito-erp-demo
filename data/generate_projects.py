"""Generate projects + assignments fixtures.

Produces ~120 projects (90 complete, 30 active) and ~420 person-project
assignments. Uses Finnish names consistent with the existing personnel
seen in purchases.json (managers like M. Hakala, T. Virtanen, etc.).

Project success is engineered to depend on context:
  - Manager × project_type fit (some managers are great at maintenance,
    bad at implementations)
  - Team-size fit per project_type (overstaffed audits = failure;
    understaffed implementations = failure)
  - Specific people are reliably good (A. Lindgren, K. Saari) or
    chaotic (V. Jokinen) — Aito learns this from team_members.
  - Budget overrun risk grows with budget magnitude × short duration.

Run with: python data/generate_projects.py
"""

import json
import random
from pathlib import Path

random.seed(42)
DATA = Path(__file__).resolve().parent

# ── Personnel ───────────────────────────────────────────────────────
# Managers also appear as approvers in purchases.json — keeps the
# demo internally consistent.
MANAGERS = ["M. Hakala", "T. Virtanen", "J. Lehtinen", "K. Mäkinen", "R. Leinonen"]

# Specialists per project type (used as team_lead).
LEADS = {
    "maintenance":    ["P. Korhonen", "T. Virtanen", "S. Niemi"],
    "implementation": ["A. Lindgren", "J. Lehtinen", "M. Salo"],
    "rollout":        ["A. Lindgren", "K. Saari", "L. Aho"],
    "audit":          ["R. Leinonen", "H. Mattila"],
    "rd":             ["E. Heikkinen", "M. Salo", "K. Saari"],
}

# Engineers / consultants who get assigned. Some are reliable, some
# are chaotic — encoded into success rates further down.
TEAM_POOL = [
    "A. Lindgren", "K. Saari", "L. Aho", "P. Korhonen", "S. Niemi",
    "M. Salo", "E. Heikkinen", "H. Mattila", "V. Jokinen", "T. Rinne",
    "O. Halonen", "I. Pulkkinen", "N. Forsberg", "J. Karjalainen",
]

# Reliability profile — used to bias outcomes deterministically.
RELIABLE = {"A. Lindgren", "K. Saari", "P. Korhonen", "M. Salo", "H. Mattila"}
CHAOTIC = {"V. Jokinen", "T. Rinne"}

# Manager × project_type affinity (1.0 = base, >1 = good fit, <1 = bad).
MANAGER_FIT = {
    ("M. Hakala",   "maintenance"):    1.25,
    ("M. Hakala",   "implementation"): 0.75,
    ("T. Virtanen", "maintenance"):    1.20,
    ("T. Virtanen", "rd"):             1.15,
    ("J. Lehtinen", "implementation"): 1.30,
    ("J. Lehtinen", "rollout"):        1.20,
    ("K. Mäkinen",  "rollout"):        1.10,
    ("R. Leinonen", "audit"):          1.30,
    ("R. Leinonen", "rd"):             0.80,
}

PROJECT_TYPES = {
    "maintenance":    {"budget": (8000, 60000),  "duration": (10, 60),   "team": (2, 5),  "weight": 35},
    "implementation": {"budget": (40000, 250000),"duration": (45, 180),  "team": (4, 9),  "weight": 25},
    "rollout":        {"budget": (15000, 80000), "duration": (20, 90),   "team": (3, 6),  "weight": 20},
    "audit":          {"budget": (4000, 25000),  "duration": (5, 25),    "team": (1, 3),  "weight": 10},
    "rd":             {"budget": (20000, 120000),"duration": (30, 150),  "team": (2, 5),  "weight": 10},
}

# Customers — mix of internal cost centres + a few external where it makes sense.
CUSTOMERS = {
    "maintenance":    ["Internal — Production", "Internal — Facilities", "Wärtsilä Oy", "Caverion Suomi"],
    "implementation": ["Internal — IT", "Internal — Production", "Atea Finland"],
    "rollout":        ["Internal — IT", "Internal — Logistics", "Telia Finland Oyj"],
    "audit":          ["Internal — Compliance", "Internal — Finance"],
    "rd":             ["Internal — R&D", "ABB Service", "Siemens Finland"],
}

PRIORITIES = ["low", "medium", "high"]
PRIORITY_WEIGHTS = [25, 50, 25]

# Months 2023-06 through 2025-09 (active span)
MONTHS_HIST = [
    f"{y}-{m:02d}"
    for y in (2023, 2024, 2025)
    for m in range(1, 13)
    if (y, m) >= (2023, 6) and (y, m) <= (2025, 9)
]

NUM_COMPLETED = 90
NUM_ACTIVE = 30


def pick_type() -> str:
    types = list(PROJECT_TYPES.keys())
    weights = [PROJECT_TYPES[t]["weight"] for t in types]
    return random.choices(types, weights=weights, k=1)[0]


def pick_team(ptype: str, team_size: int, exclude: set[str]) -> list[str]:
    """Pick `team_size` people from TEAM_POOL, excluding `exclude` (the lead)."""
    pool = [p for p in TEAM_POOL if p not in exclude]
    return random.sample(pool, k=min(team_size, len(pool)))


def success_probability(
    ptype: str,
    manager: str,
    team_size: int,
    members: list[str],
    budget: float,
    duration: int,
    priority: str,
) -> float:
    """Engineered probability the project succeeds (used to decide outcome).

    Aito then learns this back from the data — the more signal the
    generator embeds, the more impressive the predictions look.
    """
    p = 0.65  # base success rate

    # Manager × type fit
    p *= MANAGER_FIT.get((manager, ptype), 1.0)

    # Team size fit per type
    spec = PROJECT_TYPES[ptype]
    ideal_lo, ideal_hi = spec["team"]
    if team_size < ideal_lo:
        p *= 0.7
    elif team_size > ideal_hi:
        p *= 0.85
    else:
        p *= 1.10

    # Person-level effects
    reliable_count = sum(1 for m in members if m in RELIABLE)
    chaotic_count = sum(1 for m in members if m in CHAOTIC)
    p *= (1.0 + 0.08 * reliable_count)
    p *= (1.0 - 0.18 * chaotic_count)

    # Budget × duration: big budgets + short duration = trouble
    eur_per_day = budget / max(duration, 1)
    if eur_per_day > 2500:
        p *= 0.80

    # Priority — high-priority means more attention but tighter
    # constraints; net slightly negative on outcomes.
    if priority == "high":
        p *= 0.95

    return max(0.05, min(0.97, p))


def make_project(idx: int, completed: bool) -> tuple[dict, list[dict]]:
    ptype = pick_type()
    spec = PROJECT_TYPES[ptype]
    manager = random.choice(MANAGERS)
    lead = random.choice(LEADS[ptype])
    team_size = random.randint(*spec["team"])
    members = pick_team(ptype, team_size, exclude={lead})
    budget = round(random.uniform(*spec["budget"]), -2)
    duration = random.randint(*spec["duration"])
    priority = random.choices(PRIORITIES, weights=PRIORITY_WEIGHTS, k=1)[0]
    customer = random.choice(CUSTOMERS[ptype])
    start_month = random.choice(MONTHS_HIST)

    p_success = success_probability(
        ptype, manager, team_size, members, budget, duration, priority
    )

    if completed:
        success = random.random() < p_success
        # Decompose into on_time / on_budget — correlated with success
        # but not identical (some projects ship late but on budget, etc.)
        on_time = success or (random.random() < 0.35)
        on_budget = success or (random.random() < 0.30)
        if not success:
            # Force at least one failure mode for visible non-success
            if on_time and on_budget:
                if random.random() < 0.5:
                    on_time = False
                else:
                    on_budget = False
        status = "complete"
    else:
        success = None
        on_time = None
        on_budget = None
        status = random.choices(
            ["active", "at_risk", "delayed"],
            weights=[60, 25, 15],
            k=1,
        )[0]

    pid = f"PRJ-{1000 + idx}"
    name = f"{ptype.capitalize()} — {customer.split('—')[-1].strip()} #{idx}"

    project = {
        "project_id": pid,
        "name": name,
        "project_type": ptype,
        "customer": customer,
        "manager": manager,
        "team_lead": lead,
        "team_size": team_size,
        # Tokenized so Aito learns per-person effects without arrays.
        "team_members": " ".join([lead] + members),
        "budget_eur": budget,
        "duration_days": duration,
        "priority": priority,
        "status": status,
        "start_month": start_month,
        "on_time": on_time,
        "on_budget": on_budget,
        "success": success,
    }

    # Build assignment rows — one per person on the project.
    assignments = []
    all_people = [lead] + members
    for i, person in enumerate(all_people):
        role = "lead" if i == 0 else (
            "senior" if person in RELIABLE else "engineer"
        )
        # Allocation: leads ~80%, others 20-80%
        if i == 0:
            allocation = random.choice([60, 80, 100])
        else:
            allocation = random.choice([20, 25, 40, 50, 75, 100])
        assignments.append({
            "assignment_id": f"ASG-{pid}-{i:02d}",
            "project_id": pid,
            "person": person,
            "role": role,
            "allocation_pct": allocation,
        })

    return project, assignments


def main() -> None:
    projects = []
    assignments = []

    for i in range(NUM_COMPLETED):
        p, a = make_project(i, completed=True)
        projects.append(p)
        assignments.extend(a)

    for i in range(NUM_ACTIVE):
        p, a = make_project(NUM_COMPLETED + i, completed=False)
        projects.append(p)
        assignments.extend(a)

    random.shuffle(projects)

    # Sanity report
    completed = [p for p in projects if p["status"] == "complete"]
    successful = [p for p in completed if p["success"]]
    print(f"Generated {len(projects)} projects ({len(completed)} complete, "
          f"{len(projects) - len(completed)} active)")
    print(f"  Success rate (completed): {len(successful)}/{len(completed)} = "
          f"{len(successful)/max(len(completed),1):.0%}")
    print(f"Generated {len(assignments)} assignments")

    with open(DATA / "projects.json", "w") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)
    with open(DATA / "assignments.json", "w") as f:
        json.dump(assignments, f, indent=2, ensure_ascii=False)

    print("Wrote projects.json + assignments.json")


if __name__ == "__main__":
    main()

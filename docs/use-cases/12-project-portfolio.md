# Use case 12 — Project Portfolio

> Predicted success per active project, with a staffing simulator that
> shows P(success) move when you swap a team member.

![Project Portfolio](../../screenshots/11-projects.png)

## What it does

For every active project the page shows the probability it will end
successfully (`success = true`), based on the entire history of
completed projects. Click a row to open the `$why` decomposition: which
factors lifted or dragged the prediction — manager × project_type fit,
team-size band, individual people on the team, budget × duration risk.

A second column lists **staffing factors** — individuals whose presence
on a team has a statistically significant effect on outcomes. Discovered
via `_relate`, not configured.

## Aito query — success forecast

```json
POST /api/v1/_predict
{
  "from": "projects",
  "where": {
    "project_type": "implementation",
    "manager": "J. Lehtinen",
    "team_size": 5,
    "team_members": "A. Lindgren K. Saari M. Salo P. Korhonen L. Aho",
    "budget_eur": 120000,
    "duration_days": 90,
    "priority": "medium"
  },
  "predict": "success",
  "select": ["$p", "feature", { "$why": {} }]
}
```

Returns the top hits for `success=true | false` with probabilities and
the full factor tree. The frontend extracts `P(success=true)` and runs
it through `why_processor.py` to produce the highlighted multiplicative
chain.

## Aito query — staffing factors

```json
POST /api/v1/_relate
{
  "from": "projects",
  "where": { "success": true },
  "relate": "team_members"
}
```

`team_members` is a `Text` column storing space-separated names — Aito
tokenises, so `_relate` surfaces the *individual people* whose presence
on a successful project's team is over-represented. Returns hits with
`lift` and support stats; lift > 1 = boost, lift < 1 = drag.

(An equivalent shape uses the `assignments` table: `from: assignments,
where: {project_success: true}, relate: person`. `project_success` is
denormalised onto each assignment row at fixture-load time. Both
queries answer the same question; we use the `projects.team_members`
form because it's the more natural single-table answer.)

## Schema

```
projects:
  project_id     String   PK
  name           String
  project_type   String   maintenance | implementation | rollout | audit | rd
  customer       String
  manager        String
  team_lead      String
  team_size      Int
  team_members   Text     space-separated names — Aito tokenises so
                          per-person effects become learnable
  budget_eur     Decimal
  duration_days  Int
  priority       String
  status         String   active | at_risk | delayed | complete
  start_month    String
  on_time        Bool?    null until complete
  on_budget      Bool?
  success        Bool?    target field

assignments:
  assignment_id    String  PK
  project_id       String  → projects.project_id
  person           String
  role             String  lead | senior | engineer
  allocation_pct   Int
  project_type     String  denormalised mirror of projects.project_type
  project_success  Bool?   denormalised mirror of projects.success
```

## Tradeoffs / honest notes

- **`team_members` as Text**: tokenisation lets Aito learn per-person
  effects without an array column, but spelling matters. "A. Lindgren"
  and "Anna Lindgren" would look like different people.
- **Confounding**: the staffing-factors lift score reports raw
  correlation. A senior engineer who only takes on simple maintenance
  projects will look like a "boost". This is honest output from
  `_relate`; it's the operator's job to weigh confounders. The page
  notes "treat with care: confounded with project type and seniority".
- **Sample-size guard**: factors with `fOnCondition < 4` are dropped
  to avoid spurious top-list entries.

## Implementation

[`src/project_service.py`](../../src/project_service.py) — three
public functions: `get_portfolio()` (parallel-forecasts every active
project), `forecast_with_override()` (the staffing simulator —
predicts twice with different `team_members`, returns the delta), and
`_staffing_factors_from_relate()`.

The booktest [`tests/test_project_booktest.py`](../../tests/test_project_booktest.py)
validates that the engineered signal is preserved across all three
persona fixtures and (when Aito creds are set) that `_predict` and
`_relate` actually pick that signal up.

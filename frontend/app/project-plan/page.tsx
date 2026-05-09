"use client";

import { useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import type {
  AitoPanelConfig,
  AlternativeAssignee,
  GeneratedPlanResponse,
  PlanTaskCandidate,
  RerankResponse,
} from "@/lib/types";

const PROJECT_TYPES = ["construction", "maintenance", "rollout", "audit", "rd"];
const REGIONS = ["Helsinki", "Tampere", "Oulu"];
const SEASONS = ["winter", "spring", "summer", "autumn"];

const DEFAULT_PANEL: AitoPanelConfig = {
  operation: "_predict + _recommend",
  endpoints: ["_predict", "_recommend"],
  stats: [
    { label: "Tables", value: "tasks" },
    { label: "Targets", value: "assignee · days · cost · success" },
    { label: "Sources", value: "history" },
  ],
  description:
    "Project Plan combines two Aito flows. The generative side runs " +
    "<em>aito.._predict</em> three times per task (assignee_kind, " +
    "subcontractor or assignee_person, planned_days, planned_cost_eur) " +
    "given the task context — drafting a complete plan from precedent " +
    "instead of a hand-coded template. Click any task row to swap to " +
    "the matchmaking flow: <em>aito.._recommend</em> with " +
    "<em>goal:&nbsp;{success:&nbsp;true}</em> ranks subcontractors " +
    "by predicted P(success) for that exact (phase, region, season) " +
    "context.",
  query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"tasks"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"project_type"</span>: <span class="q-v">"construction"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"phase"</span>: <span class="q-v">"mep"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"task_name"</span>: <span class="q-v">"HVAC commissioning"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"region"</span>: <span class="q-v">"Helsinki"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"season"</span>: <span class="q-v">"summer"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"subcontractor"</span><br/>
}`,
  links: [
    { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
    { label: "Recommend API reference", url: "https://aito.ai/docs/api/recommend" },
  ],
};

function pct(p: number): string {
  return `${Math.round(p * 100)}%`;
}

function rerankPanel(
  task: PlanTaskCandidate,
  candidates: AlternativeAssignee[],
): AitoPanelConfig {
  const top = candidates[0];
  const delta =
    top && top.success_p > task.success_p
      ? `Swap to <em>${top.name}</em> → P(success) <em>${pct(top.success_p)}</em>` +
        ` (Δ <em>+${Math.round((top.success_p - task.success_p) * 100)}pp</em>).`
      : "Currently-assigned vendor is at or above the historical best.";
  return {
    operation: "_recommend",
    endpoints: ["_recommend"],
    stats: [
      { label: "Phase", value: task.phase },
      { label: "Currently", value: task.assignee },
      { label: "P(success)", value: pct(task.success_p) },
    ],
    description:
      `Matchmaking for <em>${task.task_name}</em>. Aito's ` +
      `<em>_recommend</em> ranks subcontractors by predicted P(success) ` +
      `given (<em>${task.phase}</em>, <em>${task.assignee_kind}</em> work, ` +
      `region, season). ${delta}`,
    query: `<span class="q-k">POST</span> /api/v1/_recommend<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"tasks"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"phase"</span>: <span class="q-v">"${task.phase}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"assignee_kind"</span>: <span class="q-v">"subcontractor"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"recommend"</span>: <span class="q-p">"subcontractor"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"goal"</span>: { <span class="q-k">"success"</span>: <span class="q-n">true</span> }<br/>
}`,
    links: [
      { label: "Recommend API reference", url: "https://aito.ai/docs/api/recommend" },
    ],
  };
}

export default function ProjectPlanPage() {
  const [projectType, setProjectType] = useState("construction");
  const [region, setRegion] = useState("Helsinki");
  const [season, setSeason] = useState("summer");
  const [budget, setBudget] = useState<string>("200000");

  const [plan, setPlan] = useState<GeneratedPlanResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(DEFAULT_PANEL);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<AlternativeAssignee[]>([]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    setSelectedTask(null);
    setCandidates([]);
    setPanel(DEFAULT_PANEL);
    try {
      const result = await apiFetch<GeneratedPlanResponse>(
        "/api/project-plan/generate/",
        {
          method: "POST",
          body: JSON.stringify({
            project_type: projectType,
            region,
            season,
            estimated_budget_eur: budget ? Number(budget) : null,
          }),
        },
      );
      setPlan(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleTaskClick = async (task: PlanTaskCandidate) => {
    const key = `${task.phase}::${task.task_name}`;
    setSelectedTask(key);
    if (task.assignee_kind !== "subcontractor") {
      // Re-ranking only makes sense for subcontracted tasks.
      setCandidates([]);
      setPanel(rerankPanel(task, []));
      return;
    }
    try {
      const result = await apiFetch<RerankResponse>(
        "/api/project-plan/rerank/",
        {
          method: "POST",
          body: JSON.stringify({
            phase: task.phase,
            project_type: projectType,
            region,
            season,
          }),
        },
      );
      setCandidates(result.candidates);
      setPanel(rerankPanel(task, result.candidates));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const tasksByPhase = plan
    ? plan.tasks.reduce<Record<string, PlanTaskCandidate[]>>((acc, t) => {
        (acc[t.phase] ||= []).push(t);
        return acc;
      }, {})
    : {};

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar title="Project Plan" breadcrumb="Operations" />
        <div className="content-area">
          <div className="content">
            {error && (
              <ErrorState message={error} command="POST /api/project-plan/generate" />
            )}

            {/* Generation form */}
            <section className="card" style={{ padding: 18 }}>
              <div style={{ marginBottom: 12 }}>
                <span className="card-title">Plan a new project</span>
                <p style={{ fontSize: 12, color: "var(--mid)", margin: "4px 0 0" }}>
                  Aito reads the historical task table and drafts the full
                  plan: phases, tasks per phase, the right subcontractor
                  or employee, planned days and cost. ~3 <code>_predict</code>
                  calls per task — watch the latency ticker.
                </p>
              </div>
              <div className="plan-form">
                <label className="plan-field">
                  <span className="plan-label">Project type</span>
                  <select
                    value={projectType}
                    onChange={(e) => setProjectType(e.target.value)}
                  >
                    {PROJECT_TYPES.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </label>
                <label className="plan-field">
                  <span className="plan-label">Region</span>
                  <select value={region} onChange={(e) => setRegion(e.target.value)}>
                    {REGIONS.map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </label>
                <label className="plan-field">
                  <span className="plan-label">Season</span>
                  <select value={season} onChange={(e) => setSeason(e.target.value)}>
                    {SEASONS.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <label className="plan-field">
                  <span className="plan-label">Estimated budget (€)</span>
                  <input
                    type="number"
                    value={budget}
                    onChange={(e) => setBudget(e.target.value)}
                    placeholder="200000"
                  />
                </label>
                <button
                  type="button"
                  className="plan-generate"
                  onClick={handleGenerate}
                  disabled={generating}
                >
                  {generating ? "Drafting…" : "Draft plan with Aito →"}
                </button>
              </div>
            </section>

            {/* KPI strip */}
            {plan && (
              <div className="kpi-row" style={{ marginTop: 16 }}>
                <div className="kpi">
                  <div className="kpi-label">Phases</div>
                  <div className="kpi-val">{plan.phases.length}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Tasks</div>
                  <div className="kpi-val">{plan.tasks.length}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Total days (planned)</div>
                  <div className="kpi-val">{plan.total_planned_days}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Total cost (planned)</div>
                  <div className="kpi-val">{fmtAmount(plan.total_planned_cost_eur)}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Avg P(success)</div>
                  <div className="kpi-val" style={{ color: "var(--green)" }}>
                    {pct(plan.avg_success_p)}
                  </div>
                </div>
              </div>
            )}

            {/* Plan body — phases as groups */}
            {plan && plan.phases.map((phase) => (
              <section key={phase} className="card" style={{ marginTop: 16 }}>
                <div className="card-head">
                  <span className="card-title">
                    <span className="phase-chip">{phase}</span>
                  </span>
                  <span className="card-meta">
                    {tasksByPhase[phase]?.length ?? 0} tasks
                  </span>
                </div>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Task</th>
                      <th>Assignee</th>
                      <th>Kind</th>
                      <th style={{ textAlign: "right" }}>Days</th>
                      <th style={{ textAlign: "right" }}>Cost</th>
                      <th style={{ textAlign: "right" }}>P(success)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(tasksByPhase[phase] ?? []).map((t, i) => {
                      const key = `${t.phase}::${t.task_name}`;
                      return (
                        <tr
                          key={`${phase}-${i}`}
                          className={`clickable${selectedTask === key ? " selected" : ""}`}
                          onClick={() => handleTaskClick(t)}
                        >
                          <td>{t.task_name}</td>
                          <td className="mono" style={{ fontSize: 11.5 }}>{t.assignee}</td>
                          <td>
                            <span
                              className={`badge ${t.assignee_kind === "subcontractor" ? "b-purple" : "b-blue"}`}
                            >
                              {t.assignee_kind}
                            </span>
                          </td>
                          <td className="mono" style={{ textAlign: "right" }}>
                            {t.planned_days}
                          </td>
                          <td className="mono" style={{ textAlign: "right" }}>
                            {fmtAmount(t.planned_cost_eur)}
                          </td>
                          <td style={{ textAlign: "right" }}>
                            <div
                              className={`conf-track ${confClass(t.success_p)}`}
                              style={{ display: "inline-block", verticalAlign: "middle" }}
                            >
                              <div
                                className="conf-fill"
                                style={{ width: `${Math.round(t.success_p * 100)}%` }}
                              />
                            </div>{" "}
                            <span className="mono" style={{ fontSize: 11 }}>
                              {pct(t.success_p)}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </section>
            ))}

            {/* Rerank candidates inline (matchmaking output) */}
            {candidates.length > 0 && (
              <section className="card" style={{ marginTop: 16 }}>
                <div className="card-head">
                  <span className="card-title">Subcontractor matchmaking</span>
                  <span className="card-meta">aito.._recommend</span>
                </div>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Subcontractor</th>
                      <th style={{ textAlign: "right" }}>P(success)</th>
                      <th style={{ textAlign: "right" }}>n</th>
                      <th style={{ textAlign: "right" }}>Avg days</th>
                      <th style={{ textAlign: "right" }}>Avg cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((c, i) => (
                      <tr key={c.name}>
                        <td>
                          {i === 0 && <span className="badge b-green" style={{ marginRight: 6 }}>top</span>}
                          {c.name}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <span className="mono" style={{ fontSize: 11.5 }}>{pct(c.success_p)}</span>
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>{c.coverage}</td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          {c.avg_days != null ? c.avg_days.toFixed(1) : "—"}
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          {c.avg_cost_eur != null ? fmtAmount(c.avg_cost_eur) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

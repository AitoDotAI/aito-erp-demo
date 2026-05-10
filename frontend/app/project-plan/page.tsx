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
  AssigneeOption,
  GeneratedPlanResponse,
  NextAssigneeResponse,
  NextPhaseResponse,
  NextTasksResponse,
  PhaseOption,
  PhasePurchasesResponse,
  PlanTaskCandidate,
  PurchaseSuggestion,
  RerankResponse,
  TaskOption,
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
    "Project Plan combines three Aito flows. The generative side runs " +
    "<em>aito.._predict</em> three times per task (assignee_kind, " +
    "subcontractor or assignee_person, planned_days, planned_cost_eur) " +
    "given the task context — drafting a complete plan from precedent " +
    "instead of a hand-coded template. For each phase it also runs " +
    "<em>aito.._predict</em> on the <em>purchases</em> table to auto-" +
    "draft material POs to the supplier the buyer's history points " +
    "at (the Lemonsoft+Jakamo punchline — Aito routes the spend " +
    "before anyone touches the requisition). Click any task row to " +
    "swap to the matchmaking flow: <em>aito.._recommend</em> with " +
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

type Mode = "idle" | "full" | "walker";

interface BuiltTask {
  phase: string;
  task_name: string;
  assignee: AssigneeOption;
  typical_days: number;
  typical_cost_eur: number;
}

export default function ProjectPlanPage() {
  const [projectType, setProjectType] = useState("construction");
  const [region, setRegion] = useState("Helsinki");
  const [season, setSeason] = useState("summer");
  const [budget, setBudget] = useState<string>("200000");

  const [mode, setMode] = useState<Mode>("idle");
  const [plan, setPlan] = useState<GeneratedPlanResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(DEFAULT_PANEL);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<AlternativeAssignee[]>([]);

  // ── Step-by-step walker state ────────────────────────────────
  const [walkerLoading, setWalkerLoading] = useState(false);
  const [acceptedPhases, setAcceptedPhases] = useState<string[]>([]);
  const [phaseOptions, setPhaseOptions] = useState<PhaseOption[]>([]);
  const [currentPhase, setCurrentPhase] = useState<string | null>(null);
  const [taskOptions, setTaskOptions] = useState<TaskOption[]>([]);
  const [acceptedInPhase, setAcceptedInPhase] = useState<BuiltTask[]>([]);
  const [builtTasks, setBuiltTasks] = useState<BuiltTask[]>([]);
  const [phasePurchases, setPhasePurchases] = useState<PurchaseSuggestion[]>([]);
  // Track which task slot is "asking Aito for an assignee" so we can
  // surface candidates alongside the row instead of as a modal.
  const [resolvingTask, setResolvingTask] = useState<string | null>(null);
  const [assigneeOptions, setAssigneeOptions] = useState<AssigneeOption[]>([]);

  const handleGenerate = async () => {
    setMode("full");
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

  // ── Step-by-step walker handlers ─────────────────────────────

  const fetchNextPhase = async (already: string[]) => {
    setWalkerLoading(true);
    try {
      const r = await apiFetch<NextPhaseResponse>(
        "/api/project-plan/next-phase/",
        {
          method: "POST",
          body: JSON.stringify({
            project_type: projectType, region, season, accepted_phases: already,
          }),
        },
      );
      setPhaseOptions(r.options);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWalkerLoading(false);
    }
  };

  const handleStartWalker = () => {
    setMode("walker");
    setError(null);
    setPlan(null);
    setAcceptedPhases([]);
    setBuiltTasks([]);
    setAcceptedInPhase([]);
    setCurrentPhase(null);
    setPhaseOptions([]);
    setTaskOptions([]);
    setPhasePurchases([]);
    setAssigneeOptions([]);
    setResolvingTask(null);
    fetchNextPhase([]);
  };

  const handlePickPhase = async (option: PhaseOption) => {
    setCurrentPhase(option.phase);
    setAcceptedInPhase([]);
    setTaskOptions([]);
    setWalkerLoading(true);
    try {
      const r = await apiFetch<NextTasksResponse>(
        "/api/project-plan/next-tasks/",
        {
          method: "POST",
          body: JSON.stringify({
            project_type: projectType, region, season,
            phase: option.phase, accepted_task_names: [],
          }),
        },
      );
      setTaskOptions(r.options);
      // Tell the panel what just happened.
      setPanel({
        operation: "_predict",
        endpoints: ["_predict"],
        stats: [
          { label: "Phase", value: option.phase },
          { label: "Picked at", value: `P ${pct(option.p)}` },
          { label: "Typical", value: `${option.typical_task_count} tasks` },
        ],
        description:
          `Building <em>${option.phase}</em>. Aito's <em>_predict</em> on ` +
          `<em>tasks.task_name</em> conditioned on (project_type, phase, ` +
          `region, season) suggested the typical task names from history. ` +
          `Click <em>Accept</em> on a task to ask Aito who should do it.`,
        query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"tasks"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"project_type"</span>: <span class="q-v">"${projectType}"</span>, <span class="q-k">"phase"</span>: <span class="q-v">"${option.phase}"</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"task_name"</span><br/>
}`,
        links: [
          { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
        ],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWalkerLoading(false);
    }
  };

  const handleAskAssignee = async (task: TaskOption) => {
    if (!currentPhase) return;
    setResolvingTask(task.task_name);
    setAssigneeOptions([]);
    try {
      const r = await apiFetch<NextAssigneeResponse>(
        "/api/project-plan/next-assignee/",
        {
          method: "POST",
          body: JSON.stringify({
            project_type: projectType, region, season,
            phase: currentPhase, task_name: task.task_name,
          }),
        },
      );
      setAssigneeOptions(r.options);
      setPanel({
        operation: "_predict",
        endpoints: ["_predict"],
        stats: [
          { label: "Task", value: task.task_name },
          { label: "Top", value: r.options[0]?.name ?? "—" },
          { label: "P(success)", value: pct(r.options[0]?.success_p ?? 0) },
        ],
        description:
          `Aito ran two <em>_predict</em>s back-to-back: first on ` +
          `<em>assignee_kind</em> (subcontractor vs employee), then on ` +
          `the actual assignee, plus <em>_predict success</em> for each ` +
          `candidate. The top option is what history says is most likely; ` +
          `the alternatives let you see what else Aito would consider.`,
        query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"tasks"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"phase"</span>: <span class="q-v">"${currentPhase}"</span>, <span class="q-k">"task_name"</span>: <span class="q-v">"${task.task_name}"</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"subcontractor"</span><br/>
}`,
        links: [
          { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
        ],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleConfirmAssignee = (task: TaskOption, assignee: AssigneeOption) => {
    if (!currentPhase) return;
    const built: BuiltTask = {
      phase: currentPhase,
      task_name: task.task_name,
      assignee,
      typical_days: task.typical_days,
      typical_cost_eur: task.typical_cost_eur,
    };
    setAcceptedInPhase((prev) => [...prev, built]);
    setBuiltTasks((prev) => [...prev, built]);
    setResolvingTask(null);
    setAssigneeOptions([]);
    // Drop this task from the candidates so it doesn't reappear; if the
    // pool runs dry the user can move on to the next phase.
    setTaskOptions((prev) => prev.filter((t) => t.task_name !== task.task_name));
  };

  const handleFinishPhase = async () => {
    if (!currentPhase) return;
    const newAccepted = [...acceptedPhases, currentPhase];
    setAcceptedPhases(newAccepted);
    setWalkerLoading(true);
    try {
      // Two parallel calls: the per-phase POs that just closed, and
      // the next-phase candidates for the cumulative context.
      const [posResp, _] = await Promise.all([
        apiFetch<PhasePurchasesResponse>("/api/project-plan/phase-purchases/", {
          method: "POST",
          body: JSON.stringify({ project_type: projectType, phase: currentPhase }),
        }),
        fetchNextPhase(newAccepted),
      ]);
      setPhasePurchases((prev) => [...prev, ...posResp.purchases]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCurrentPhase(null);
      setAcceptedInPhase([]);
      setTaskOptions([]);
      setResolvingTask(null);
      setAssigneeOptions([]);
      setWalkerLoading(false);
    }
  };

  const handleFinishPlan = () => {
    // Close out — keep what's been built visible but stop offering more.
    setPhaseOptions([]);
    setTaskOptions([]);
    setCurrentPhase(null);
    setAssigneeOptions([]);
    setResolvingTask(null);
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
  const purchasesByPhase = plan
    ? plan.purchases.reduce<Record<string, PurchaseSuggestion[]>>((acc, p) => {
        (acc[p.phase] ||= []).push(p);
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
                  Pick the project context, then either let Aito draft
                  the full plan in one shot — or build it step by step,
                  asking Aito for the next prediction at each click.
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
              </div>
              <div className="plan-actions">
                <button
                  type="button"
                  className="plan-generate"
                  onClick={handleGenerate}
                  disabled={generating || walkerLoading}
                >
                  {generating ? "Drafting…" : "Draft full plan with Aito →"}
                </button>
                <button
                  type="button"
                  className="plan-walker"
                  onClick={handleStartWalker}
                  disabled={generating || walkerLoading}
                >
                  Build step-by-step ↻
                </button>
              </div>
            </section>

            {/* Step-by-step walker */}
            {mode === "walker" && (
              <section className="card walker-card" style={{ marginTop: 16 }}>
                <div className="card-head">
                  <span className="card-title">Step-by-step walker</span>
                  <span className="card-meta">
                    aito.._predict at every choice
                  </span>
                </div>

                {/* Built-so-far summary */}
                {builtTasks.length > 0 && (
                  <div className="walker-built">
                    <div className="walker-built-head">
                      Plan so far · {acceptedPhases.length + (currentPhase ? 1 : 0)} phase(s) ·{" "}
                      {builtTasks.length} task(s)
                    </div>
                    {[...acceptedPhases, ...(currentPhase ? [currentPhase] : [])].map((ph) => {
                      const rows = builtTasks.filter((t) => t.phase === ph);
                      if (rows.length === 0) return null;
                      return (
                        <div key={ph} className="walker-built-phase">
                          <span className="phase-chip">{ph}</span>
                          <ul>
                            {rows.map((r, i) => (
                              <li key={i}>
                                <span className="walker-built-name">{r.task_name}</span>
                                <span className="walker-built-meta">
                                  → {r.assignee.name}{" "}
                                  <span className="mono">P(succ) {pct(r.assignee.success_p)}</span>
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Picking a phase */}
                {!currentPhase && phaseOptions.length > 0 && (
                  <div className="walker-stage">
                    <div className="walker-stage-title">
                      {acceptedPhases.length === 0
                        ? "Pick the first phase"
                        : `Pick the next phase (${acceptedPhases.length} so far)`}
                    </div>
                    <div className="walker-options">
                      {phaseOptions.map((p) => (
                        <button
                          key={p.phase}
                          type="button"
                          className="walker-option walker-option-phase"
                          onClick={() => handlePickPhase(p)}
                        >
                          <span className="phase-chip">{p.phase}</span>
                          <span className="walker-option-meta">
                            <span className="mono">P {pct(p.p)}</span>
                            {" · "}
                            <span className="mono">~{p.typical_task_count} tasks</span>
                          </span>
                        </button>
                      ))}
                    </div>
                    {acceptedPhases.length > 0 && (
                      <button
                        type="button"
                        className="walker-finish"
                        onClick={handleFinishPlan}
                      >
                        I'm done — finish plan
                      </button>
                    )}
                  </div>
                )}

                {/* Picking tasks for the current phase */}
                {currentPhase && (
                  <div className="walker-stage">
                    <div className="walker-stage-title">
                      Tasks for <span className="phase-chip">{currentPhase}</span>
                    </div>
                    {taskOptions.length === 0 && acceptedInPhase.length === 0 && (
                      <div className="walker-empty">No more tasks suggested for this phase.</div>
                    )}
                    <div className="walker-tasks">
                      {taskOptions.map((t) => (
                        <div key={t.task_name} className="walker-task">
                          <div className="walker-task-row">
                            <span className="walker-task-name">{t.task_name}</span>
                            <span className="walker-task-meta">
                              <span className="mono">P {pct(t.p)}</span>
                              {" · "}
                              <span className="mono">~{t.typical_days}d</span>
                              {" · "}
                              <span className="mono">{fmtAmount(t.typical_cost_eur)}</span>
                            </span>
                            <button
                              type="button"
                              className="walker-task-accept"
                              onClick={() => handleAskAssignee(t)}
                              disabled={resolvingTask === t.task_name}
                            >
                              {resolvingTask === t.task_name ? "Asking Aito…" : "Accept"}
                            </button>
                          </div>
                          {resolvingTask === t.task_name && assigneeOptions.length > 0 && (
                            <div className="walker-assignees">
                              <div className="walker-assignees-head">
                                Aito's top {assigneeOptions.length} picks for this task
                              </div>
                              {assigneeOptions.map((a, i) => (
                                <button
                                  key={a.name}
                                  type="button"
                                  className={`walker-assignee${i === 0 ? " is-top" : ""}`}
                                  onClick={() => handleConfirmAssignee(t, a)}
                                >
                                  {i === 0 && <span className="badge b-green">top</span>}
                                  <span className="walker-assignee-name">{a.name}</span>
                                  <span className={`badge ${a.assignee_kind === "subcontractor" ? "b-purple" : "b-blue"}`}>
                                    {a.assignee_kind}
                                  </span>
                                  <span className="walker-assignee-meta mono">
                                    P {pct(a.p)} · P(succ) {pct(a.success_p)}
                                  </span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                    <div className="walker-actions">
                      <button
                        type="button"
                        className="walker-finish"
                        onClick={handleFinishPhase}
                        disabled={walkerLoading}
                      >
                        {acceptedInPhase.length === 0
                          ? "Skip this phase →"
                          : `Done with ${currentPhase} (${acceptedInPhase.length} task${acceptedInPhase.length === 1 ? "" : "s"}) →`}
                      </button>
                    </div>
                  </div>
                )}

                {/* Accumulated material POs from finished phases */}
                {phasePurchases.length > 0 && (
                  <div className="walker-pos">
                    <div className="walker-stage-title" style={{ marginTop: 4 }}>
                      Material POs auto-drafted across the finished phases
                    </div>
                    {phasePurchases.map((po, i) => (
                      <div key={i} className="phase-po">
                        <span className="badge b-gold">{po.phase}</span>
                        <span className="walker-po-cat">{po.category}</span>
                        <span className="phase-po-supplier">{po.supplier}</span>
                        <span className="phase-po-meta">
                          <span className="mono">P {pct(po.supplier_confidence)}</span>
                          {po.typical_amount_eur != null && (
                            <>
                              {" · "}
                              <span className="mono">~{fmtAmount(po.typical_amount_eur)}</span>
                            </>
                          )}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {walkerLoading && (
                  <div className="walker-loading">Asking Aito…</div>
                )}
              </section>
            )}

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
                <div className="kpi">
                  <div className="kpi-label">Auto-drafted POs</div>
                  <div className="kpi-val">
                    {plan.purchases.length}
                  </div>
                  <div className="kpi-sub">
                    {fmtAmount(plan.total_purchases_eur)} total
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

                {/* Per-phase auto-drafted POs (materials + supplier).
                    Empty for admin-style phases (planning, design, …). */}
                {(purchasesByPhase[phase] ?? []).length > 0 && (
                  <div className="phase-pos">
                    <div className="phase-pos-head">
                      <span className="phase-pos-label">Material POs · </span>
                      <span className="phase-pos-meta">
                        aito.._predict supplier from purchase history
                      </span>
                    </div>
                    <div className="phase-pos-list">
                      {(purchasesByPhase[phase] ?? []).map((po, i) => (
                        <div key={i} className="phase-po">
                          <span className="badge b-gold">{po.category}</span>
                          <span className="phase-po-supplier">{po.supplier}</span>
                          <span className="phase-po-meta">
                            <span className="mono">P {pct(po.supplier_confidence)}</span>
                            {po.typical_amount_eur != null && (
                              <>
                                {" · "}
                                <span className="mono">~{fmtAmount(po.typical_amount_eur)}</span>
                              </>
                            )}
                            <span style={{ color: "var(--mid)" }}> · n={po.coverage}</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
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

"use client";

import { Fragment, useState } from "react";
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
  id: string;            // stable key — task_name can repeat across phases otherwise
  phase: string;
  task_name: string;
  assignee: AssigneeOption;
  typical_days: number;
  typical_cost_eur: number;
}

let _taskIdSeq = 0;
const nextTaskId = () => `bt-${++_taskIdSeq}`;

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

  // ── Plan editor state ────────────────────────────────────────
  // The walker builds the plan, but every accepted task and phase is
  // editable afterwards: delete, swap assignee, add more tasks to an
  // existing phase, or add a new phase at any time. The state below
  // covers both the "build" affordances (candidate panels) and the
  // "edit" affordances (per-task swap / delete) on the same data.
  const [walkerLoading, setWalkerLoading] = useState(false);
  const [acceptedPhases, setAcceptedPhases] = useState<string[]>([]);
  const [builtTasks, setBuiltTasks] = useState<BuiltTask[]>([]);
  const [phasePurchases, setPhasePurchases] = useState<PurchaseSuggestion[]>([]);

  // "Pick a phase" panel — open when user clicks "Add phase" or at
  // walker bootstrap. Closes once a phase is picked (or cancelled).
  const [phaseOptions, setPhaseOptions] = useState<PhaseOption[]>([]);
  const [pickingPhase, setPickingPhase] = useState(false);

  // "Pick tasks for <phase>" panel — open when user clicks "+ Add
  // task in <phase>" or right after picking the phase itself. The
  // panel can re-open on demand for any phase, so the user can add
  // more tasks to a finished phase.
  const [pickingTasksFor, setPickingTasksFor] = useState<string | null>(null);
  const [taskOptions, setTaskOptions] = useState<TaskOption[]>([]);

  // "Pick assignee for <pendingTaskName> in <pendingPhase>" — the
  // user clicked Accept on a task candidate and Aito is fanning out
  // alternatives. Shared by the swap-assignee flow on existing tasks
  // (then `swapForTaskId` is set instead).
  const [pendingTaskCandidate, setPendingTaskCandidate] = useState<TaskOption | null>(null);
  const [swapForTaskId, setSwapForTaskId] = useState<string | null>(null);
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

  // ── Plan editor handlers ─────────────────────────────────────

  const closeAllPickers = () => {
    setPickingPhase(false);
    setPickingTasksFor(null);
    setPendingTaskCandidate(null);
    setSwapForTaskId(null);
    setAssigneeOptions([]);
    setPhaseOptions([]);
    setTaskOptions([]);
  };

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

  const fetchNextTasks = async (phase: string) => {
    const acceptedNames = builtTasks.filter((t) => t.phase === phase).map((t) => t.task_name);
    setWalkerLoading(true);
    try {
      const r = await apiFetch<NextTasksResponse>(
        "/api/project-plan/next-tasks/",
        {
          method: "POST",
          body: JSON.stringify({
            project_type: projectType, region, season, phase,
            accepted_task_names: acceptedNames,
          }),
        },
      );
      setTaskOptions(r.options);
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
    setPhasePurchases([]);
    closeAllPickers();
    setPickingPhase(true);
    fetchNextPhase([]);
    setPanel(DEFAULT_PANEL);
  };

  // Open the phase picker on demand (used by "+ Add phase" too).
  const handleOpenPhasePicker = () => {
    setMode("walker");
    setError(null);
    closeAllPickers();
    setPickingPhase(true);
    fetchNextPhase(acceptedPhases);
  };

  const handlePickPhase = async (option: PhaseOption) => {
    if (!acceptedPhases.includes(option.phase)) {
      setAcceptedPhases((prev) => [...prev, option.phase]);
      // Fire phase-purchases in the background so material POs are
      // ready by the time the user finishes adding tasks.
      apiFetch<PhasePurchasesResponse>("/api/project-plan/phase-purchases/", {
        method: "POST",
        body: JSON.stringify({ project_type: projectType, phase: option.phase }),
      }).then((resp) => {
        setPhasePurchases((prev) => [
          ...prev.filter((p) => p.phase !== option.phase),
          ...resp.purchases,
        ]);
      }).catch(() => { /* non-fatal — POs are advisory */ });
    }
    setPickingPhase(false);
    setPhaseOptions([]);
    setPickingTasksFor(option.phase);
    await fetchNextTasks(option.phase);
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: "Phase", value: option.phase },
        { label: "Picked at", value: `P ${pct(option.p)}` },
        { label: "Typical", value: `${option.typical_task_count} tasks` },
      ],
      description:
        `Editing <em>${option.phase}</em>. Aito's <em>_search</em> over ` +
        `<em>tasks</em> for the (project_type, phase) slice surfaced the ` +
        `typical task names from history. Click <em>Accept</em> on a ` +
        `candidate to ask Aito who should do it. Each accepted task is ` +
        `editable afterwards — swap assignee, delete, or add more.`,
      query: `<span class="q-k">POST</span> /api/v1/_search<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"tasks"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"project_type"</span>: <span class="q-v">"${projectType}"</span>, <span class="q-k">"phase"</span>: <span class="q-v">"${option.phase}"</span> }<br/>
}`,
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const fetchAssigneeOptions = async (phase: string, taskName: string) => {
    try {
      const r = await apiFetch<NextAssigneeResponse>(
        "/api/project-plan/next-assignee/",
        {
          method: "POST",
          body: JSON.stringify({
            project_type: projectType, region, season, phase, task_name: taskName,
          }),
        },
      );
      setAssigneeOptions(r.options);
      setPanel({
        operation: "_predict",
        endpoints: ["_predict"],
        stats: [
          { label: "Task", value: taskName },
          { label: "Top", value: r.options[0]?.name ?? "—" },
          { label: "P(success)", value: pct(r.options[0]?.success_p ?? 0) },
        ],
        description:
          `Aito ran two <em>_predict</em>s back-to-back: first on ` +
          `<em>assignee_kind</em>, then on the actual assignee, plus ` +
          `<em>_predict success</em> for each candidate. Pick the top ` +
          `(what history most likely matches) or any of the alternatives ` +
          `to swap.`,
        query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"tasks"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"phase"</span>: <span class="q-v">"${phase}"</span>, <span class="q-k">"task_name"</span>: <span class="q-v">"${taskName}"</span> },<br/>
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

  // User clicked Accept on a task *candidate* — start the assignee
  // fan-out so they can confirm or pick an alternative.
  const handleAcceptCandidate = async (task: TaskOption, phase: string) => {
    setPendingTaskCandidate(task);
    setSwapForTaskId(null);
    setAssigneeOptions([]);
    await fetchAssigneeOptions(phase, task.task_name);
  };

  // Confirm the assignee for a *new* task being added.
  const handleConfirmNewTask = (task: TaskOption, phase: string, assignee: AssigneeOption) => {
    const built: BuiltTask = {
      id: nextTaskId(),
      phase,
      task_name: task.task_name,
      assignee,
      typical_days: task.typical_days,
      typical_cost_eur: task.typical_cost_eur,
    };
    setBuiltTasks((prev) => [...prev, built]);
    setPendingTaskCandidate(null);
    setAssigneeOptions([]);
    // Drop the candidate from the picker; if more remain, the user can keep adding.
    setTaskOptions((prev) => prev.filter((t) => t.task_name !== task.task_name));
  };

  // User clicked an existing task's assignee chip — swap mode.
  const handleSwapAssignee = async (taskId: string) => {
    const task = builtTasks.find((t) => t.id === taskId);
    if (!task) return;
    setSwapForTaskId(taskId);
    setPendingTaskCandidate(null);
    setAssigneeOptions([]);
    await fetchAssigneeOptions(task.phase, task.task_name);
  };

  const handleConfirmSwap = (taskId: string, assignee: AssigneeOption) => {
    setBuiltTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, assignee } : t)),
    );
    setSwapForTaskId(null);
    setAssigneeOptions([]);
  };

  const handleDeleteTask = (taskId: string) => {
    setBuiltTasks((prev) => prev.filter((t) => t.id !== taskId));
    if (swapForTaskId === taskId) setSwapForTaskId(null);
  };

  const handleAddTaskToPhase = async (phase: string) => {
    closeAllPickers();
    setPickingTasksFor(phase);
    await fetchNextTasks(phase);
  };

  const handleRemovePhase = (phase: string) => {
    setBuiltTasks((prev) => prev.filter((t) => t.phase !== phase));
    setAcceptedPhases((prev) => prev.filter((p) => p !== phase));
    setPhasePurchases((prev) => prev.filter((p) => p.phase !== phase));
    if (pickingTasksFor === phase) setPickingTasksFor(null);
  };

  const handleDeletePO = (phase: string, category: string, supplier: string) => {
    setPhasePurchases((prev) =>
      prev.filter((p) => !(p.phase === phase && p.category === category && p.supplier === supplier)),
    );
  };

  const handleEditTaskField = (taskId: string, field: "typical_days" | "typical_cost_eur", value: number) => {
    setBuiltTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, [field]: value } : t)),
    );
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

            {/* Plan editor (step-by-step build + free editing) */}
            {mode === "walker" && (
              <section className="card walker-card" style={{ marginTop: 16 }}>
                <div className="card-head">
                  <span className="card-title">
                    Plan editor · {acceptedPhases.length} phase{acceptedPhases.length === 1 ? "" : "s"} ·{" "}
                    {builtTasks.length} task{builtTasks.length === 1 ? "" : "s"}
                  </span>
                  <span className="card-meta">
                    aito.._predict on every edit
                  </span>
                </div>

                {/* Per-phase editor sections */}
                {acceptedPhases.map((ph) => {
                  const rows = builtTasks.filter((t) => t.phase === ph);
                  const isPickingTasksHere = pickingTasksFor === ph;
                  const phasePos = phasePurchases.filter((p) => p.phase === ph);
                  return (
                    <div key={ph} className="editor-phase">
                      <div className="editor-phase-head">
                        <span className="phase-chip">{ph}</span>
                        <span className="editor-phase-count">
                          {rows.length} task{rows.length === 1 ? "" : "s"}
                        </span>
                        <button
                          type="button"
                          className="editor-add-task"
                          onClick={() => handleAddTaskToPhase(ph)}
                          disabled={walkerLoading}
                        >
                          + Add task
                        </button>
                        <button
                          type="button"
                          className="editor-remove-phase"
                          onClick={() => handleRemovePhase(ph)}
                          title="Remove phase and all its tasks"
                        >
                          ×
                        </button>
                      </div>

                      {/* Accepted tasks — editable rows */}
                      {rows.length > 0 && (
                        <table className="tbl editor-tbl">
                          <thead>
                            <tr>
                              <th>Task</th>
                              <th>Assignee</th>
                              <th style={{ textAlign: "right" }}>Days</th>
                              <th style={{ textAlign: "right" }}>Cost</th>
                              <th style={{ textAlign: "right" }}>P(success)</th>
                              <th></th>
                            </tr>
                          </thead>
                          <tbody>
                            {rows.map((row) => (
                              <Fragment key={row.id}>
                                <tr>
                                  <td>{row.task_name}</td>
                                  <td>
                                    <button
                                      type="button"
                                      className="editor-assignee-chip"
                                      onClick={() => handleSwapAssignee(row.id)}
                                      title="Click to ask Aito for alternatives"
                                    >
                                      <span className={`badge ${row.assignee.assignee_kind === "subcontractor" ? "b-purple" : "b-blue"}`}>
                                        {row.assignee.assignee_kind}
                                      </span>
                                      <span className="editor-assignee-name">{row.assignee.name}</span>
                                      <span className="editor-assignee-swap" aria-hidden="true">↻</span>
                                    </button>
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    <input
                                      type="number"
                                      className="editor-numeric"
                                      value={row.typical_days}
                                      min={0}
                                      onChange={(e) =>
                                        handleEditTaskField(row.id, "typical_days", Number(e.target.value) || 0)
                                      }
                                    />
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    <input
                                      type="number"
                                      className="editor-numeric editor-numeric-wide"
                                      value={row.typical_cost_eur}
                                      min={0}
                                      step={100}
                                      onChange={(e) =>
                                        handleEditTaskField(row.id, "typical_cost_eur", Number(e.target.value) || 0)
                                      }
                                    />
                                  </td>
                                  <td style={{ textAlign: "right" }} className="mono">
                                    {pct(row.assignee.success_p)}
                                  </td>
                                  <td>
                                    <button
                                      type="button"
                                      className="editor-row-delete"
                                      onClick={() => handleDeleteTask(row.id)}
                                      title="Delete task"
                                    >
                                      ×
                                    </button>
                                  </td>
                                </tr>
                                {/* Inline assignee swap panel for this row */}
                                {swapForTaskId === row.id && assigneeOptions.length > 0 && (
                                  <tr className="editor-inline-row">
                                    <td colSpan={6}>
                                      <div className="walker-assignees">
                                        <div className="walker-assignees-head">
                                          Aito's top {assigneeOptions.length} alternatives — click to swap
                                        </div>
                                        {assigneeOptions.map((a, i) => (
                                          <button
                                            key={a.name}
                                            type="button"
                                            className={`walker-assignee${i === 0 ? " is-top" : ""}${
                                              a.name === row.assignee.name ? " is-current" : ""
                                            }`}
                                            onClick={() => handleConfirmSwap(row.id, a)}
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
                                        <button
                                          type="button"
                                          className="walker-assignee-cancel"
                                          onClick={() => { setSwapForTaskId(null); setAssigneeOptions([]); }}
                                        >
                                          Cancel
                                        </button>
                                      </div>
                                    </td>
                                  </tr>
                                )}
                              </Fragment>
                            ))}
                          </tbody>
                        </table>
                      )}

                      {/* Task candidate picker — shown when the user clicked + Add task */}
                      {isPickingTasksHere && (
                        <div className="editor-picker">
                          <div className="walker-stage-title">
                            Aito's task suggestions for {ph}
                          </div>
                          {taskOptions.length === 0 && !walkerLoading && (
                            <div className="walker-empty">
                              No more tasks suggested. (You've accepted them all, or this phase is unusual.)
                            </div>
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
                                    onClick={() => handleAcceptCandidate(t, ph)}
                                    disabled={pendingTaskCandidate?.task_name === t.task_name}
                                  >
                                    {pendingTaskCandidate?.task_name === t.task_name ? "Asking Aito…" : "Accept"}
                                  </button>
                                </div>
                                {pendingTaskCandidate?.task_name === t.task_name && assigneeOptions.length > 0 && (
                                  <div className="walker-assignees">
                                    <div className="walker-assignees-head">
                                      Aito's top {assigneeOptions.length} picks for this task — click to confirm
                                    </div>
                                    {assigneeOptions.map((a, i) => (
                                      <button
                                        key={a.name}
                                        type="button"
                                        className={`walker-assignee${i === 0 ? " is-top" : ""}`}
                                        onClick={() => handleConfirmNewTask(t, ph, a)}
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
                              onClick={() => { setPickingTasksFor(null); setTaskOptions([]); setPendingTaskCandidate(null); setAssigneeOptions([]); }}
                            >
                              Done editing {ph}
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Per-phase auto-drafted POs (deletable) */}
                      {phasePos.length > 0 && (
                        <div className="editor-pos">
                          <div className="editor-pos-head">
                            <span>Material POs · auto-drafted</span>
                          </div>
                          {phasePos.map((po, i) => (
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
                              </span>
                              <button
                                type="button"
                                className="editor-row-delete"
                                onClick={() => handleDeletePO(po.phase, po.category, po.supplier)}
                                title="Remove this PO from the draft"
                              >
                                ×
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}

                {/* Phase picker — shown by default at bootstrap and on demand via "+ Add phase" */}
                {pickingPhase && (
                  <div className="editor-picker editor-picker-phase">
                    <div className="walker-stage-title">
                      {acceptedPhases.length === 0
                        ? "Pick the first phase"
                        : "Pick another phase to add"}
                    </div>
                    {phaseOptions.length === 0 && !walkerLoading && (
                      <div className="walker-empty">No more phases suggested.</div>
                    )}
                    <div className="walker-options">
                      {phaseOptions.map((p) => (
                        <button
                          key={p.phase}
                          type="button"
                          className="walker-option walker-option-phase"
                          onClick={() => handlePickPhase(p)}
                          disabled={walkerLoading}
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
                        className="walker-finish editor-cancel-phase"
                        onClick={() => { setPickingPhase(false); setPhaseOptions([]); }}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                )}

                {/* Footer: + Add phase always available so the editor never feels "done" */}
                {!pickingPhase && acceptedPhases.length > 0 && (
                  <div className="editor-footer">
                    <button
                      type="button"
                      className="editor-add-phase"
                      onClick={handleOpenPhasePicker}
                      disabled={walkerLoading}
                    >
                      + Add phase
                    </button>
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

"use client";

import { Fragment, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import WhyPopover from "@/components/prediction/WhyPopover";
import type {
  AitoPanelConfig,
  AssigneeOption,
  GeneratedPlanResponse,
  MaterialSuggestion,
  NextAssigneeResponse,
  NextPhaseResponse,
  NextTasksResponse,
  PhaseOption,
  SupplierOption,
  SwapSupplierResponse,
  TaskMaterialsResponse,
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
    "Project Plan combines Aito flows on a single editable surface. " +
    "The generative side runs <em>aito.._predict</em> per task on the " +
    "<em>tasks</em> table for assignee_kind, subcontractor or " +
    "assignee_person, planned_days, planned_cost_eur — drafting a " +
    "plan from precedent rather than a template. Beneath each task " +
    "it then fans out on the <em>purchases</em> table: a " +
    "<em>_search</em> with <em>$has</em> overlap finds the product " +
    "lines whose vocabulary matches the task name (\"Steel erection\" " +
    "→ \"Steel erection batch\"), and two <em>_predict</em>s give " +
    "the historically right supplier and the estimated EUR amount for " +
    "that exact line. Click any supplier chip to open the swap " +
    "dropdown: Aito's history-ranked candidates (with the full " +
    "<em>$why</em> popover) plus newly-registered suppliers piped in " +
    "from the acquired supplier management system — a sales/" +
    "distribution channel that lets suppliers reach the planner " +
    "directly. Every cell is editable; the live KPI strip recomputes " +
    "in place.",
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
    { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/16-project-plan.md", kind: "doc" },
    { label: "Source code", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/task_service.py", kind: "github" },
  ],
};

function pct(p: number): string {
  return `${Math.round(p * 100)}%`;
}

function supplierSwapPanel(
  phase: string,
  category: string,
  description: string,
  options: SupplierOption[],
): AitoPanelConfig {
  const history = options.filter((o) => o.source === "history");
  const portal = options.filter((o) => o.source === "portal");
  const top = history[0];
  return {
    operation: "_predict",
    endpoints: ["_predict"],
    stats: [
      { label: "Phase", value: phase },
      { label: "Product line", value: description },
      { label: "Category", value: category },
      { label: "Top", value: top ? `${top.supplier} · ${pct(top.confidence)}` : "—" },
    ],
    description:
      `Swapping supplier for <em>${description}</em>. Aito's ` +
      `<em>_predict from=purchases predict=supplier</em> conditions on ` +
      `(<em>category=${category}</em>, <em>description=${description}</em>) ` +
      `to surface who actually supplies this product line in history — ` +
      `${history.length} match${history.length === 1 ? "" : "es"} ` +
      `(click <em>?</em> for the full <em>$why</em>). ` +
      `${portal.length > 0
        ? `Below them, ${portal.length} candidate${portal.length === 1 ? "" : "s"} from the ` +
          `acquired supplier management system — suppliers that registered ` +
          `against <em>${category}</em> via the portal, pushed straight into ` +
          `the planning view as a sales/distribution channel.`
        : "No portal listings registered for this category yet."}`,
    query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"category"</span>: <span class="q-v">"${category}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"description"</span>: <span class="q-v">"${description}"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"supplier"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"limit"</span>: <span class="q-n">5</span><br/>
}`,
    links: [
      { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
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
  // Materials arrive async — `null` means "Aito is still fanning out
  // _predict supplier + _predict amount_eur for the product lines";
  // `[]` means "Aito returned nothing for this phase's categories";
  // a populated array is what the editor renders.
  materials: MaterialSuggestion[] | null;
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

  // ── Plan editor state ────────────────────────────────────────
  // The walker builds the plan, but every accepted task and phase is
  // editable afterwards: delete, swap assignee, add more tasks to an
  // existing phase, or add a new phase at any time. The state below
  // covers both the "build" affordances (candidate panels) and the
  // "edit" affordances (per-task swap / delete) on the same data.
  const [walkerLoading, setWalkerLoading] = useState(false);
  const [acceptedPhases, setAcceptedPhases] = useState<string[]>([]);
  const [builtTasks, setBuiltTasks] = useState<BuiltTask[]>([]);

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

  // Material supplier swap. Key is (taskId, materialIndex) — uniquely
  // identifies the row to mutate within `builtTasks[*].materials`.
  // `loadingSwap` is true while the _predict round-trip is in flight.
  const [swapForMaterial, setSwapForMaterial] = useState<
    { taskId: string; materialIdx: number } | null
  >(null);
  const [supplierOptions, setSupplierOptions] = useState<SupplierOption[]>([]);
  const [loadingSwap, setLoadingSwap] = useState(false);

  const handleGenerate = async () => {
    // The full-plan path lands in the same editable surface as the
    // step-by-step walker — one model, two ways to populate it. The
    // user can immediately edit anything: assignee, days, cost,
    // materials, supplier per material.
    setMode("walker");
    setGenerating(true);
    setError(null);
    setPanel(DEFAULT_PANEL);
    closeAllPickers();
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
      setAcceptedPhases(result.phases);
      setBuiltTasks(
        result.tasks.map((t) => ({
          id: nextTaskId(),
          phase: t.phase,
          task_name: t.task_name,
          assignee: {
            assignee_kind: t.assignee_kind,
            name: t.assignee,
            p: t.assignee_confidence,
            success_p: t.success_p,
          },
          typical_days: t.planned_days,
          typical_cost_eur: t.planned_cost_eur,
          materials: t.materials,
        })),
      );
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

  // Confirm the assignee for a *new* task being added. Materials are
  // fetched in the background — the row appears with a "predicting
  // materials…" hint, then fills in when Aito's _predict supplier +
  // _predict amount_eur fan-out completes.
  const handleConfirmNewTask = (task: TaskOption, phase: string, assignee: AssigneeOption) => {
    const built: BuiltTask = {
      id: nextTaskId(),
      phase,
      task_name: task.task_name,
      assignee,
      typical_days: task.typical_days,
      typical_cost_eur: task.typical_cost_eur,
      materials: null,
    };
    setBuiltTasks((prev) => [...prev, built]);
    setPendingTaskCandidate(null);
    setAssigneeOptions([]);
    setTaskOptions((prev) => prev.filter((t) => t.task_name !== task.task_name));

    apiFetch<TaskMaterialsResponse>("/api/project-plan/task-materials/", {
      method: "POST",
      body: JSON.stringify({ phase, task_name: task.task_name }),
    }).then((resp) => {
      setBuiltTasks((prev) =>
        prev.map((t) => (t.id === built.id ? { ...t, materials: resp.materials } : t)),
      );
    }).catch(() => {
      // Non-fatal — empty materials list lets the user add manually.
      setBuiltTasks((prev) =>
        prev.map((t) => (t.id === built.id ? { ...t, materials: [] } : t)),
      );
    });
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
    if (pickingTasksFor === phase) setPickingTasksFor(null);
  };

  // Delete a single material line from a task's materials array.
  const handleDeleteMaterial = (taskId: string, materialIdx: number) => {
    setBuiltTasks((prev) =>
      prev.map((t) => {
        if (t.id !== taskId || !t.materials) return t;
        return { ...t, materials: t.materials.filter((_, i) => i !== materialIdx) };
      }),
    );
    if (
      swapForMaterial &&
      swapForMaterial.taskId === taskId &&
      swapForMaterial.materialIdx === materialIdx
    ) {
      setSwapForMaterial(null);
      setSupplierOptions([]);
    }
  };

  // Edit a material's estimated amount in place.
  const handleEditMaterialAmount = (taskId: string, materialIdx: number, value: number) => {
    setBuiltTasks((prev) =>
      prev.map((t) => {
        if (t.id !== taskId || !t.materials) return t;
        return {
          ...t,
          materials: t.materials.map((m, i) =>
            i === materialIdx ? { ...m, estimated_amount_eur: value } : m,
          ),
        };
      }),
    );
  };

  // Open the supplier dropdown for one material line. Scopes the
  // _predict to (category, description) so candidates are who actually
  // supplies this product line in history.
  const handleOpenMaterialSwap = async (taskId: string, materialIdx: number) => {
    if (
      swapForMaterial &&
      swapForMaterial.taskId === taskId &&
      swapForMaterial.materialIdx === materialIdx
    ) {
      setSwapForMaterial(null);
      setSupplierOptions([]);
      return;
    }
    const task = builtTasks.find((t) => t.id === taskId);
    const material = task?.materials?.[materialIdx];
    if (!task || !material) return;
    setSwapForMaterial({ taskId, materialIdx });
    setSupplierOptions([]);
    setLoadingSwap(true);
    try {
      const r = await apiFetch<SwapSupplierResponse>(
        "/api/project-plan/swap-supplier/",
        {
          method: "POST",
          body: JSON.stringify({
            category: material.category,
            description: material.description,
          }),
        },
      );
      setSupplierOptions(r.options);
      setPanel(supplierSwapPanel(task.phase, material.category, material.description, r.options));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingSwap(false);
    }
  };

  const handleConfirmMaterialSupplier = (
    taskId: string,
    materialIdx: number,
    next: SupplierOption,
  ) => {
    setBuiltTasks((prev) =>
      prev.map((t) => {
        if (t.id !== taskId || !t.materials) return t;
        return {
          ...t,
          materials: t.materials.map((m, i) => {
            if (i !== materialIdx) return m;
            return {
              ...m,
              supplier: next.supplier,
              supplier_source: next.source,
              supplier_confidence: next.source === "history" ? next.confidence : 0,
              supplier_why: next.source === "history" ? next.why : null,
              // Portal candidate has no historical amount yet — keep
              // whatever the planner had typed in (they can re-estimate
              // from a quote). History candidate inherits the historical
              // mean when available.
              estimated_amount_eur:
                next.source === "history" && next.avg_amount_eur != null
                  ? next.avg_amount_eur
                  : m.estimated_amount_eur,
              coverage: next.source === "history" ? next.coverage : 0,
            };
          }),
        };
      }),
    );
    setSwapForMaterial(null);
    setSupplierOptions([]);
  };

  const handleEditTaskField = (taskId: string, field: "typical_days" | "typical_cost_eur", value: number) => {
    setBuiltTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, [field]: value } : t)),
    );
  };

  // Live KPIs from the editable state — reflects any edits the
  // planner has made (added/deleted tasks, swapped suppliers, etc.).
  const totalDays = builtTasks.reduce((s, t) => s + t.typical_days, 0);
  const totalLabour = builtTasks.reduce((s, t) => s + t.typical_cost_eur, 0);
  const allMaterials = builtTasks.flatMap((t) => t.materials ?? []);
  const totalMaterialsEur = allMaterials.reduce(
    (s, m) => s + (m.estimated_amount_eur ?? 0),
    0,
  );
  const avgSuccess = builtTasks.length
    ? builtTasks.reduce((s, t) => s + t.assignee.success_p, 0) / builtTasks.length
    : 0;
  const portalMaterials = allMaterials.filter((m) => m.supplier_source === "portal").length;

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
                                {/* Materials sub-row — product lines under each task with
                                    per-material supplier swap + editable amount. */}
                                {(row.materials === null || row.materials.length > 0) && (
                                  <tr className="editor-materials-row">
                                    <td colSpan={6}>
                                      {row.materials === null ? (
                                        <div className="editor-materials-loading">
                                          Predicting materials with Aito…
                                        </div>
                                      ) : (
                                        <div className="editor-materials">
                                          <div className="editor-materials-head">
                                            Materials · predicted product lines & suppliers
                                          </div>
                                          {row.materials.map((m, mi) => {
                                            const swapOpen =
                                              swapForMaterial?.taskId === row.id &&
                                              swapForMaterial?.materialIdx === mi;
                                            return (
                                              <Fragment key={`${row.id}-m-${mi}`}>
                                                <div className="material-row">
                                                  <span className="badge b-gold material-cat">{m.category}</span>
                                                  <span className="material-desc" title="Product line — predicted from history">
                                                    {m.description}
                                                  </span>
                                                  <button
                                                    type="button"
                                                    className="material-supplier-chip"
                                                    onClick={() => handleOpenMaterialSwap(row.id, mi)}
                                                    title="Click to ask Aito for alternative suppliers offering this product line"
                                                  >
                                                    <span className="material-supplier-name">{m.supplier}</span>
                                                    {m.supplier_source === "portal" ? (
                                                      <span className="badge b-purple">via portal</span>
                                                    ) : m.supplier_confidence > 0 && (
                                                      <span className="mono material-supplier-p">{pct(m.supplier_confidence)}</span>
                                                    )}
                                                    <span className="editor-assignee-swap" aria-hidden="true">↻</span>
                                                  </button>
                                                  {m.supplier_source === "history" && m.supplier_why && (
                                                    <WhyPopover
                                                      value={m.supplier}
                                                      confidence={m.supplier_confidence}
                                                      why={m.supplier_why}
                                                    />
                                                  )}
                                                  <input
                                                    type="number"
                                                    className="editor-numeric editor-numeric-wide material-amount"
                                                    value={Math.round(m.estimated_amount_eur ?? 0)}
                                                    min={0}
                                                    step={100}
                                                    onChange={(e) =>
                                                      handleEditMaterialAmount(row.id, mi, Number(e.target.value) || 0)
                                                    }
                                                    title={
                                                      m.amount_confidence > 0
                                                        ? `Aito _predict amount_eur · P ${pct(m.amount_confidence)} · n=${m.coverage}`
                                                        : "Estimated amount"
                                                    }
                                                  />
                                                  <button
                                                    type="button"
                                                    className="editor-row-delete"
                                                    onClick={() => handleDeleteMaterial(row.id, mi)}
                                                    title="Remove this material from the task"
                                                  >
                                                    ×
                                                  </button>
                                                </div>
                                                {swapOpen && (
                                                  <div className="supplier-swap material-swap">
                                                    <div className="supplier-swap-head">
                                                      {loadingSwap
                                                        ? "Asking Aito for supplier candidates…"
                                                        : `Aito's top ${supplierOptions.filter((o) => o.source === "history").length} from history + ${supplierOptions.filter((o) => o.source === "portal").length} from supplier portal — for ${m.description}`}
                                                    </div>
                                                    {supplierOptions.map((opt) => {
                                                      const isCurrent = opt.supplier === m.supplier;
                                                      return (
                                                        <div
                                                          key={`${opt.source}-${opt.supplier}`}
                                                          className={`supplier-swap-row${isCurrent ? " is-current" : ""}${opt.source === "portal" ? " is-portal" : ""}`}
                                                        >
                                                          <button
                                                            type="button"
                                                            className="supplier-swap-pick"
                                                            onClick={() => handleConfirmMaterialSupplier(row.id, mi, opt)}
                                                            disabled={isCurrent}
                                                          >
                                                            <span className="supplier-swap-name">{opt.supplier}</span>
                                                            {opt.source === "portal" ? (
                                                              <span className="badge b-purple">via portal</span>
                                                            ) : (
                                                              <span className="mono supplier-swap-p">{pct(opt.confidence)}</span>
                                                            )}
                                                            {opt.source === "history" && opt.avg_amount_eur != null && (
                                                              <span className="mono supplier-swap-meta">
                                                                ~{fmtAmount(opt.avg_amount_eur)} · n={opt.coverage}
                                                              </span>
                                                            )}
                                                            {opt.source === "portal" && (
                                                              <span className="supplier-swap-meta supplier-swap-portal-meta">
                                                                new entrant — no history yet
                                                              </span>
                                                            )}
                                                          </button>
                                                          {opt.source === "history" && opt.why && (
                                                            <WhyPopover
                                                              value={opt.supplier}
                                                              confidence={opt.confidence}
                                                              why={opt.why}
                                                            />
                                                          )}
                                                        </div>
                                                      );
                                                    })}
                                                    <button
                                                      type="button"
                                                      className="walker-assignee-cancel"
                                                      onClick={() => { setSwapForMaterial(null); setSupplierOptions([]); }}
                                                    >
                                                      Cancel
                                                    </button>
                                                  </div>
                                                )}
                                              </Fragment>
                                            );
                                          })}
                                        </div>
                                      )}
                                    </td>
                                  </tr>
                                )}
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

            {/* Live KPI strip — reads off the editable state so edits update in place. */}
            {builtTasks.length > 0 && (
              <div className="kpi-row" style={{ marginTop: 16 }}>
                <div className="kpi">
                  <div className="kpi-label">Phases</div>
                  <div className="kpi-val">{acceptedPhases.length}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Tasks</div>
                  <div className="kpi-val">{builtTasks.length}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Total days</div>
                  <div className="kpi-val">{totalDays}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Labour cost</div>
                  <div className="kpi-val">{fmtAmount(totalLabour)}</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Materials cost</div>
                  <div className="kpi-val">{fmtAmount(totalMaterialsEur)}</div>
                  <div className="kpi-sub">
                    {allMaterials.length} line{allMaterials.length === 1 ? "" : "s"}
                    {portalMaterials > 0 && ` · ${portalMaterials} via portal`}
                  </div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Avg P(success)</div>
                  <div className="kpi-val" style={{ color: "var(--green)" }}>
                    {pct(avgSuccess)}
                  </div>
                </div>
              </div>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

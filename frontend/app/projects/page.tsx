"use client";

import { useEffect, useMemo, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import WhyPopover from "@/components/prediction/WhyPopover";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { findQuery } from "@/lib/query";
import type {
  AitoPanelConfig,
  PortfolioResponse,
  ProjectRow,
  SuccessFactor,
  WhyExplanation,
} from "@/lib/types";

const DEFAULT_PANEL: AitoPanelConfig = {
  operation: "_predict + _relate",
  endpoints: ["_predict", "_relate"],
  stats: [
    { label: "Table", value: "projects" },
    { label: "Target", value: "success" },
    { label: "Factors", value: "type · priority · drivers" },
  ],
  description:
    "Project portfolio combines two Aito patterns. <em>aito.._predict</em> on " +
    "<em>success</em> forecasts the probability each active project will succeed " +
    "given its manager, project type, team size, budget and duration. " +
    "<em>aito.._relate</em> mines completed-project history for the signals that " +
    "actually move outcomes: <em>project_type</em>, <em>priority</em> and the " +
    "outcome drivers (contract, scope clarity, novelty, customer size, team " +
    "seniority) from <em>projects</em>. Properties of the work, not people: " +
    "a ranked list of colleagues by name is not a finding to put on a screen.",
  // Filled once the portfolio loads: the first success prediction sent.
  queries: [],
  links: [
    { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
    { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
    { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/12-project-portfolio.md", kind: "doc" },
    { label: "Source code", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/project_service.py", kind: "github" },
  ],
};

function pct(p: number | null | undefined): string {
  if (p == null) return "—";
  return `${Math.round(p * 100)}%`;
}

function statusClass(s: string): string {
  if (s === "complete") return "proj-status proj-status-ok";
  if (s === "active") return "proj-status proj-status-info";
  if (s === "at_risk") return "proj-status proj-status-warn";
  if (s === "delayed") return "proj-status proj-status-bad";
  return "proj-status proj-status-info";
}

export default function ProjectsPage() {
  const { tenantId } = useTenant();
  const [data, setData] = useState<PortfolioResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [panel, setPanel] = useState<AitoPanelConfig>(DEFAULT_PANEL);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch<PortfolioResponse>("/api/projects/portfolio")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  useEffect(() => {
    if (!data) return;
    const first = findQuery(data._queries, { endpoint: "_predict", from: "projects", target: "success" });
    setPanel({
      ...DEFAULT_PANEL,
      queries: first ? [first] : [],
      stats: [
        { label: "Projects", value: String(data.kpis.total) },
        { label: "Active", value: String(data.kpis.active) },
        { label: "At risk", value: String(data.kpis.at_risk_count) },
      ],
    });
  }, [data]);

  const active = useMemo(
    () => (data?.projects ?? []).filter((p) => p.status !== "complete"),
    [data],
  );
  const completed = useMemo(
    () => (data?.projects ?? []).filter((p) => p.status === "complete").slice(0, 30),
    [data],
  );

  const handleProjectClick = (p: ProjectRow) => {
    setSelected(p.project_id);
    // The prediction sent for this project, found by its own shape. A
    // completed project was never predicted, so it shows no query.
    const rowQuery = findQuery(data?._queries, {
      endpoint: "_predict", from: "projects", target: "success",
      where: {
        project_type: p.project_type, manager: p.manager, team_size: p.team_size,
        budget_eur: p.budget_eur, duration_days: p.duration_days, priority: p.priority,
      },
    });
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: "P(success)", value: pct(p.success_p) },
        { label: "Team", value: String(p.team_size) },
        { label: "Budget", value: fmtAmount(p.budget_eur) },
      ],
      description:
        `Forecast for <em>${p.name}</em>. Manager: <em>${p.manager}</em>. ` +
        `Lead: <em>${p.team_lead}</em>. Type: <em>${p.project_type}</em>. ` +
        `Open the <em>?</em> on the row for the factor decomposition — which ` +
        `parts of the project context move the prediction up or down.`,
      queries: rowQuery ? [rowQuery] : [],
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const handleFactorClick = (f: SuccessFactor) => {
    const fieldOnly = f.field.split(".").pop() ?? f.field;
    // One _relate per factor field; this row is one of its answers.
    const factorQuery = findQuery(data?._queries, {
      endpoint: "_relate", from: "projects", target: fieldOnly, where: { success: true },
    });
    setPanel({
      operation: "_relate",
      endpoints: ["_relate"],
      stats: [
        { label: f.label, value: f.value },
        { label: "Lift", value: `× ${f.lift.toFixed(2)}` },
        { label: "n", value: String(f.coverage) },
      ],
      description:
        `${f.label}: <em>${f.value}</em>. Among completed projects ` +
        `with this ${f.label.toLowerCase()}, ` +
        `<em>${pct(f.success_rate_with)}</em> succeeded — versus ` +
        `<em>${pct(f.success_rate_without)}</em> across the rest of the ` +
        `portfolio. Lift <em>× ${f.lift.toFixed(2)}</em>. Treat as ` +
        `correlation, not cause: factors confound with project type, ` +
        `priority and seniority.`,
      queries: factorQuery ? [factorQuery] : [],
      links: [
        { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
      ],
    });
  };

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar
          title="Project Portfolio"
          breadcrumb="Operations"
        />
        <div className="content-area">
          <div className="content">
            {error && (
              <ErrorState message={error} command="GET /api/projects/portfolio" />
            )}
            {!error && (loading || !data) && (
              <p style={{ padding: 24, color: "var(--mid)" }}>Loading…</p>
            )}
            {!error && data && (
              <>
                {/* KPI strip */}
                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">Portfolio success rate</div>
                    <div className="kpi-val">{pct(data.kpis.success_rate)}</div>
                    <div className="kpi-sub">{data.kpis.completed} completed</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">On-time rate</div>
                    <div className="kpi-val">{pct(data.kpis.on_time_rate)}</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">On-budget rate</div>
                    <div className="kpi-val">{pct(data.kpis.on_budget_rate)}</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">At risk</div>
                    <div className="kpi-val" style={{ color: "var(--red)" }}>
                      {data.kpis.at_risk_count}
                    </div>
                    <div className="kpi-sub">
                      of {data.kpis.active} active &lt; 55%
                    </div>
                  </div>
                </div>

                <div className="proj-grid">
                  {/* Active projects with success forecast */}
                  <section className="card">
                    <div className="card-head">
                      <span className="card-title">
                        Active projects — predicted success
                      </span>
                      <span className="card-meta">{active.length} active</span>
                    </div>
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>Project</th>
                          <th>Manager</th>
                          <th>Lead</th>
                          <th style={{ textAlign: "right" }}>Budget</th>
                          <th style={{ textAlign: "right" }}>Days</th>
                          <th>Status</th>
                          <th style={{ textAlign: "right" }}>P(success)</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {active.map((p) => {
                          const why = (p.success_why ?? {}) as WhyExplanation;
                          const hasWhy = !!why.lifts;
                          return (
                            <tr
                              key={p.project_id}
                              className={`clickable${selected === p.project_id ? " selected" : ""}`}
                              onClick={() => handleProjectClick(p)}
                            >
                              <td>
                                <div className="proj-name">{p.name}</div>
                                <div className="proj-sub">
                                  {p.project_id} · {p.project_type}
                                </div>
                              </td>
                              <td>{p.manager}</td>
                              <td>{p.team_lead}</td>
                              <td style={{ textAlign: "right" }}>
                                {fmtAmount(p.budget_eur)}
                              </td>
                              <td style={{ textAlign: "right" }}>{p.duration_days}</td>
                              <td>
                                <span className={statusClass(p.status)}>
                                  {p.status}
                                </span>
                              </td>
                              <td style={{ textAlign: "right" }}>
                                <div className={`conf-track ${confClass(p.success_p ?? 0)}`}
                                     style={{ display: "inline-block", verticalAlign: "middle" }}>
                                  <div
                                    className="conf-fill"
                                    style={{ width: `${Math.round((p.success_p ?? 0) * 100)}%` }}
                                  />
                                </div>{" "}
                                <span className="mono" style={{ fontSize: 11 }}>
                                  {pct(p.success_p)}
                                </span>
                              </td>
                              <td onClick={(e) => e.stopPropagation()}>
                                {hasWhy && p.success_p != null && (
                                  <WhyPopover
                                    value="success = true"
                                    confidence={p.success_p}
                                    why={why}
                                    alternatives={p.success_alternatives}
                                  />
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </section>

                  {/* Success factors discovered by _relate */}
                  <aside className="card">
                    <div className="card-head">
                      <span className="card-title">Success factors</span>
                      <span className="card-meta">aito.._relate</span>
                    </div>
                    <div style={{ padding: "10px 14px", fontSize: 11, color: "var(--mid)", lineHeight: 1.5 }}>
                      Properties of the work that move the success rate
                      across completed projects: <code>project_type</code>,{" "}
                      <code>priority</code> and the outcome drivers, from{" "}
                      <code>projects</code>. One <code>_relate</code> per
                      field. No people: this is not a ranking of colleagues.
                    </div>
                    <div className="factors-list">
                      {data.success_factors.length === 0 ? (
                        <div className="factors-empty">
                          Not enough completed-project history yet.
                        </div>
                      ) : (
                        data.success_factors.map((f) => (
                          <button
                            key={`${f.kind}:${f.value}`}
                            type="button"
                            className={`factors-row factors-${f.role_in_pattern}`}
                            onClick={() => handleFactorClick(f)}
                          >
                            <span className={`factors-kind factors-kind-${
                              f.kind === "project_type" || f.kind === "priority" ? f.kind : "driver"}`}>
                              {f.label}
                            </span>
                            <span className="factors-value">{f.value}</span>
                            <span className={`factors-lift factors-${f.role_in_pattern}`}>
                              × {f.lift.toFixed(2)}
                            </span>
                            <span className="factors-meta">
                              {pct(f.success_rate_with)}{" "}
                              <span style={{ color: "var(--mid)" }}>vs</span>{" "}
                              {pct(f.success_rate_without)}{" "}
                              <span style={{ color: "var(--mid)" }}>· n={f.coverage}</span>
                            </span>
                          </button>
                        ))
                      )}
                    </div>
                  </aside>
                </div>

                {/* Completed history (compact) */}
                <section className="card" style={{ marginTop: 16 }}>
                  <div className="card-head">
                    <span className="card-title">Completed projects (last 30)</span>
                    <span className="card-meta">history</span>
                  </div>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Manager</th>
                        <th>Lead</th>
                        <th>Started</th>
                        <th style={{ textAlign: "right" }}>Budget</th>
                        <th>On-time</th>
                        <th>On-budget</th>
                        <th>Outcome</th>
                      </tr>
                    </thead>
                    <tbody>
                      {completed.map((p) => (
                        <tr key={p.project_id}>
                          <td>
                            <div className="proj-name">{p.name}</div>
                            <div className="proj-sub">{p.project_id}</div>
                          </td>
                          <td>{p.manager}</td>
                          <td>{p.team_lead}</td>
                          <td>{p.start_month}</td>
                          <td style={{ textAlign: "right" }}>
                            {fmtAmount(p.budget_eur)}
                          </td>
                          <td>{p.on_time ? "✓" : "✗"}</td>
                          <td>{p.on_budget ? "✓" : "✗"}</td>
                          <td>
                            <span className={`proj-status ${p.success ? "proj-status-ok" : "proj-status-bad"}`}>
                              {p.success ? "success" : "failure"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              </>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

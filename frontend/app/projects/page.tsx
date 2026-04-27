"use client";

import { useEffect, useMemo, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import WhyPopover from "@/components/prediction/WhyPopover";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import type {
  AitoPanelConfig,
  PortfolioResponse,
  ProjectRow,
  StaffingFactor,
  WhyExplanation,
} from "@/lib/types";

const DEFAULT_PANEL: AitoPanelConfig = {
  operation: "_predict + _relate",
  stats: [
    { label: "Tables", value: "projects" },
    { label: "Target", value: "success" },
    { label: "Patterns", value: "team × manager" },
  ],
  description:
    "Project portfolio combines two Aito patterns. <em>aito.._predict</em> on " +
    "<em>success</em> forecasts the probability each active project will succeed " +
    "given its manager, team composition, budget and duration. <em>aito.._relate</em> " +
    "discovers which individual team members have a statistically significant " +
    "effect on outcomes — boost or drag.",
  query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"projects"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"project_type"</span>: <span class="q-v">"implementation"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"manager"</span>: <span class="q-v">"J. Lehtinen"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"team_members"</span>: <span class="q-v">"A. Lindgren K. Saari ..."</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"budget_eur"</span>: <span class="q-n">120000</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"duration_days"</span>: <span class="q-n">90</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"success"</span><br/>
}`,
  links: [
    { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
    { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
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
  const [data, setData] = useState<PortfolioResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [panel, setPanel] = useState<AitoPanelConfig>(DEFAULT_PANEL);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<PortfolioResponse>("/api/projects/portfolio")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!data) return;
    setPanel({
      ...DEFAULT_PANEL,
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
    setPanel({
      operation: "_predict",
      stats: [
        { label: "P(success)", value: pct(p.success_p) },
        { label: "Team", value: String(p.team_size) },
        { label: "Budget", value: fmtAmount(p.budget_eur) },
      ],
      description:
        `Forecast for <em>${p.name}</em>. Manager: <em>${p.manager}</em>. ` +
        `Lead: <em>${p.team_lead}</em>. Type: <em>${p.project_type}</em>. ` +
        `Open the <em>?</em> on the row for the factor decomposition — which ` +
        `parts of the project context move the prediction up or down, ` +
        `including which team members carry weight.`,
      query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"projects"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"project_type"</span>: <span class="q-v">"${p.project_type}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"manager"</span>: <span class="q-v">"${p.manager}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"team_members"</span>: <span class="q-v">"${p.team_members.slice(0, 60)}…"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"budget_eur"</span>: <span class="q-n">${p.budget_eur}</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"duration_days"</span>: <span class="q-n">${p.duration_days}</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"success"</span><br/>
}`,
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const handleStaffingClick = (f: StaffingFactor) => {
    setPanel({
      operation: "_relate",
      stats: [
        { label: "Person", value: f.person },
        { label: "Lift", value: `× ${f.lift.toFixed(2)}` },
        { label: "n", value: String(f.coverage) },
      ],
      description:
        `Among completed projects, those that included <em>${f.person}</em> ` +
        `succeeded <em>${pct(f.success_rate_with)}</em> of the time, ` +
        `versus <em>${pct(f.success_rate_without)}</em> for projects without — ` +
        `a <em>× ${f.lift.toFixed(2)}</em> lift. Treat with care: confounded ` +
        `with project type and seniority.`,
      query: `<span class="q-k">POST</span> /api/v1/_relate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"projects"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"success"</span>: <span class="q-n">true</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"relate"</span>: <span class="q-p">"team_members"</span><br/>
}`,
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

                  {/* Staffing factors discovered by _relate */}
                  <aside className="card">
                    <div className="card-head">
                      <span className="card-title">Staffing factors</span>
                      <span className="card-meta">aito.._relate</span>
                    </div>
                    <div style={{ padding: "10px 14px", fontSize: 11, color: "var(--mid)", lineHeight: 1.5 }}>
                      People whose presence on the team correlates with
                      project success — discovered by Aito's <code>_relate</code>{" "}
                      over completed-project history.
                    </div>
                    <div className="staffing-list">
                      {data.staffing_factors.length === 0 ? (
                        <div className="staffing-empty">
                          Not enough completed-project history yet.
                        </div>
                      ) : (
                        data.staffing_factors.map((f) => (
                          <button
                            key={f.person}
                            type="button"
                            className={`staffing-row staffing-${f.role_in_pattern}`}
                            onClick={() => handleStaffingClick(f)}
                          >
                            <span className="staffing-person">{f.person}</span>
                            <span className={`staffing-lift staffing-${f.role_in_pattern}`}>
                              × {f.lift.toFixed(2)}
                            </span>
                            <span className="staffing-meta">
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

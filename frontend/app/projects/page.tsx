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
  CombinedForecast,
  PortfolioResponse,
  ProjectOutcome,
  ProjectRow,
  SuccessFactor,
  SuccessFactorsResponse,
  WhyExplanation,
} from "@/lib/types";
import { readParam, writeParam } from "@/lib/url-state";

const REVIEW_THRESHOLD = 0.55;

// The KPI the whole view is examined by. "combined" is the expected
// number of the core three that land, over three, from one `_predict`
// on `outcome_score`; the rest are the six outcomes behind it.
const COMBINED = "combined";
const KPIS: { key: string; label: string; what: string }[] = [
  { key: COMBINED, label: "Combined", what: "expected share of the core three that land" },
  { key: "financial_ok", label: "Makes money", what: "the engagement made money" },
  { key: "team_happy", label: "Team stays happy", what: "the team stayed happy" },
  { key: "customer_happy", label: "Customer stays happy", what: "the customer stayed happy" },
  { key: "on_time", label: "Lands when we said", what: "it landed when we said" },
  { key: "outcome_ok", label: "The thing works", what: "the thing worked" },
  { key: "doors_opened", label: "Opens a door", what: "it opened a door" },
];

const DEFAULT_PANEL: AitoPanelConfig = {
  operation: "_predict + _relate",
  endpoints: ["_predict", "_relate"],
  stats: [
    { label: "Table", value: "projects" },
    { label: "Target", value: "outcome_score" },
    { label: "Factors", value: "type · priority · drivers" },
  ],
  description:
    "Project portfolio combines two Aito patterns. <em>aito.._predict</em> " +
    "forecasts each active project on one KPI at a time, chosen above: the six " +
    "outcomes, or <em>outcome_score</em> (how many of the core three land) for " +
    "the combined reading, given its manager, project type, team size, budget, " +
    "duration and outcome drivers. " +
    "<em>aito.._relate</em> mines completed-project history for the signals that " +
    "actually move outcomes: <em>project_type</em>, <em>priority</em> and the " +
    "outcome drivers (contract, scope clarity, novelty, customer size, team " +
    "seniority) from <em>projects</em>. Properties of the work, not people: " +
    "a ranked list of colleagues by name is not a finding to put on a screen.",
  // Filled once the portfolio loads: the first combined prediction sent.
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

function forecastOf(p: ProjectRow, kpi: string): number | null {
  if (kpi === COMBINED) return (p.combined as CombinedForecast).p ?? null;
  return p.outcomes.find((o) => o.field === kpi)?.p ?? null;
}

function riskClass(p: number | null): string {
  if (p == null) return "fc-p fc-p-none";
  if (p >= 0.75) return "fc-p fc-p-high";
  if (p >= 0.5) return "fc-p fc-p-mid";
  return "fc-p fc-p-low";
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
  const [kpi, setKpi] = useState<string>(COMBINED);
  const [factors, setFactors] = useState<SuccessFactorsResponse | null>(null);

  useEffect(() => {
    const wanted = readParam("kpi");
    if (wanted && KPIS.some((k) => k.key === wanted)) setKpi(wanted);
  }, []);

  useEffect(() => {
    writeParam("kpi", kpi === COMBINED ? null : kpi);
    setFactors(null);
    apiFetch<SuccessFactorsResponse>(`/api/projects/success-factors?kpi=${kpi}`)
      .then(setFactors)
      .catch((e) => setError(e.message));
  }, [kpi, tenantId]);

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
    // The riskiest active project is listed first; open it so the six
    // outcomes are on screen without a click.
    const riskiest = data.projects.find((p) => p.status !== "complete");
    if (riskiest) setSelected(riskiest.project_id);
    const first = findQuery(data._queries, { endpoint: "_predict", from: "projects", target: "outcome_score" });
    setPanel({
      ...DEFAULT_PANEL,
      queries: first ? [first] : [],
      stats: [
        { label: "Projects", value: String(data.kpis.total) },
        { label: "Active", value: String(data.kpis.active) },
      ],
    });
  }, [data]);

  // Riskiest first for the KPI being examined, not for the combined one.
  const active = useMemo(
    () => (data?.projects ?? [])
      .filter((p) => p.status !== "complete")
      .sort((a, b) => (forecastOf(a, kpi) ?? 1) - (forecastOf(b, kpi) ?? 1)),
    [data, kpi],
  );
  const kpiMeta = KPIS.find((k) => k.key === kpi) ?? KPIS[0];
  const forecasts = active.map((p) => forecastOf(p, kpi)).filter((v): v is number => v != null);
  const atRisk = forecasts.filter((v) => v < REVIEW_THRESHOLD).length;
  const meanForecast = forecasts.length ? forecasts.reduce((a, b) => a + b, 0) / forecasts.length : null;
  const completed = useMemo(
    () => (data?.projects ?? []).filter((p) => p.status === "complete").slice(0, 30),
    [data],
  );

  // The prediction the backend sent for one outcome of one project, found
  // by the project's own shape. A completed project was never predicted.
  const projectQuery = (p: ProjectRow, target: string) =>
    findQuery(data?._queries, {
      endpoint: "_predict", from: "projects", target,
      where: {
        project_type: p.project_type, manager: p.manager, team_size: p.team_size,
        budget_eur: p.budget_eur, duration_days: p.duration_days, priority: p.priority,
        contract_type: p.contract_type, scope_clarity: p.scope_clarity,
        novelty: p.novelty, customer_size: p.customer_size,
        team_seniority: p.team_seniority,
      },
    });

  const handleProjectClick = (p: ProjectRow) => {
    setSelected(p.project_id);
    const rowQuery = projectQuery(p, kpi === COMBINED ? "outcome_score" : kpi);
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: kpiMeta.label, value: pct(forecastOf(p, kpi)) },
        { label: "Team", value: String(p.team_size) },
        { label: "Budget", value: fmtAmount(p.budget_eur) },
      ],
      description:
        `Forecast for <em>${p.name}</em>. Manager: <em>${p.manager}</em>. ` +
        `Lead: <em>${p.team_lead}</em>. Type: <em>${p.project_type}</em>. ` +
        (kpi === COMBINED
          ? `<em>Combined</em> is one <em>_predict outcome_score</em>: the ` +
            `distribution over how many of money, team and customer land, ` +
            `shown as its expectation over three. `
          : `<em>${kpiMeta.label}</em> is asked on its own, with its own drivers. `) +
        `The card beside the table lists every KPI for this project — click ` +
        `one for its query and open the <em>?</em> for what moved it.`,
      queries: rowQuery ? [rowQuery] : [],
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const handleCombinedClick = (p: ProjectRow) => {
    const c = p.combined as CombinedForecast;
    const query = projectQuery(p, "outcome_score");
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: "Combined", value: pct(c.p) },
        { label: "Expected", value: `${c.expected_score.toFixed(1)} of 3` },
        { label: "Project", value: p.project_id },
      ],
      description:
        `<em>${p.name}</em>: on average <em>${c.expected_score.toFixed(1)}</em> of ` +
        `the core three (money, team, customer) land. One <em>_predict</em> on ` +
        `<em>outcome_score</em> returns the whole distribution, so the ` +
        `correlation between the three is in the answer rather than averaged ` +
        `in afterwards. The <em>?</em> explains the most likely step ` +
        `(<em>${c.top_value}</em>).`,
      queries: query ? [query] : [],
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const handleOutcomeClick = (p: ProjectRow, o: ProjectOutcome) => {
    const query = projectQuery(p, o.field);
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: o.label, value: pct(o.p) },
        { label: "Target", value: o.field },
        { label: "Project", value: p.project_id },
      ],
      description:
        `<em>${o.label}</em> for <em>${p.name}</em>: <em>${pct(o.p)}</em>. ` +
        `The same project context as the success forecast, asking about ` +
        `<em>${o.field}</em> alone — each outcome has its own drivers, ` +
        `which is why they disagree. Open the <em>?</em> to see which ` +
        `fields moved it.`,
      queries: query ? [query] : [],
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const handleFactorClick = (f: SuccessFactor) => {
    const fieldOnly = f.field.split(".").pop() ?? f.field;
    // One _relate per factor field; this row is one of its answers.
    const factorQuery = findQuery(factors?._queries, {
      endpoint: "_relate", from: "projects", target: fieldOnly,
      where: kpi === COMBINED ? { outcome_score: "3" } : { [kpi]: true },
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
        `<em>${pct(f.success_rate_with)}</em> ${kpi === COMBINED ? "landed all three" : `had “${kpiMeta.what}”`} — versus ` +
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
                {/* One KPI at a time: the strip, the table and the factors all follow it */}
                <div className="pill-tabs" role="tablist" aria-label="KPI"
                     style={{ flexWrap: "wrap", marginBottom: 6 }}>
                  {KPIS.map((k) => (
                    <button key={k.key} type="button" role="tab"
                            aria-selected={kpi === k.key}
                            className={`pill-tab${kpi === k.key ? " active" : ""}`}
                            onClick={() => setKpi(k.key)}>
                      {k.label}
                    </button>
                  ))}
                </div>
                <p className="pl-note" style={{ margin: "0 0 14px" }}>
                  Examining: {kpiMeta.what}.
                  {kpi === COMBINED &&
                    " The mean over the core three (money, team, customer), read from one prediction of how many of them land."}
                </p>

                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">{kpiMeta.label} · history</div>
                    <div className="kpi-val">{pct(data.kpis.rates[kpi])}</div>
                    <div className="kpi-sub">{data.kpis.completed} completed</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Predicted · active</div>
                    <div className="kpi-val">{pct(meanForecast)}</div>
                    <div className="kpi-sub">mean over {forecasts.length} projects</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">At risk</div>
                    <div className="kpi-val" style={{ color: "var(--red)" }}>
                      {atRisk}
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
                        Active projects — {kpiMeta.label.toLowerCase()}
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
                          <th style={{ textAlign: "right" }}>P</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {active.map((p) => {
                          const combined = p.combined as CombinedForecast;
                          const outcome = p.outcomes.find((o) => o.field === kpi);
                          const pk = forecastOf(p, kpi);
                          const why = ((kpi === COMBINED ? combined.why : outcome?.why) ?? {}) as WhyExplanation;
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
                                <div className={`conf-track ${confClass(pk ?? 0)}`}
                                     style={{ display: "inline-block", verticalAlign: "middle" }}>
                                  <div
                                    className="conf-fill"
                                    style={{ width: `${Math.round((pk ?? 0) * 100)}%` }}
                                  />
                                </div>{" "}
                                <span className="mono" style={{ fontSize: 11 }}>
                                  {pct(pk)}
                                </span>
                              </td>
                              <td onClick={(e) => e.stopPropagation()}>
                                {hasWhy && pk != null && (
                                  <WhyPopover
                                    value={kpi === COMBINED ? `score = ${combined.top_value}` : kpiMeta.label}
                                    confidence={kpi === COMBINED ? combined.alternatives[0].confidence : pk}
                                    why={why}
                                    alternatives={kpi === COMBINED ? combined.alternatives : outcome?.alternatives ?? []}
                                  />
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </section>

                  {/* Right column: the selected project's six outcomes, then the portfolio-wide factors */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                  <section className="card">
                    {(() => {
                      const sel = active.find((p) => p.project_id === selected);
                      if (!sel || sel.outcomes.length === 0) {
                        return (
                          <p className="pl-note">
                            Click a project to see its six outcomes, each
                            predicted on its own.
                          </p>
                        );
                      }
                      return (
                        <div>
                          <div className="card-head" style={{ marginTop: 8 }}>
                            <span className="card-title">
                              Six outcomes — {sel.name}
                            </span>
                            <span className="card-meta">projects._predict ×6</span>
                          </div>
                          <table className="tbl">
                            <tbody>
                              <tr
                                className={`clickable${kpi === COMBINED ? " selected" : ""}`}
                                onClick={() => handleCombinedClick(sel)}
                              >
                                <td>
                                  <strong>Combined</strong>
                                  <div className="proj-sub">
                                    {(sel.combined as CombinedForecast).expected_score.toFixed(1)} of the core three, expected
                                  </div>
                                </td>
                                <td style={{ textAlign: "right", width: "22%" }}>
                                  <span className={riskClass((sel.combined as CombinedForecast).p)}>
                                    {pct((sel.combined as CombinedForecast).p)}
                                  </span>
                                </td>
                                <td style={{ width: 30 }} />
                              </tr>
                            </tbody>
                          </table>
                          {([
                            ["core", "Was it worth doing"],
                            ["qualifying", "And did it hold up"],
                          ] as const).map(([group, head]) => (
                            <div key={group}>
                              <div className="pl-group">{head}</div>
                              <table className="tbl">
                                <tbody>
                                  {sel.outcomes.filter((o) => o.group === group).map((o) => (
                                    <tr
                                      key={o.field}
                                      className={`clickable${kpi === o.field ? " selected" : ""}`}
                                      onClick={() => handleOutcomeClick(sel, o)}
                                    >
                                      <td>{o.label}</td>
                                      <td style={{ textAlign: "right", width: "22%" }}>
                                        <span className={riskClass(o.p)}>{pct(o.p)}</span>
                                      </td>
                                      <td style={{ width: 30 }} onClick={(e) => e.stopPropagation()}>
                                        {(o.why as WhyExplanation)?.lifts && o.p != null && (
                                          <WhyPopover
                                            value={o.label}
                                            confidence={o.p}
                                            why={o.why as WhyExplanation}
                                            alternatives={o.alternatives}
                                          />
                                        )}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ))}
                        </div>
                      );
                    })()}
                  </section>
                  <aside className="card">
                    <div className="card-head">
                      <span className="card-title">Success factors</span>
                      <span className="card-meta">aito.._relate</span>
                    </div>
                    <div style={{ padding: "10px 14px", fontSize: 11, color: "var(--mid)", lineHeight: 1.5 }}>
                      Properties of the work that move the rate of{" "}
                      <strong>{kpiMeta.label.toLowerCase()}</strong>{" "}
                      across completed projects: <code>project_type</code>,{" "}
                      <code>priority</code> and the outcome drivers, from{" "}
                      <code>projects</code>. One <code>_relate</code> per
                      field. No people: this is not a ranking of colleagues.
                    </div>
                    <div className="factors-list">
                      {factors === null ? (
                        <div className="factors-empty">Loading…</div>
                      ) : factors.success_factors.length === 0 ? (
                        <div className="factors-empty">
                          Not enough completed-project history yet.
                        </div>
                      ) : (
                        factors.success_factors.map((f) => (
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
                              {p.outcome_score} of 3
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

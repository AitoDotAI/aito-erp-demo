"use client";

import { useEffect, useMemo, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch } from "@/lib/api";
import type {
  AitoPanelConfig,
  UtilizationOverview,
  UtilizationRow,
  CapacityForecast,
} from "@/lib/types";

const DEFAULT_PANEL: AitoPanelConfig = {
  operation: "_search + _predict",
  stats: [
    { label: "Tables", value: "assignments + projects" },
    { label: "Target", value: "role / allocation_pct" },
    { label: "Latency", value: "30-80ms" },
  ],
  description:
    "Utilisation rolls up active <em>assignments × allocation_pct</em> per " +
    "person; the at-risk column also weighs in project status. The " +
    "&ldquo;What if&rdquo; forecast is a plain <em>aito.._predict</em> " +
    "on the assignments table — <em>project_type</em> is denormalised " +
    "onto each assignment row at load time, so the query is a single " +
    "table away from the answer: which role + allocation does this " +
    "person take on engagements of that kind. No timesheet integration, " +
    "no rules: predictions come straight from the historical assignment " +
    "table.",
  query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"assignments"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"person"</span>: <span class="q-v">"A. Lindgren"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"project_type"</span>: <span class="q-v">"design"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"allocation_pct"</span><br/>
}`,
  links: [
    { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
  ],
};

function statusClass(s: string): string {
  return `util-status util-status-${s}`;
}

function loadBarColor(pct: number): string {
  if (pct > 110) return "var(--red)";
  if (pct < 60) return "var(--blue)";
  return "var(--green)";
}

export default function UtilizationPage() {
  const [data, setData] = useState<UtilizationOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<UtilizationRow | null>(null);
  const [forecastType, setForecastType] = useState<string>("");
  const [forecast, setForecast] = useState<CapacityForecast | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [panel, setPanel] = useState<AitoPanelConfig>(DEFAULT_PANEL);

  useEffect(() => {
    apiFetch<UtilizationOverview>("/api/utilization/overview")
      .then((d) => {
        setData(d);
        if (d.project_types.length) setForecastType(d.project_types[0]);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Refresh forecast whenever the selected person OR project_type changes.
  useEffect(() => {
    if (!selected || !forecastType) {
      setForecast(null);
      return;
    }
    setForecastLoading(true);
    apiFetch<CapacityForecast>("/api/utilization/forecast", {
      method: "POST",
      body: JSON.stringify({
        person: selected.person,
        project_type: forecastType,
      }),
    })
      .then(setForecast)
      .catch((e) => setError(e.message))
      .finally(() => setForecastLoading(false));
  }, [selected, forecastType]);

  // Update the right-rail Aito panel when a person is selected.
  useEffect(() => {
    if (!selected) {
      setPanel(DEFAULT_PANEL);
      return;
    }
    setPanel({
      operation: "_predict",
      stats: [
        { label: "Person", value: selected.person },
        { label: "Current load", value: `${selected.current_allocation_pct}%` },
        { label: "At risk", value: `${selected.at_risk_pct}%` },
      ],
      description:
        `Capacity profile for <em>${selected.person}</em> (typical role: ` +
        `<em>${selected.primary_role}</em>). Active load <em>${selected.current_allocation_pct}%</em> ` +
        `across ${selected.active_projects} projects; ${selected.at_risk_pct}% of that ` +
        `is on at-risk or delayed engagements. Historical norm across ` +
        `${selected.completed_projects} completed projects: <em>${selected.historical_avg_pct}%</em>. ` +
        `Pick a project type below to see the role + allocation Aito predicts ` +
        `for them on a typical engagement of that kind.`,
      query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"assignments"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"person"</span>: <span class="q-v">"${selected.person}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"project_type"</span>: <span class="q-v">"${forecastType || "..."}"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"role"</span> | <span class="q-p">"allocation_pct"</span><br/>
}`,
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  }, [selected, forecastType]);

  const overloaded = useMemo(() =>
    (data?.rows ?? []).filter((r) => r.status === "overloaded"), [data]);
  const available = useMemo(() =>
    (data?.rows ?? []).filter((r) => r.status === "available"), [data]);

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar
          title="Utilization & Capacity"
          breadcrumb="Operations"
        />
        <div className="content-area">
          <div className="content">
            {error && (
              <ErrorState message={error} command="GET /api/utilization/overview" />
            )}
            {!error && (loading || !data) && (
              <p style={{ padding: 24, color: "var(--mid)" }}>Loading…</p>
            )}
            {!error && data && (
              <>
                {/* Summary KPIs */}
                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">Avg utilisation</div>
                    <div className="kpi-val">
                      {Math.round(data.summary.avg_utilization)}%
                    </div>
                    <div className="kpi-sub">{data.summary.total_people} people</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Overloaded</div>
                    <div className="kpi-val" style={{ color: "var(--red)" }}>
                      {data.summary.overloaded_count}
                    </div>
                    <div className="kpi-sub">&gt; 110% loaded</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Available capacity</div>
                    <div className="kpi-val" style={{ color: "var(--blue)" }}>
                      {data.summary.available_count}
                    </div>
                    <div className="kpi-sub">&lt; 60% loaded</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Loaded on at-risk work</div>
                    <div className="kpi-val" style={{ color: "var(--gold-dark)" }}>
                      {data.summary.at_risk_count}
                    </div>
                    <div className="kpi-sub">&gt; 25% on slipping projects</div>
                  </div>
                </div>

                {/* Honest framing */}
                <div style={{
                  padding: "12px 16px",
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  borderLeft: "3px solid var(--gold)",
                  borderRadius: 5,
                  marginBottom: 16,
                  fontSize: 12,
                  lineHeight: 1.55,
                  color: "var(--mid)",
                }}>
                  <strong style={{ color: "var(--ink)" }}>How to read this:</strong>{" "}
                  <strong style={{ color: "var(--blue)" }}>{available.length}</strong> consultants are below 60% — sales has capacity to sell into this week.{" "}
                  <strong style={{ color: "var(--red)" }}>{overloaded.length}</strong> are above 110% — they should not take new work.
                  Click any person to see their assignment history and project Aito's predicted role + allocation on hypothetical new engagements.
                </div>

                <div className="util-grid">
                  {/* Utilization table */}
                  <section className="card">
                    <div className="card-head">
                      <span className="card-title">Consultant load</span>
                      <span className="card-meta">sorted by current allocation</span>
                    </div>
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>Person</th>
                          <th>Role</th>
                          <th>Status</th>
                          <th style={{ textAlign: "right" }}>Active</th>
                          <th style={{ textAlign: "right" }}>Load</th>
                          <th style={{ textAlign: "right" }}>At risk</th>
                          <th style={{ textAlign: "right" }}>Hist.</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.rows.map((r) => (
                          <tr
                            key={r.person}
                            className={`clickable${selected?.person === r.person ? " selected" : ""}`}
                            onClick={() => setSelected(r)}
                          >
                            <td>
                              <div className="proj-name">{r.person}</div>
                            </td>
                            <td style={{ fontSize: 11, color: "var(--mid)" }}>
                              {r.primary_role}
                            </td>
                            <td>
                              <span className={statusClass(r.status)}>{r.status}</span>
                            </td>
                            <td style={{ textAlign: "right" }} className="mono">
                              {r.active_projects}
                            </td>
                            <td style={{ textAlign: "right" }}>
                              <div className="util-bar">
                                <div
                                  className="util-bar-fill"
                                  style={{
                                    width: `${Math.min(r.current_allocation_pct, 150) / 1.5}%`,
                                    background: loadBarColor(r.current_allocation_pct),
                                  }}
                                />
                              </div>
                              <span className="mono" style={{ fontSize: 11 }}>
                                {r.current_allocation_pct}%
                              </span>
                            </td>
                            <td
                              className="mono"
                              style={{ textAlign: "right",
                                       color: r.at_risk_pct > 25 ? "var(--gold-dark)" : "var(--mid)" }}
                            >
                              {r.at_risk_pct > 0 ? `${r.at_risk_pct}%` : "—"}
                            </td>
                            <td
                              className="mono"
                              style={{ textAlign: "right", color: "var(--mid)", fontSize: 11 }}
                            >
                              {r.historical_avg_pct}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>

                  {/* What-if forecast panel */}
                  <aside className="card util-forecast-card">
                    <div className="card-head">
                      <span className="card-title">"What if" forecast</span>
                      <span className="card-meta">aito.._predict</span>
                    </div>
                    {!selected ? (
                      <div style={{ padding: 16, fontSize: 12, color: "var(--mid)", lineHeight: 1.6 }}>
                        Click a consultant on the left to predict the role and
                        allocation Aito expects them to take on a typical
                        engagement.
                      </div>
                    ) : (
                      <div style={{ padding: "14px 16px" }}>
                        <div style={{ marginBottom: 12 }}>
                          <div style={{ fontSize: 9.5, fontWeight: 600,
                                        letterSpacing: "0.1em", textTransform: "uppercase",
                                        color: "var(--mid)" }}>
                            Selected
                          </div>
                          <div style={{ fontFamily: "'DM Serif Display', serif",
                                        fontSize: 20, color: "var(--ink)", marginTop: 2 }}>
                            {selected.person}
                          </div>
                          <div style={{ fontSize: 11, color: "var(--mid)" }}>
                            current {selected.current_allocation_pct}% ·{" "}
                            {selected.active_projects} active ·{" "}
                            {selected.completed_projects} completed
                          </div>
                        </div>

                        <label className="form-label" style={{ display: "block", marginBottom: 4 }}>
                          On a typical project of type:
                        </label>
                        <select
                          className="form-input"
                          value={forecastType}
                          onChange={(e) => setForecastType(e.target.value)}
                          style={{ marginBottom: 14 }}
                        >
                          {data.project_types.map((t) => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>

                        {forecastLoading ? (
                          <div style={{ fontSize: 11, color: "var(--mid)" }}>Predicting…</div>
                        ) : forecast ? (
                          forecast.historical_count === 0 ? (
                            <div style={{ padding: 10,
                                          background: "var(--red-light)",
                                          color: "var(--red)",
                                          fontSize: 11, borderRadius: 4, lineHeight: 1.5 }}>
                              No prior assignments of this type — Aito has no
                              history to learn from. Predictions below would be
                              based on the population baseline alone.
                            </div>
                          ) : (
                            <>
                              <div className="util-forecast-block">
                                <div className="util-forecast-label">Predicted role</div>
                                <div className="util-forecast-value">
                                  {forecast.predicted_role ?? "—"}
                                </div>
                                <div className="util-forecast-sub">
                                  {Math.round(forecast.role_confidence * 100)}% confidence
                                </div>
                                {forecast.role_alternatives.length > 1 && (
                                  <div className="util-forecast-alts">
                                    {forecast.role_alternatives.slice(0, 4).map((a, i) => (
                                      <span key={i} className="util-alt-chip">
                                        {a.value} <span className="mono">{Math.round(a.confidence * 100)}%</span>
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>

                              <div className="util-forecast-block">
                                <div className="util-forecast-label">Predicted allocation</div>
                                <div className="util-forecast-value">
                                  {forecast.predicted_allocation != null
                                    ? `${forecast.predicted_allocation}%`
                                    : "—"}
                                </div>
                                <div className="util-forecast-sub">
                                  {Math.round(forecast.allocation_confidence * 100)}% confidence
                                </div>
                              </div>

                              <div style={{ fontSize: 10.5, color: "var(--mid)", marginTop: 10 }}>
                                Based on {forecast.historical_count} past assignment{forecast.historical_count === 1 ? "" : "s"} of this type.
                              </div>
                            </>
                          )
                        ) : null}
                      </div>
                    )}
                  </aside>
                </div>
              </>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

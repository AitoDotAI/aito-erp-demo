"use client";

import { useState, useEffect } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import type { OverviewMetrics, AitoPanelConfig } from "@/lib/types";

const defaultPanel: AitoPanelConfig = {
  operation: "automation overview",
  stats: [
    { label: "Rules", value: "—" },
    { label: "aito..", value: "—" },
    { label: "Manual", value: "—" },
  ],
  description:
    "The automation gap: rules handle <em>known patterns</em>, but the remaining percentage requires either manual work or machine learning.<br/><br/>aito.. closes this gap with <em>zero training required</em>. Upload your data, ask a question, get a prediction. The system learns from every correction, continuously improving without retraining pipelines.<br/><br/>Unlike traditional ML, aito.. needs <em>no feature engineering, no model selection, no deployment</em> &mdash; predictions come directly from the database.",
  query: `<span class="q-d">// No model training needed.</span>\n<span class="q-d">// aito.. learns directly from data.</span>\n\n<span class="q-k">POST</span> <span class="q-v">/api/v1/_predict</span>\n<span class="q-d">// \u2192 Predicts categorical values</span>\n\n<span class="q-k">POST</span> <span class="q-v">/api/v1/_estimate</span>\n<span class="q-d">// \u2192 Estimates numerical values</span>\n\n<span class="q-k">POST</span> <span class="q-v">/api/v1/_relate</span>\n<span class="q-d">// \u2192 Discovers relationships</span>\n\n<span class="q-k">POST</span> <span class="q-v">/api/v1/_match</span>\n<span class="q-d">// \u2192 Finds similar records</span>`,
  links: [
    { label: "aito.ai/docs/overview", url: "https://aito.ai/docs" },
    { label: "aito.ai/docs/api", url: "https://aito.ai/docs/api" },
  ],
};

export default function OverviewPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<OverviewMetrics | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);

  useEffect(() => {
    apiFetch<OverviewMetrics>("/api/overview/metrics")
      .then((data) => {
        setMetrics(data);
        setPanel({
          ...defaultPanel,
          stats: [
            { label: "Rules", value: `${Math.round(data.automation.rules_pct)}%` },
            { label: "aito..", value: `${Math.round(data.automation.aito_high_pct)}%` },
            { label: "Manual", value: `${Math.round(data.automation.manual_pct)}%` },
          ],
        });
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) {
    return (
      <>
        <Nav />
        <div className="main">
          <TopBar title="Automation Overview" breadcrumb="Overview" />
          <div className="content-area">
            <div className="content">
              <ErrorState message={error} command="GET /api/overview/metrics" />
            </div>
            <AitoPanel config={defaultPanel} />
          </div>
        </div>
      </>
    );
  }

  if (!metrics) {
    return (
      <>
        <Nav />
        <div className="main">
          <TopBar title="Automation Overview" breadcrumb="Overview" />
          <div className="content-area">
            <div className="content">
              <p style={{ padding: 24, color: "var(--mid)" }}>Loading...</p>
            </div>
            <AitoPanel config={defaultPanel} />
          </div>
        </div>
      </>
    );
  }

  const auto = metrics.automation;
  const summary = metrics.summary;

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar title="Automation Overview" breadcrumb="Overview" />
        <div className="content-area">
          <div className="content">
            {/* Savings Strip — money first, then automation metrics */}
            <div className="savings-strip">
              <div className="savings-card" style={{ background: "var(--gold-light)", borderColor: "var(--gold)" }}>
                <div className="savings-icon">{"\uD83D\uDCB0"}</div>
                <div>
                  <div className="savings-val" style={{ color: "var(--gold-dark)" }}>
                    {summary.total_savings_eur != null
                      ? "\u20AC" + Math.round(summary.total_savings_eur).toLocaleString("fi-FI")
                      : "\u2014"}
                  </div>
                  <div className="savings-label" style={{ color: "var(--gold-dark)" }}>
                    estimated savings YTD
                    {summary.hours_saved != null && (
                      <span style={{ display: "block", fontSize: 10, color: "var(--mid)", marginTop: 2 }}>
                        {summary.hours_saved}h labor + miscoding prevented
                      </span>
                    )}
                    <details style={{ marginTop: 4, fontSize: 10, color: "var(--mid)" }}>
                      <summary style={{ cursor: "pointer", color: "var(--mid)" }}>methodology</summary>
                      <div style={{ marginTop: 4, lineHeight: 1.5 }}>
                        <strong>Labor</strong>: {summary.total_automated} POs × 5 min × €0.80/min ={" "}
                        €{summary.labor_savings_eur != null ? Math.round(summary.labor_savings_eur).toLocaleString("fi-FI") : "—"}
                        <br/>
                        <strong>Mis-coding</strong>: {summary.total_automated} × {Math.round(summary.avg_prediction_confidence * 100)}% accuracy ×{" "}
                        €120 cleanup cost ={" "}
                        €{summary.miscode_savings_eur != null ? Math.round(summary.miscode_savings_eur).toLocaleString("fi-FI") : "—"}
                        <br/>
                        <em>Constants are conservative SMB benchmarks. Adjust in
                        <code> overview_service.py</code> for your org&apos;s loaded cost.</em>
                      </div>
                    </details>
                  </div>
                </div>
              </div>
              <div className="savings-card">
                <div className="savings-icon">{"\u23F1\uFE0F"}</div>
                <div>
                  <div className="savings-val">{Math.round(summary.automation_rate)}%</div>
                  <div className="savings-label">Automation rate</div>
                </div>
              </div>
              <div className="savings-card">
                <div className="savings-icon">{"\uD83C\uDFAF"}</div>
                <div>
                  <div className="savings-val">{Math.round(summary.avg_prediction_confidence * 100)}%</div>
                  <div className="savings-label">Avg prediction confidence</div>
                </div>
              </div>
              <div className="savings-card">
                <div className="savings-icon">{"\uD83D\uDCC8"}</div>
                <div>
                  <div className="savings-val">{summary.total_automated}</div>
                  <div className="savings-label">POs automated</div>
                </div>
              </div>
            </div>

            {/* P3 honest framing: tell the story behind the numbers */}
            <div style={{
              padding: "12px 16px",
              background: "var(--card)",
              border: "1px solid var(--border)",
              borderLeft: "3px solid var(--gold)",
              borderRadius: 5,
              marginBottom: 14,
              fontSize: 12,
              lineHeight: 1.55,
              color: "var(--mid)",
            }}>
              <strong style={{ color: "var(--ink)" }}>How to read this:</strong>{" "}
              <strong style={{ color: "var(--gold-dark)" }}>{Math.round(auto.rules_pct + auto.aito_high_pct)}%</strong> of POs ship without anyone touching them
              ({Math.round(auto.rules_pct)}% via deterministic rules, {Math.round(auto.aito_high_pct)}% via aito.. high-confidence predictions).
              The remaining <strong style={{ color: "var(--mid)" }}>{Math.round(auto.aito_reviewed_pct + auto.manual_pct)}%</strong> goes to a human —
              not because aito.. failed, but because <em>those are the cases worth a second look</em>: new vendors,
              ambiguous descriptions, amounts that break the supplier&apos;s pattern. The system is honest about its
              uncertainty so you can focus review effort where it matters.
            </div>

            {/* Automation Coverage */}
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="card-head">
                <span className="card-title">Automation Coverage</span>
                <span className="card-meta">{Math.round(auto.rules_pct + auto.aito_high_pct + auto.aito_reviewed_pct)}% automated &middot; {Math.round(auto.manual_pct)}% manual</span>
              </div>
              <div className="auto-bar-wrap" style={{ paddingTop: 16 }}>
                <div className="auto-bar" style={{ height: 10, borderRadius: 5 }}>
                  <div className="auto-rules" style={{ width: `${auto.rules_pct}%` }} />
                  <div className="auto-aito" style={{ width: `${auto.aito_high_pct}%` }} />
                  <div className="auto-review" style={{ width: `${auto.aito_reviewed_pct}%` }} />
                  <div className="auto-manual" style={{ width: `${auto.manual_pct}%` }} />
                </div>
                <div className="auto-legend">
                  <div className="auto-legend-item">
                    <span className="auto-legend-dot" style={{ background: "var(--green)" }} />
                    Rules ({Math.round(auto.rules_pct)}%)
                  </div>
                  <div className="auto-legend-item">
                    <span className="auto-legend-dot" style={{ background: "var(--gold)" }} />
                    aito.. high-conf ({Math.round(auto.aito_high_pct)}%)
                  </div>
                  <div className="auto-legend-item">
                    <span className="auto-legend-dot" style={{ background: "#e8c060" }} />
                    aito.. reviewed ({Math.round(auto.aito_reviewed_pct)}%)
                  </div>
                  <div className="auto-legend-item">
                    <span className="auto-legend-dot" style={{ background: "#d0ccc0" }} />
                    Manual ({Math.round(auto.manual_pct)}%)
                  </div>
                </div>
              </div>
            </div>

            {/* Two-column grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              {/* Prediction Quality by Field */}
              <div className="card">
                <div className="card-head">
                  <span className="card-title">Prediction Quality by Field</span>
                </div>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Accuracy</th>
                      <th>Avg Confidence</th>
                      <th>Samples</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.prediction_quality.map((pq) => (
                      <tr key={pq.field_name} className="clickable">
                        <td style={{ fontWeight: 500 }}>{pq.field_name}</td>
                        <td>
                          <div className={`conf ${confClass(pq.accuracy)}`}>
                            <div className="conf-track">
                              <div className="conf-fill" style={{ width: `${pq.accuracy * 100}%` }} />
                            </div>
                            <span className="conf-val">{Math.round(pq.accuracy * 100)}%</span>
                          </div>
                        </td>
                        <td className="mono" style={{ fontSize: 11 }}>
                          {Math.round(pq.avg_confidence * 100)}%
                        </td>
                        <td className="mono" style={{ fontSize: 11 }}>
                          {pq.sample_size}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Learning Curve */}
              <div className="card">
                <div className="card-head">
                  <span className="card-title">Learning Curve</span>
                  <span className="card-meta">month-by-month from data</span>
                </div>
                <div style={{ padding: 14 }}>
                  {metrics.learning_curve.map((lc, i) => {
                    const label = (lc as { month?: string }).month ?? `Week ${lc.week}`;
                    const total = (lc as { total?: number }).total;
                    const isLatest = i === metrics.learning_curve.length - 1;
                    return (
                      <div key={i} style={{ marginBottom: 8 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 }}>
                          <span className="mono" style={{ fontSize: 11, color: "var(--mid)" }}>
                            {label}
                            {total != null && <span style={{ color: "#bbb" }}> · {total} POs</span>}
                          </span>
                          <span className="mono" style={{ fontSize: 11, fontWeight: 600, color: isLatest ? "var(--gold-dark)" : "var(--mid)" }}>
                            {Math.round(lc.automation_pct)}%
                          </span>
                        </div>
                        <div style={{ height: 5, borderRadius: 3, background: "#f0ede6" }}>
                          <div
                            style={{
                              height: 5,
                              borderRadius: 3,
                              background: isLatest ? "var(--gold-dark)" : "var(--gold)",
                              width: `${lc.automation_pct}%`,
                              transition: "width 0.3s ease",
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                  <div style={{ fontSize: 11, color: "var(--mid)", marginTop: 8, padding: "8px 0", borderTop: "1px solid #f0ede6", lineHeight: 1.5 }}>
                    Each row is one month of <code>routed_by</code> data from the <code>purchases</code> table — computed live, not hardcoded.
                  </div>
                </div>
              </div>
            </div>
          </div>

          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

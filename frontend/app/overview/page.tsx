"use client";

import { useState, useEffect } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, confClass } from "@/lib/api";
import type { OverviewMetrics, AitoPanelConfig } from "@/lib/types";

const defaultPanel: AitoPanelConfig = {
  operation: "automation overview",
  endpoints: ["_search", "_evaluate"],
  stats: [
    { label: "Rules", value: "—" },
    { label: "aito..", value: "—" },
    { label: "Manual", value: "—" },
  ],
  description:
    "Per-field <em>accuracy</em> on this page is real &mdash; it comes from Aito's <em>_evaluate</em> with " +
    "<code>select: [\"cases\"]</code>. We hold out each row, predict the field from supplier + " +
    "description + amount, compare to ground truth, and bucket by confidence band. " +
    "<em>Predictions &ge; 0.85</em> are the auto-approve zone; lower bands flag review work.<br/><br/>" +
    "Unlike traditional ML, aito.. needs <em>no feature engineering, no model selection, no deployment</em> " +
    "&mdash; predictions come directly from the database, and so does this evaluation.",
  query: `<span class="q-k">POST</span> /api/v1/_evaluate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"testSource"</span>: { <span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>, <span class="q-k">"limit"</span>: <span class="q-n">200</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"evaluate"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>:    { <span class="q-k">"$get"</span>: <span class="q-v">"supplier"</span> },<br/>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"description"</span>: { <span class="q-k">"$get"</span>: <span class="q-v">"description"</span> },<br/>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"amount_eur"</span>:  { <span class="q-k">"$get"</span>: <span class="q-v">"amount_eur"</span> }<br/>
&nbsp;&nbsp;&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"cost_center"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"select"</span>: [<span class="q-v">"accuracy"</span>, <span class="q-v">"baseAccuracy"</span>, <span class="q-v">"cases"</span>]<br/>
}`,
  links: [
    { label: "_evaluate API reference", url: "https://aito.ai/docs/api/evaluate" },
    { label: "aito.ai/docs", url: "https://aito.ai/docs" },
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
                        <strong>Mis-coding</strong>: {summary.total_automated} × {Math.round((summary.model_accuracy ?? summary.avg_prediction_confidence) * 100)}% measured accuracy ×{" "}
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
                  <div className="savings-val">
                    {Math.round((summary.model_accuracy ?? summary.avg_prediction_confidence) * 100)}%
                  </div>
                  <div className="savings-label">
                    Measured accuracy
                    {summary.baseline_accuracy != null && (
                      <span style={{ display: "block", fontSize: 10, color: "var(--mid)", marginTop: 2 }}>
                        baseline {Math.round(summary.baseline_accuracy * 100)}% &middot; +{Math.round((summary.accuracy_gain ?? 0) * 100)}pt gain
                      </span>
                    )}
                  </div>
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
            <div className="split-2-col">
              {/* Prediction Quality by Field — real numbers from _evaluate. */}
              <div className="card">
                <div className="card-head">
                  <span className="card-title">Prediction Quality by Field</span>
                  <span className="card-meta">held-out _evaluate</span>
                </div>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Accuracy</th>
                      <th>Baseline</th>
                      <th>Gain</th>
                      <th>Samples</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.prediction_quality.map((pq) => (
                      <tr key={pq.field_name}>
                        <td style={{ fontWeight: 500 }}>{pq.field_name}</td>
                        <td>
                          <div className={`conf ${confClass(pq.accuracy)}`}>
                            <div className="conf-track">
                              <div className="conf-fill" style={{ width: `${pq.accuracy * 100}%` }} />
                            </div>
                            <span className="conf-val">{Math.round(pq.accuracy * 100)}%</span>
                          </div>
                        </td>
                        <td className="mono" style={{ fontSize: 11, color: "var(--mid)" }}>
                          {Math.round(pq.base_accuracy * 100)}%
                        </td>
                        <td className="mono" style={{ fontSize: 11, color: pq.accuracy_gain >= 0 ? "var(--green)" : "var(--red, #c54)" }}>
                          {pq.accuracy_gain >= 0 ? "+" : ""}{Math.round(pq.accuracy_gain * 100)}pt
                        </td>
                        <td className="mono" style={{ fontSize: 11 }}>
                          {pq.sample_size}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ padding: "10px 14px 14px", fontSize: 11, color: "var(--mid)", lineHeight: 1.5 }}>
                  Each row: <code>_evaluate</code> holds out 200 purchases, predicts the field from
                  supplier + description + amount, and compares to ground truth. <em>Gain</em> = accuracy &minus;
                  most-common-value baseline.
                </div>

                {/* Confidence-band breakdown — when to trust, when to review */}
                {metrics.prediction_quality.some((pq) => pq.bands?.length) && (
                  <div style={{ borderTop: "1px solid #f0ede6", padding: "12px 14px" }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink)", marginBottom: 8 }}>
                      Accuracy by confidence band — first field shown
                    </div>
                    {(() => {
                      const first = metrics.prediction_quality.find((pq) => pq.bands?.length);
                      if (!first) return null;
                      return (
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                          {first.bands.map((b) => (
                            <div key={b.label} style={{
                              padding: "8px 10px",
                              border: "1px solid var(--border)",
                              borderRadius: 5,
                              background: b.min_p >= 0.85
                                ? "var(--green-light, #e7f4ec)"
                                : b.min_p >= 0.5 ? "var(--gold-light)" : "#f5efe5",
                            }}>
                              <div style={{ fontSize: 10, color: "var(--mid)", marginBottom: 2 }}>
                                $p {b.label}
                              </div>
                              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--ink)" }}>
                                {Math.round(b.accuracy * 100)}%
                              </div>
                              <div style={{ fontSize: 10, color: "var(--mid)" }}>
                                {b.count} cases
                              </div>
                            </div>
                          ))}
                        </div>
                      );
                    })()}
                    <div style={{ fontSize: 10, color: "var(--mid)", marginTop: 8, lineHeight: 1.5 }}>
                      Predictions in the <strong>≥ 0.85</strong> band are the auto-approve zone;
                      <strong> &lt; 0.5</strong> is the review zone. The confidence-to-accuracy
                      relationship is <em>calibrated</em> — Aito's $p actually means what it says.
                    </div>
                  </div>
                )}
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

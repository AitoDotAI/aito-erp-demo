"use client";

import { useEffect, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { anomaliesPanel } from "@/lib/panel-content";
import type { AnomalyResponse, AnomalyFlag, AitoPanelConfig } from "@/lib/types";

function ringClass(score: number): string {
  if (score >= 85) return "a-high";
  if (score >= 60) return "a-mid";
  return "a-low";
}

export default function AnomaliesPage() {
  const { tenantId } = useTenant();
  const [data, setData] = useState<AnomalyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(() => anomaliesPanel(tenantId));


  useEffect(() => {
    apiFetch<AnomalyResponse>("/api/anomalies/scan")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Re-tone whenever data loads OR the tenant changes — persona
  // description swaps to the new industry, live stats stay intact.
  useEffect(() => {
    const base = anomaliesPanel(tenantId);
    if (!data) {
      setPanel(base);
      return;
    }
    const flags = data.anomalies;
    const high = flags.filter((f) => f.severity === "high").length;
    const avgScore = flags.length > 0
      ? Math.round(flags.reduce((acc, f) => acc + f.anomaly_score, 0) / flags.length)
      : 0;
    setPanel({
      ...base,
      stats: [
        { label: "Flagged", value: String(flags.length) },
        { label: "High severity", value: String(high) },
        { label: "Avg score", value: String(avgScore) },
      ],
    });
  }, [data, tenantId]);

  const [decisions, setDecisions] = useState<Record<string, "investigate" | "approve" | "escalate" | "legitimate">>({});

  const handleAction = (id: string, action: "investigate" | "approve" | "escalate" | "legitimate") => {
    setDecisions((prev) => ({ ...prev, [id]: action }));
  };

  const handleRowClick = (item: AnomalyFlag) => {
    setSelected(item.purchase_id);
    setPanel({
      operation: "_evaluate",
      endpoints: ["_evaluate"],
      stats: [
        { label: "Score", value: `${item.anomaly_score}` },
        { label: "Flagged field", value: item.flagged_field },
        { label: "Severity", value: item.severity },
      ],
      description:
        `Anomaly analysis for <em>${item.supplier}</em> (${item.purchase_id}). ` +
        `The flagged field <em>${item.flagged_field}</em> shows an anomaly score of <em>${item.anomaly_score}</em>. ` +
        `Expected: <em>${item.expected_value}</em>, actual: <em>${item.actual_value}</em>.` +
        (item.explanation ? ` Explanation: <em>${item.explanation}</em>.` : ""),
      query: `<span class="q-k">POST</span> /api/v1/_evaluate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchase_orders"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"evaluate"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>: <span class="q-v">"${item.supplier}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"amount"</span>: <span class="q-n">${item.amount}</span><br/>
&nbsp;&nbsp;}<br/>
}<br/>
<br/>
<span class="q-d">// Anomaly score: ${item.anomaly_score}</span><br/>
<span class="q-d">// Flagged: ${item.flagged_field}</span>`,
      links: [
        { label: "Evaluate API reference", url: "https://aito.ai/docs/api/evaluate" },
      ],
    });
  };

  const anomalies = data?.anomalies ?? [];

  return (
    <>
      <Nav />
      <main className="main">
        <TopBar
          breadcrumb="Intelligence"
          title="Anomaly Detection"
          subtitle={`${anomalies.length} anomalies detected`}
          live
        />
        <div className="content-area">
          <div className="content">
            {loading && <p style={{ padding: 24, color: "var(--mid)" }}>Loading...</p>}
            {error && <ErrorState message={error} command="GET /api/anomalies/scan" />}
            {data && (
              <>
                <div className="intro-banner">
                  <div className="intro-banner-text">
                    <strong>Anomaly score = inverse probability.</strong> Each PO field is
                    evaluated against learned distributions. High scores indicate values that
                    are statistically unlikely given the supplier and context. Click a row to
                    see the full evaluation.
                  </div>
                </div>

                <div className="card">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Score</th>
                        <th>PO / ID</th>
                        <th>Supplier</th>
                        <th>Amount</th>
                        <th>Flagged Field</th>
                        <th>Expected vs Actual</th>
                        <th>Severity</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {anomalies.map((item) => (
                        <tr
                          key={item.purchase_id}
                          className={`clickable${selected === item.purchase_id ? " selected" : ""}`}
                          onClick={() => handleRowClick(item)}
                        >
                          <td>
                            <div className={`a-ring ${ringClass(item.anomaly_score)}`}>
                              {item.anomaly_score}
                            </div>
                          </td>
                          <td className="mono">{item.purchase_id}</td>
                          <td>{item.supplier}</td>
                          <td className="mono">{fmtAmount(item.amount)}</td>
                          <td>{item.flagged_field}</td>
                          <td style={{ maxWidth: 200 }}>{item.expected_value} / {item.actual_value}</td>
                          <td>
                            <span
                              className={`badge ${
                                item.severity === "high"
                                  ? "b-red"
                                  : item.severity === "medium"
                                  ? "b-gold"
                                  : "b-green"
                              }`}
                            >
                              {item.severity}
                            </span>
                          </td>
                          <td onClick={(e) => e.stopPropagation()}>
                            {decisions[item.purchase_id] ? (
                              <span style={{
                                fontSize: 11,
                                padding: "3px 8px",
                                borderRadius: 4,
                                background:
                                  decisions[item.purchase_id] === "approve" || decisions[item.purchase_id] === "legitimate"
                                    ? "var(--green-light)"
                                    : decisions[item.purchase_id] === "escalate"
                                    ? "var(--red-light)"
                                    : "var(--gold-light)",
                                color:
                                  decisions[item.purchase_id] === "approve" || decisions[item.purchase_id] === "legitimate"
                                    ? "var(--green)"
                                    : decisions[item.purchase_id] === "escalate"
                                    ? "var(--red)"
                                    : "var(--gold-dark)",
                              }}>
                                ✓ {decisions[item.purchase_id]}
                              </span>
                            ) : (
                              <div style={{ display: "flex", gap: 4 }}>
                                <button
                                  className="btn btn-ghost"
                                  style={{ fontSize: 10, padding: "3px 7px" }}
                                  onClick={() => handleAction(item.purchase_id, "investigate")}
                                  title="Open for investigation"
                                >Investigate</button>
                                <button
                                  className="btn btn-ghost"
                                  style={{ fontSize: 10, padding: "3px 7px", color: "var(--red)" }}
                                  onClick={() => handleAction(item.purchase_id, "escalate")}
                                  title="Escalate to fraud team"
                                >Escalate</button>
                                <button
                                  className="btn btn-ghost"
                                  style={{ fontSize: 10, padding: "3px 7px", color: "var(--green)" }}
                                  onClick={() => handleAction(item.purchase_id, "legitimate")}
                                  title="Mark as legitimate (becomes training data)"
                                >Legitimate</button>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                      {anomalies.length === 0 && (
                        <tr>
                          <td colSpan={8} style={{ textAlign: "center", color: "var(--mid)", padding: 32 }}>
                            No anomalies detected
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </main>
    </>
  );
}

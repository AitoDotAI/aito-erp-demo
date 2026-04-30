"use client";

import { useEffect, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { poQueuePanel } from "@/lib/panel-content";
import WhyPopover from "@/components/prediction/WhyPopover";
import type { POQueueResponse, POPrediction, AitoPanelConfig, WhyExplanation, Alternative } from "@/lib/types";

export default function POQueuePage() {
  const [data, setData] = useState<POQueueResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"all" | "review" | "aito" | "rule">("all");
  const [selected, setSelected] = useState<string | null>(null);
  const { tenantId } = useTenant();
  const defaultPanel = poQueuePanel(tenantId);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);

  // Re-tone the panel when the tenant changes (e.g. visitor swaps
  // persona via the TopBar without leaving this page).
  useEffect(() => {
    setPanel(poQueuePanel(tenantId));
  }, [tenantId]);
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set());
  const [bulkMessage, setBulkMessage] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<POQueueResponse>("/api/po/pending")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleBulkApprove = (kind: "rule" | "aito_high") => {
    if (!data) return;
    const targets = data.pos.filter((o) => {
      if (approvedIds.has(o.purchase_id)) return false;
      if (kind === "rule") return o.source === "rule";
      return o.source === "aito" && o.confidence >= 0.85;
    });
    if (targets.length === 0) {
      setBulkMessage("No eligible rows to approve.");
      return;
    }
    setApprovedIds((prev) => {
      const next = new Set(prev);
      targets.forEach((t) => next.add(t.purchase_id));
      return next;
    });
    const totalAmount = targets.reduce((a, t) => a + t.amount, 0);
    setBulkMessage(
      `✓ Approved ${targets.length} ${kind === "rule" ? "rule-matched" : "high-confidence"} POs (${fmtAmount(totalAmount)} total)`
    );
    setTimeout(() => setBulkMessage(null), 6000);
  };

  const handleRowClick = (order: POPrediction) => {
    setSelected(order.purchase_id);
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: "Confidence", value: `${Math.round(order.confidence * 100)}%` },
        { label: "Cost center", value: order.cost_center ?? "—" },
        { label: "Account", value: order.account_code ?? "—" },
      ],
      description:
        `Prediction for <em>${order.purchase_id}</em> from <em>${order.supplier}</em>. ` +
        `The model predicts cost center <em>${order.cost_center}</em> with ${Math.round(order.cost_center_confidence * 100)}% confidence ` +
        `and account <em>${order.account_code}</em> with ${Math.round(order.account_code_confidence * 100)}% confidence.`,
      query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchase_orders"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>: <span class="q-v">"${order.supplier}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"description"</span>: <span class="q-v">"${order.description}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"amount"</span>: <span class="q-n">${order.amount}</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"cost_center"</span><br/>
}`,
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const metrics = data?.metrics;
  const orders = tab === "all"
    ? data?.pos ?? []
    : data?.pos?.filter((o) => o.source === tab) ?? [];

  const tabCounts = {
    all: data?.pos?.length ?? 0,
    review: data?.pos?.filter((o) => o.source === "review").length ?? 0,
    aito: data?.pos?.filter((o) => o.source === "aito").length ?? 0,
    rule: data?.pos?.filter((o) => o.source === "rule").length ?? 0,
  };

  return (
    <>
      <Nav />
      <main className="main">
        <TopBar
          breadcrumb="Procurement"
          title="PO Queue"
          subtitle={`${metrics?.total ?? "..."} unrouted POs · 47 received today`}
          live
        />
        <div className="content-area">
          <div className="content">
            {loading && <p style={{ padding: 24, color: "var(--mid)" }}>Loading...</p>}
            {error && <ErrorState message={error} command="GET /api/po/pending" />}
            {data && (
              <>
                <div className="intro-banner">
                  <div className="intro-banner-text">
                    <strong>Click any row</strong> to inspect the aito.. prediction in the
                    side panel. Gold badges indicate predicted values; gray badges show
                    low-confidence fields that need review.
                    <span className="intro-banner-freshness">
                      Predictions are live — every row added to the database is in the
                      next prediction. No batch retrain step.
                    </span>
                  </div>
                </div>

                {/* Override→relearn ribbon — surfaces only when the user
                    has just submitted a PO from Smart Entry. Closes the
                    "I overrode Aito; what happens next?" loop visibly. */}
                {data.recent_submissions && data.recent_submissions.length > 0 && (
                  <div className="relearn-banner">
                    <span className="relearn-pulse" />
                    <div className="relearn-text">
                      <strong>aito.. just learned from your {data.recent_submissions.length === 1 ? "submission" : `${data.recent_submissions.length} submissions`}.</strong>
                      {" "}Next prediction for{" "}
                      {data.recent_submissions.slice(0, 3).map((s, i, arr) => (
                        <span key={s.purchase_id}>
                          <em>{s.supplier}</em>{i < arr.length - 1 ? ", " : ""}
                        </span>
                      ))}
                      {" "}reflects what you just submitted &mdash; no batch retrain.
                    </div>
                  </div>
                )}

                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">POs Today</div>
                    <div className="kpi-val">47</div>
                    <div className="kpi-sub">↑ 12% vs avg</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Auto-coded MTD</div>
                    <div className="kpi-val">82%</div>
                    <div className="kpi-sub">vs 21% rules-only</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Avg Confidence</div>
                    <div className="kpi-val">91%</div>
                    <div className="kpi-sub">on auto-coded POs</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Pending Review</div>
                    <div className="kpi-val">{metrics!.review_count}</div>
                    <div className="kpi-sub">low-confidence flagged</div>
                  </div>
                </div>

                <div className="pill-tabs">
                  {(["all", "review", "aito", "rule"] as const).map((t) => (
                    <button
                      key={t}
                      className={`pill-tab${tab === t ? " active" : ""}`}
                      onClick={() => setTab(t)}
                    >
                      {t === "all" ? "All" : t === "review" ? "Review" : t === "aito" ? "Aito" : "Rule"}{" "}
                      ({tabCounts[t]})
                    </button>
                  ))}
                  <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
                    {bulkMessage && (
                      <span style={{
                        fontSize: 11,
                        padding: "4px 10px",
                        background: "var(--green-light)",
                        color: "var(--green)",
                        borderRadius: 5,
                      }}>{bulkMessage}</span>
                    )}
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleBulkApprove("rule")}
                      disabled={tabCounts.rule === 0}
                      style={{ fontSize: 11 }}
                    >
                      📋 Approve all rule matches ({tabCounts.rule})
                    </button>
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleBulkApprove("aito_high")}
                      disabled={tabCounts.aito === 0}
                      style={{ fontSize: 11 }}
                    >
                      🤖 Approve high-conf. aito ({tabCounts.aito})
                    </button>
                  </div>
                </div>

                <div className="card">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>PO #</th>
                        <th>Supplier</th>
                        <th>Description</th>
                        <th>Amount</th>
                        <th>Cost Center</th>
                        <th>Account</th>
                        <th>Approver</th>
                        <th>Conf.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.map((o) => (
                        <tr
                          key={o.purchase_id}
                          className={`clickable${selected === o.purchase_id ? " selected" : ""}`}
                          onClick={() => handleRowClick(o)}
                          style={approvedIds.has(o.purchase_id) ? { opacity: 0.55 } : undefined}
                        >
                          <td className="mono">
                            {o.purchase_id}
                            {approvedIds.has(o.purchase_id) && (
                              <span style={{ marginLeft: 6, color: "var(--green)", fontSize: 10 }}>✓</span>
                            )}
                          </td>
                          <td>{o.supplier}</td>
                          <td>{o.description}</td>
                          <td className="mono">{fmtAmount(o.amount)}</td>
                          <td>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                              <span className={`badge ${o.source === "rule" ? "b-green" : o.cost_center_confidence >= 0.5 ? "b-gold" : "b-gray"}`}>
                                {o.source === "rule" ? "📋 " : o.cost_center_confidence >= 0.5 ? "🤖 " : "? "}{o.cost_center || "—"}
                              </span>
                              {o.source !== "rule" && o.cost_center_why && (
                                <WhyPopover
                                  value={o.cost_center ?? ""}
                                  confidence={o.cost_center_confidence}
                                  why={o.cost_center_why}
                                  alternatives={o.cost_center_alternatives}
                                />
                              )}
                            </div>
                          </td>
                          <td>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                              <span className={`badge ${o.source === "rule" ? "b-green" : o.account_code_confidence >= 0.5 ? "b-gold" : "b-gray"}`}>
                                {o.source === "rule" ? "📋 " : o.account_code_confidence >= 0.5 ? "🤖 " : "? "}{o.account_code || "—"}
                              </span>
                              {o.source !== "rule" && o.account_code_why && (
                                <WhyPopover
                                  value={o.account_code ?? ""}
                                  confidence={o.account_code_confidence}
                                  why={o.account_code_why}
                                  alternatives={o.account_code_alternatives}
                                />
                              )}
                            </div>
                          </td>
                          <td>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                              <span className={`badge ${o.source === "rule" ? "b-green" : o.approver_confidence >= 0.5 ? "b-gold" : "b-gray"}`}>
                                {o.source === "rule" ? "📋 " : o.approver_confidence >= 0.5 ? "🤖 " : "? "}{o.approver || "—"}
                              </span>
                              {o.source !== "rule" && o.approver_why && (
                                <WhyPopover
                                  value={o.approver ?? ""}
                                  confidence={o.approver_confidence}
                                  why={o.approver_why}
                                  alternatives={o.approver_alternatives}
                                />
                              )}
                            </div>
                          </td>
                          <td>
                            <div className={`conf ${confClass(o.confidence)}`}>
                              <div className="conf-track">
                                <div
                                  className="conf-fill"
                                  style={{ width: `${o.confidence * 100}%` }}
                                />
                              </div>
                              <span className="conf-val">
                                {Math.round(o.confidence * 100)}%
                              </span>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {orders.length === 0 && (
                        <tr>
                          <td colSpan={8} style={{ textAlign: "center", color: "var(--mid)", padding: 32 }}>
                            No orders in this category
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

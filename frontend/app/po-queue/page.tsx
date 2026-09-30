"use client";

import { useEffect, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { poQueuePanel } from "@/lib/panel-content";
import { findQuery } from "@/lib/query";
import WhyPopover from "@/components/prediction/WhyPopover";
import type { POQueueResponse, POPrediction, AitoPanelConfig, WhyExplanation, Alternative } from "@/lib/types";

export default function POQueuePage() {
  const [data, setData] = useState<POQueueResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"all" | "review" | "aito" | "rule">("all");
  const [selected, setSelected] = useState<string | null>(null);
  const { tenantId } = useTenant();
  const [panel, setPanel] = useState<AitoPanelConfig>(poQueuePanel(tenantId));

  // Re-tone the panel when the tenant changes (e.g. visitor swaps
  // persona via the TopBar without leaving this page), and show a real
  // query once the queue has loaded.
  useEffect(() => {
    setPanel(poQueuePanel(tenantId, data?._queries));
  }, [tenantId, data]);
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set());
  const [bulkMessage, setBulkMessage] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch<POQueueResponse>("/api/po/pending")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  const handleBulkApprove = (kind: "rule" | "aito_high") => {
    if (!data) return;
    const targets = data.pos.filter((o) => {
      if (approvedIds.has(o.purchase_id)) return false;
      if (kind === "rule") return o.source === "rule";
      // Exactly the rows the backend did not send to review: the bar is
      // REVIEW_THRESHOLD in src/po_service.py, carried by `source`. A
      // second, stricter cutoff here left the button's count and its
      // effect disagreeing.
      return o.source === "aito";
    });
    if (targets.length === 0) {
      setBulkMessage("No eligible rows to accept.");
      return;
    }
    setApprovedIds((prev) => {
      const next = new Set(prev);
      targets.forEach((t) => next.add(t.purchase_id));
      return next;
    });
    const totalAmount = targets.reduce((a, t) => a + t.amount, 0);
    setBulkMessage(
      // "Accepted coding", never "approved": the cost centre, account and
      // approver are accepted here; authorising the spend stays with the
      // approver named on each row.
      `✓ Accepted coding on ${targets.length} ${kind === "rule" ? "rule-matched" : "Aito-coded"} POs (${fmtAmount(totalAmount)} total)`
    );
    setTimeout(() => setBulkMessage(null), 6000);
  };

  const handleRowClick = (order: POPrediction) => {
    setSelected(order.purchase_id);
    // The query behind the field that decides this row's confidence —
    // the one a reviewer would look at. A rule field sent no query.
    const fields = (["cost_center", "account_code", "approver"] as const)
      .filter((f) => !order.rule_fields?.[f]);
    const weakest = fields.reduce<typeof fields[number] | null>((low, f) =>
      low === null || order[`${f}_confidence`] < order[`${low}_confidence`] ? f : low, null);
    const where: Record<string, unknown> = { supplier: order.supplier };
    if (order.description) where.description = order.description;
    const rowQuery = weakest
      ? findQuery(data?._queries, { endpoint: "_predict", from: "purchases", target: weakest, where })
      : null;
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
      queries: rowQuery ? [rowQuery] : [],
      links: [
        { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/01-po-queue.md", kind: "doc" },
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
          subtitle={`${metrics?.total ?? "..."} POs in queue · ${metrics?.review_count ?? "..."} need review`}
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

                {/* Every figure is about the queue on this screen, computed by
                    the backend from the predictions it just made. The strip
                    used to show "47 POs today", "82% auto-coded" and "91%
                    confidence" — constants the rows below contradicted. */}
                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">In queue</div>
                    <div className="kpi-val">{metrics!.total}</div>
                    <div className="kpi-sub">pending POs</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Coded without review</div>
                    <div className="kpi-val">{Math.round(metrics!.automation_rate * 100)}%</div>
                    <div className="kpi-sub">{metrics!.rule_count} by rule · {metrics!.aito_count} by Aito</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Avg Confidence</div>
                    <div className="kpi-val">{Math.round(metrics!.avg_confidence * 100)}%</div>
                    <div className="kpi-sub">across the queue</div>
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
                      📋 Accept rule rows ({tabCounts.rule})
                    </button>
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleBulkApprove("aito_high")}
                      disabled={tabCounts.aito === 0}
                      style={{ fontSize: 11 }}
                    >
                      🤖 Accept Aito coding ({tabCounts.aito})
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
                            <div style={{ fontSize: 10, color: o.source === "review" ? "var(--gold-dark)" : "var(--mid)", fontFamily: "inherit" }}>
                              {o.status_label}
                            </div>
                            {approvedIds.has(o.purchase_id) && (
                              <span style={{ marginLeft: 6, color: "var(--green)", fontSize: 10 }}>✓</span>
                            )}
                          </td>
                          <td>{o.supplier}</td>
                          <td>{o.description}</td>
                          <td className="mono">{fmtAmount(o.amount)}</td>
                          <td>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                              <span className={`badge ${o.rule_fields?.cost_center ? "b-green" : o.cost_center_confidence >= 0.5 ? "b-gold" : "b-gray"}`}>
                                {o.rule_fields?.cost_center ? "📋 " : o.cost_center_confidence >= 0.5 ? "🤖 " : "? "}{o.cost_center || "—"}
                                {o.rule_fields?.cost_center && (
                                  <span title={o.rule_fields.cost_center} style={{ marginLeft: 4, fontSize: 9, opacity: 0.8 }}>
                                    {Math.round(o.cost_center_confidence * 100)}%
                                  </span>
                                )}
                              </span>
                              {!o.rule_fields?.cost_center && o.cost_center_why && (
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
                              <span className={`badge ${o.rule_fields?.account_code ? "b-green" : o.account_code_confidence >= 0.5 ? "b-gold" : "b-gray"}`}>
                                {o.rule_fields?.account_code ? "📋 " : o.account_code_confidence >= 0.5 ? "🤖 " : "? "}{o.account_code || "—"}
                                {o.rule_fields?.account_code && (
                                  <span title={o.rule_fields.account_code} style={{ marginLeft: 4, fontSize: 9, opacity: 0.8 }}>
                                    {Math.round(o.account_code_confidence * 100)}%
                                  </span>
                                )}
                              </span>
                              {!o.rule_fields?.account_code && o.account_code_why && (
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
                              <span className={`badge ${o.rule_fields?.approver ? "b-green" : o.approver_confidence >= 0.5 ? "b-gold" : "b-gray"}`}>
                                {o.rule_fields?.approver ? "📋 " : o.approver_confidence >= 0.5 ? "🤖 " : "? "}{o.approver || "—"}
                                {o.rule_fields?.approver && (
                                  <span title={o.rule_fields.approver} style={{ marginLeft: 4, fontSize: 9, opacity: 0.8 }}>
                                    {Math.round(o.approver_confidence * 100)}%
                                  </span>
                                )}
                              </span>
                              {!o.rule_fields?.approver && o.approver_why && (
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

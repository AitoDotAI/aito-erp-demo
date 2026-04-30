"use client";

import { useEffect, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import WhyPopover from "@/components/prediction/WhyPopover";
import type { ApprovalResponse, ApprovalPrediction, AitoPanelConfig } from "@/lib/types";

const defaultPanel: AitoPanelConfig = {
  operation: "_predict",
  endpoints: ["_predict"],
  stats: [
    { label: "Auto-routed", value: "71%" },
    { label: "Escalations", value: "6" },
    { label: "Override rate", value: "3.1%" },
  ],
  description:
    "Approval routing uses <em>aito.._predict</em> to suggest the correct approver and " +
    "escalation level for each PO from historical routing decisions. " +
    "Suggestions surface for governance review — they are not policy until promoted via " +
    "the Rule Mining workflow with explicit signoff. The audit trail records every " +
    "override and every promoted rule.",
  query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"approval_history"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"amount"</span>: <span class="q-n">$amount</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>: <span class="q-v">"$supplier"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"cost_center"</span>: <span class="q-v">"$cost_center"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"approval_level"</span><br/>
}`,
  links: [
    { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
    { label: "Approval routing guide", url: "https://aito.ai/docs/guides/approval-routing" },
  ],
};

function escalationBadge(reason: string) {
  if (!reason) return null;
  const lower = reason.toLowerCase();
  if (lower.includes("amount") || lower.includes("capex") || lower.includes("threshold"))
    return "b-red";
  if (lower.includes("first-time") || lower.includes("new vendor") || lower.includes("vendor"))
    return "b-blue";
  return "b-gold";
}

export default function ApprovalPage() {
  const [data, setData] = useState<ApprovalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);

  useEffect(() => {
    apiFetch<ApprovalResponse>("/api/approval/queue")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!data) return;
    const items = data.approvals;
    const cfo = items.filter((i) => i.predicted_level?.toLowerCase().includes("cfo")).length;
    const board = items.filter((i) => i.predicted_level?.toLowerCase().includes("board")).length;
    const avgConf = items.length > 0
      ? items.reduce((a, i) => a + i.confidence, 0) / items.length
      : 0;
    setPanel({
      ...defaultPanel,
      stats: [
        { label: "Pending", value: String(items.length) },
        { label: "CFO + Board", value: String(cfo + board) },
        { label: "Avg conf.", value: `${Math.round(avgConf * 100)}%` },
      ],
    });
  }, [data]);

  const handleRowClick = (item: ApprovalPrediction) => {
    setSelected(item.purchase_id);
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: "Confidence", value: `${Math.round(item.confidence * 100)}%` },
        { label: "Level", value: item.predicted_level },
        { label: "Amount", value: fmtAmount(item.amount) },
      ],
      description:
        `Approval prediction for <em>${item.purchase_id}</em> from <em>${item.supplier}</em>. ` +
        `Predicted approver: <em>${item.predicted_approver}</em> at level <em>${item.predicted_level}</em>. ` +
        (item.escalation_reason
          ? `Escalation reason: <em>${item.escalation_reason}</em>.`
          : "No escalation required."),
      query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"approval_history"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>: <span class="q-v">"${item.supplier}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"amount"</span>: <span class="q-n">${item.amount}</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"approval_level"</span><br/>
}`,
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const approvals = data?.approvals ?? [];

  return (
    <>
      <Nav />
      <main className="main">
        <TopBar
          breadcrumb="Procurement"
          title="Approval Routing"
          subtitle={`${approvals.length} approvals`}
          live
        />
        <div className="content-area">
          <div className="content">
            {loading && <p style={{ padding: 24, color: "var(--mid)" }}>Loading...</p>}
            {error && <ErrorState message={error} command="GET /api/approval/queue" />}
            {data && (
              <>
                <div className="intro-banner">
                  <div className="intro-banner-text">
                    <strong>Predicted approver + escalation level</strong> per pending PO.
                    Click any row to inspect the reasoning. Suggestions surface for review &mdash;
                    they are not policy until promoted via the Rule Mining workflow.
                    <span className="intro-banner-freshness">
                      Predictions reflect every approval decision logged so far. No batch retrain step.
                    </span>
                  </div>
                </div>
                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">Auto-routed</div>
                    <div className="kpi-val">71%</div>
                    <div className="kpi-sub">routed without escalation</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Approvals</div>
                    <div className="kpi-val">{approvals.length}</div>
                    <div className="kpi-sub">pending routing</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Avg Approval Time</div>
                    <div className="kpi-val">1.4h</div>
                    <div className="kpi-sub">from submission to approval</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Override Rate</div>
                    <div className="kpi-val">3.1%</div>
                    <div className="kpi-sub">predictions overridden</div>
                  </div>
                </div>

                <div className="card">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>PO #</th>
                        <th>Supplier</th>
                        <th>Amount</th>
                        <th>Escalation Reason</th>
                        <th>Predicted Approver</th>
                        <th>Conf.</th>
                        <th>Level</th>
                      </tr>
                    </thead>
                    <tbody>
                      {approvals.map((item) => (
                        <tr
                          key={item.purchase_id}
                          className={`clickable${selected === item.purchase_id ? " selected" : ""}`}
                          onClick={() => handleRowClick(item)}
                        >
                          <td className="mono">{item.purchase_id}</td>
                          <td>{item.supplier}</td>
                          <td className="mono">{fmtAmount(item.amount)}</td>
                          <td>
                            {item.escalation_reason && (
                              <span className={`badge ${escalationBadge(item.escalation_reason)}`}>
                                {item.escalation_reason}
                              </span>
                            )}
                          </td>
                          <td>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                              <span className="badge b-gold">{item.predicted_approver}</span>
                              {item.why && (
                                <WhyPopover
                                  value={item.predicted_approver}
                                  confidence={item.confidence}
                                  why={item.why}
                                  alternatives={item.alternatives}
                                />
                              )}
                            </div>
                          </td>
                          <td>
                            <div className={`conf ${confClass(item.confidence)}`}>
                              <div className="conf-track">
                                <div
                                  className="conf-fill"
                                  style={{ width: `${item.confidence * 100}%` }}
                                />
                              </div>
                              <span className="conf-val">
                                {Math.round(item.confidence * 100)}%
                              </span>
                            </div>
                          </td>
                          <td>
                            <span className="badge b-gray">{item.predicted_level}</span>
                          </td>
                        </tr>
                      ))}
                      {approvals.length === 0 && (
                        <tr>
                          <td colSpan={7} style={{ textAlign: "center", color: "var(--mid)", padding: 32 }}>
                            No approvals pending
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

"use client";

import { useEffect, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import type { RulesResponse, RuleCandidate, AitoPanelConfig } from "@/lib/types";

const defaultPanel: AitoPanelConfig = {
  operation: "_relate",
  stats: [
    { label: "Candidates", value: "12" },
    { label: "Strong", value: "4" },
    { label: "Min support", value: "20" },
  ],
  description:
    "Rule mining uses <em>aito.._relate</em> to surface recurring patterns in procurement " +
    "data as <strong>candidates for governance review</strong>. Nothing is promoted to policy " +
    "without an explicit human signoff. The lift and support columns let an auditor judge " +
    "whether a candidate is statistically meaningful before it becomes a hardcoded rule.",
  query: `<span class="q-k">POST</span> /api/v1/_relate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchase_orders"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {},<br/>
&nbsp;&nbsp;<span class="q-k">"relate"</span>: [<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-p">"cost_center"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-p">"account_code"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-p">"approver"</span><br/>
&nbsp;&nbsp;],<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"$p"</span>: { <span class="q-k">"$gt"</span>: <span class="q-n">0.85</span> }<br/>
&nbsp;&nbsp;}<br/>
}`,
  links: [
    { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
    { label: "Rule lifecycle guide", url: "https://aito.ai/docs/guides/rule-mining" },
  ],
};

export default function RulesPage() {
  const [data, setData] = useState<RulesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);

  useEffect(() => {
    apiFetch<RulesResponse>("/api/rules/candidates")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!data) return;
    setPanel({
      ...defaultPanel,
      stats: [
        { label: "Candidates", value: String(data.summary?.total ?? data.candidates.length) },
        { label: "Strong", value: String(data.summary?.strong ?? data.candidates.filter(c => c.strength === "strong").length) },
        { label: "Min support", value: "10" },
      ],
    });
  }, [data]);

  const handleRowClick = (rule: RuleCandidate) => {
    const ruleKey = `${rule.condition_field}=${rule.condition_value}`;
    setSelected(ruleKey);
    const coverage = rule.support_total > 0 ? rule.support_match / rule.support_total : 0;
    setPanel({
      operation: "_relate",
      stats: [
        { label: "Support", value: `${rule.support_match}/${rule.support_total}` },
        { label: "Lift", value: `${rule.lift.toFixed(1)}x` },
        { label: "Strength", value: rule.strength },
      ],
      description:
        `Rule: when <em>${rule.condition_field} = ${rule.condition_value}</em>, predict <em>${rule.target_field} = ${rule.target_value}</em>. ` +
        `This pattern was observed in <em>${rule.support_match}</em> of <em>${rule.support_total}</em> matching records ` +
        `(${Math.round(coverage * 100)}% coverage). Lift: ${rule.lift.toFixed(1)}x. ` +
        (rule.strength === "strong"
          ? "Strong candidate — high enough lift and support to be worth promoting after governance review."
          : rule.strength === "weak"
          ? "Weak candidate — too low support or lift; do not promote without more data."
          : "Review candidate — moderate signal; needs subject-matter judgement before promotion."),
      query: `<span class="q-k">POST</span> /api/v1/_relate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchase_orders"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-d">// ${rule.condition_field} = ${rule.condition_value}</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"relate"</span>: [<span class="q-p">"${rule.target_field}"</span>]<br/>
}<br/>
<br/>
<span class="q-d">// Support: ${rule.support_match}/${rule.support_total}</span><br/>
<span class="q-d">// Lift: ${rule.lift.toFixed(1)}x</span>`,
      links: [
        { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
        { label: "Rule lifecycle guide", url: "https://aito.ai/docs/guides/rule-mining" },
      ],
    });
  };

  const candidates = data?.candidates ?? [];
  const summary = data?.summary;
  const strongCount = summary?.strong ?? candidates.filter((r) => r.strength === "strong").length;
  const reviewCount = summary?.review ?? candidates.filter((r) => r.strength === "review").length;

  return (
    <>
      <Nav />
      <main className="main">
        <TopBar
          breadcrumb="Intelligence"
          title="Rule Mining"
          subtitle={`${candidates.length} candidates, ${strongCount} strong`}
        />
        <div className="content-area">
          <div className="content">
            {loading && <p style={{ padding: 24, color: "var(--mid)" }}>Loading...</p>}
            {error && <ErrorState message={error} command="GET /api/rules/candidates" />}
            {data && (
              <>
                <div className="intro-banner">
                  <div className="intro-banner-text">
                    <strong>Rule candidates from data.</strong> aito.._relate surfaces
                    recurring patterns; nothing here is policy yet. <strong>Promote</strong>
                    requires explicit signoff and creates an audit-trail entry. <strong>Dismiss</strong>
                    records a decision so the same pattern doesn&apos;t resurface. Rules
                    cover deterministic cases; aito.. handles the long tail.
                  </div>
                </div>

                <div className="card">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Condition</th>
                        <th>Prediction</th>
                        <th>Support</th>
                        <th>Lift</th>
                        <th>Strength</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {candidates.map((rule, idx) => {
                        const ruleKey = `${rule.condition_field}=${rule.condition_value}`;
                        return (
                          <tr
                            key={idx}
                            className={`clickable${selected === ruleKey ? " selected" : ""}`}
                            onClick={() => handleRowClick(rule)}
                          >
                            <td>
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
                                <span className="tag">
                                  {rule.condition_field} = {rule.condition_value}
                                </span>
                              </div>
                            </td>
                            <td>
                              <span className="badge b-gold">
                                {rule.target_field}: {rule.target_value}
                              </span>
                            </td>
                            <td className="mono">
                              {rule.support_match}/{rule.support_total}
                            </td>
                            <td className="mono">
                              {rule.lift.toFixed(1)}x
                            </td>
                            <td>
                              <span
                                className={`badge ${
                                  rule.strength === "strong"
                                    ? "b-green"
                                    : rule.strength === "weak"
                                    ? "b-gray"
                                    : "b-gold"
                                }`}
                              >
                                {rule.strength}
                              </span>
                            </td>
                            <td>
                              {rule.strength === "review" && (
                                <div style={{ display: "flex", gap: 4 }}>
                                  <button
                                    className="btn btn-secondary"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                    }}
                                  >
                                    Promote
                                  </button>
                                  <button
                                    className="btn btn-ghost"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                    }}
                                  >
                                    Review
                                  </button>
                                </div>
                              )}
                              {rule.strength === "strong" && (
                                <span style={{ fontSize: 11, color: "var(--green)" }}>Active</span>
                              )}
                              {rule.strength === "weak" && (
                                <span style={{ fontSize: 11, color: "var(--mid)" }}>Weak</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                      {candidates.length === 0 && (
                        <tr>
                          <td colSpan={6} style={{ textAlign: "center", color: "var(--mid)", padding: 32 }}>
                            No rules discovered yet
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

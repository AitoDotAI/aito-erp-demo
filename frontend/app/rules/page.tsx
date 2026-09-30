"use client";

import { useEffect, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { findQuery } from "@/lib/query";
import type { RulesResponse, RuleCandidate, AitoPanelConfig } from "@/lib/types";

const defaultPanel: AitoPanelConfig = {
  operation: "_relate",
  endpoints: ["_relate"],
  stats: [
    // Filled from the response once it loads (see the effect below).
    { label: "Candidates", value: "—" },
    { label: "Strong", value: "—" },
    { label: "Min support", value: "—" },
  ],
  description:
    "Rule mining uses <em>aito.._relate</em> to surface recurring patterns in procurement " +
    "data as <strong>candidates for governance review</strong>. Nothing is promoted to policy " +
    "without an explicit human signoff. The lift and support columns let an auditor judge " +
    "whether a candidate is statistically meaningful before it becomes a hardcoded rule.",
  // Filled with the query behind the top candidate once the list loads.
  queries: [],
  links: [
    { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
    { label: "Rule lifecycle guide", url: "https://aito.ai/docs/guides/rule-mining" },
    { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/06-rule-mining.md", kind: "doc" },
    { label: "Source code", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/rulemining_service.py", kind: "github" },
  ],
};

/** The `_relate` that produced this candidate: one query per condition
 *  value (a supplier or a category), relating it to the predicted field. */
function ruleQuery(data: RulesResponse | null, rule: RuleCandidate | undefined) {
  if (!rule) return [];
  const q = findQuery(data?._queries, {
    endpoint: "_relate",
    from: "purchases",
    target: rule.predicted_field,
    where: { [rule.condition_field]: rule.condition_value },
  });
  return q ? [q] : [];
}

export default function RulesPage() {
  const { tenantId } = useTenant();
  const [data, setData] = useState<RulesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch<RulesResponse>("/api/rules/candidates")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  useEffect(() => {
    if (!data) return;
    setPanel({
      ...defaultPanel,
      stats: [
        { label: "Candidates", value: String(data.summary?.total ?? data.candidates.length) },
        { label: "Strong", value: String(data.summary?.strong ?? data.candidates.filter(c => c.strength === "strong").length) },
        { label: "Min support", value: String(data.summary.min_support) },
      ],
      queries: ruleQuery(data, data.candidates[0]),
    });
  }, [data]);

  const handleRowClick = (rule: RuleCandidate) => {
    const ruleKey = `${rule.condition_field}=${rule.condition_value}`;
    setSelected(ruleKey);
    setPanel({
      operation: "_relate",
      endpoints: ["_relate"],
      stats: [
        { label: "Confidence", value: `${Math.round(rule.confidence * 100)}%` },
        { label: "Support", value: String(rule.support) },
        { label: "Lift", value: `${rule.lift.toFixed(1)}x` },
      ],
      description:
        `Rule: when <em>${rule.condition_field} = ${rule.condition_value}</em>, predict <em>${rule.predicted_field} = ${rule.predicted_value}</em>. ` +
        `Holds in <em>${Math.round(rule.confidence * 100)}%</em> of <em>${rule.support}</em> matching purchases. Lift: ${rule.lift.toFixed(1)}x. ` +
        (rule.strength === "strong"
          ? "Strong candidate — high enough confidence and support to be worth promoting after governance review."
          : rule.strength === "weak"
          ? "Weak candidate — confidence too low; do not promote without more data."
          : "Review candidate — moderate signal; needs subject-matter judgement before promotion."),
      queries: ruleQuery(data, rule),
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
                                {rule.predicted_field} = {rule.predicted_value}
                              </span>
                            </td>
                            <td className="mono">
                              {rule.support}
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

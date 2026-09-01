"use client";

import { useEffect, useMemo, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import WhyPopover from "@/components/prediction/WhyPopover";
import { apiFetch, fmtAmount } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import type {
  AitoPanelConfig,
  EngagementPlan,
  PlannerCandidate,
  PlannerOptions,
  WhyExplanation,
} from "@/lib/types";

const DEFAULT_PANEL: AitoPanelConfig = {
  operation: "_predict",
  endpoints: ["_predict", "_search"],
  stats: [
    { label: "Tables", value: "assignments · projects · quotes" },
    { label: "Predicts", value: "role · person · won · loss_reason" },
    { label: "Calls", value: "one per role + 5" },
  ],
  description:
    "Four questions off one proposal, none of them from a template. " +
    "<em>aito.._predict role</em> on <em>assignments</em> gives the role mix " +
    "work of this type historically needed; <em>_predict person</em> per role " +
    "ranks who actually does it. <em>_predict success / on_time</em> on " +
    "<em>projects</em> reads delivery risk off the proposed shape. And " +
    "<em>_predict won</em> on <em>quotes</em> answers the question the other " +
    "tables structurally cannot — <em>projects</em> only contains work that " +
    "was won, so the losses, and the objection behind each one, live only in " +
    "the quote history.",
  query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"quotes"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"customer"</span>: <span class="q-v">"City of Tampere"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"price_band"</span>: <span class="q-v">"well_over"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"competing_bid"</span>: <span class="q-n">true</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"won"</span>: <span class="q-n">false</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"loss_reason"</span><br/>
}`,
  links: [
    { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
    {
      label: "Source code",
      url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/planner_service.py",
      kind: "github",
    },
  ],
};

const BAND_LABEL: Record<string, string> = {
  under: "under the going rate",
  at_market: "at the going rate",
  over: "over the going rate",
  well_over: "well over the going rate",
};

const OBJECTION_LABEL: Record<string, string> = {
  price: "Too expensive",
  timing: "Schedule doesn't work",
  scope_fit: "Scope isn't right",
  incumbent: "Going with the incumbent",
  budget_frozen: "No budget this year",
};

function pct(p: number | null | undefined): string {
  if (p == null) return "—";
  return `${Math.round(p * 100)}%`;
}

function riskClass(p: number | null): string {
  if (p == null) return "fc-p fc-p-none";
  if (p >= 0.75) return "fc-p fc-p-high";
  if (p >= 0.5) return "fc-p fc-p-mid";
  return "fc-p fc-p-low";
}

/** Availability is a separate axis from fit — a perfect match at 300%
 *  allocated is not a staffing answer. */
function loadClass(status: string): string {
  if (status === "overloaded") return "pl-load pl-load-bad";
  if (status === "at_risk") return "pl-load pl-load-warn";
  if (status === "available") return "pl-load pl-load-ok";
  return "pl-load";
}

export default function PlannerPage() {
  const { tenantId } = useTenant();
  const [options, setOptions] = useState<PlannerOptions | null>(null);
  const [plan, setPlan] = useState<EngagementPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [panel, setPanel] = useState<AitoPanelConfig>(DEFAULT_PANEL);

  const [projectType, setProjectType] = useState("");
  const [customer, setCustomer] = useState("");
  const [scope, setScope] = useState("");
  const [quoted, setQuoted] = useState(180000);
  const [duration, setDuration] = useState(150);
  const [teamSize, setTeamSize] = useState(8);
  const [priority, setPriority] = useState("high");
  const [site, setSite] = useState("");
  const [competing, setCompeting] = useState(true);
  const [existing, setExisting] = useState(true);

  useEffect(() => {
    setPlan(null);
    apiFetch<PlannerOptions>("/api/planner/options")
      .then((o) => {
        setOptions(o);
        const firstType = o.project_types[0] ?? "";
        setProjectType(firstType);
        setCustomer(o.customers_by_type[firstType]?.[0] ?? "");
      })
      .catch((e) => setError(e.message));
  }, [tenantId]);

  const customers = useMemo(
    () => options?.customers_by_type[projectType] ?? [],
    [options, projectType],
  );

  useEffect(() => {
    if (customers.length && !customers.includes(customer)) {
      setCustomer(customers[0]);
    }
  }, [customers, customer]);

  // Selecting a customer pre-fills the site their work usually runs at,
  // the way a CRM would. Still editable — the point of the field is
  // that it moves the staffing answer.
  useEffect(() => {
    const hinted = options?.site_by_customer?.[customer];
    if (hinted) setSite(hinted);
  }, [customer, options]);

  const submit = () => {
    setBusy(true);
    setError(null);
    apiFetch<EngagementPlan>("/api/planner/plan", {
      method: "POST",
      body: JSON.stringify({
        customer,
        scope,
        project_type: projectType,
        quoted_eur: quoted,
        duration_days: duration,
        team_size: teamSize,
        priority,
        site,
        competing_bid: competing,
        existing_customer: existing,
      }),
    })
      .then(setPlan)
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  };

  const showCandidate = (role: string, c: PlannerCandidate) => {
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: "Fit", value: pct(c.fit) },
        { label: "Current load", value: `${c.current_load_pct}%` },
        { label: "Site", value: c.site },
      ],
      description:
        `<em>${c.person}</em> — ${c.title}, ${c.seniority}, ` +
        `${c.years_experience}y, based in ${c.site}. Skills on record: ` +
        `<em>${c.skills}</em>. ` +
        `Ranked as <em>${role}</em> on ` +
        `<em>${projectType}</em> work. Fit is P(person | project type, role) ` +
        `over the assignment history — how often this person is the one who ` +
        `actually does this job. Their current allocation is ` +
        `<em>${c.current_load_pct}%</em>, read from the same aggregation the ` +
        `capacity view uses, so best-fit and actually-free are visible ` +
        `together. They are often not the same person.`,
      query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"assignments"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"project_type"</span>: <span class="q-v">"${projectType}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"role"</span>: <span class="q-v">"${role}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"site"</span>: <span class="q-v">"${site}"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"person"</span><br/>
}<br/>
<br/>
<span class="q-d">// person links to people — one call returns the</span><br/>
<span class="q-d">// ranking AND the matched person's whole row</span>`,
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const bestFit = (candidates: PlannerCandidate[]) =>
    candidates.reduce((m, c) => Math.max(m, c.fit), 0) || 1;

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar title="Engagement Planner" breadcrumb="Operations" />
        <div className="content-area">
          <div className="content">
            {error && (
              <ErrorState message={error} command="POST /api/planner/plan" />
            )}

            <section className="card">
              <div className="card-head">
                <span className="card-title">The proposal</span>
                <span className="card-meta">
                  everything below is predicted from it
                </span>
              </div>
              <div className="pl-form">
                <label className="pl-field">
                  <span>Work type</span>
                  <select
                    value={projectType}
                    onChange={(e) => setProjectType(e.target.value)}
                  >
                    {(options?.project_types ?? []).map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </label>
                <label className="pl-field">
                  <span>Customer</span>
                  <select
                    value={customer}
                    onChange={(e) => setCustomer(e.target.value)}
                  >
                    {customers.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <label className="pl-field pl-field-wide">
                  <span>Scope</span>
                  <input
                    type="text"
                    value={scope}
                    placeholder="New assembly hall foundation and frame"
                    onChange={(e) => setScope(e.target.value)}
                  />
                </label>
                <label className="pl-field">
                  <span>Quote (€)</span>
                  <input
                    type="number"
                    value={quoted}
                    step={10000}
                    onChange={(e) => setQuoted(Number(e.target.value))}
                  />
                </label>
                <label className="pl-field">
                  <span>Duration (days)</span>
                  <input
                    type="number"
                    value={duration}
                    onChange={(e) => setDuration(Number(e.target.value))}
                  />
                </label>
                <label className="pl-field">
                  <span>Team size</span>
                  <input
                    type="number"
                    value={teamSize}
                    min={1}
                    max={20}
                    onChange={(e) => setTeamSize(Number(e.target.value))}
                  />
                </label>
                <label className="pl-field">
                  <span>Site</span>
                  <select value={site} onChange={(e) => setSite(e.target.value)}>
                    <option value="">any site</option>
                    {(options?.sites ?? []).map((sName) => (
                      <option key={sName} value={sName}>{sName}</option>
                    ))}
                  </select>
                </label>
                <label className="pl-field">
                  <span>Priority</span>
                  <select
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                  >
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                  </select>
                </label>
                <label className="pl-check">
                  <input
                    type="checkbox"
                    checked={competing}
                    onChange={(e) => setCompeting(e.target.checked)}
                  />
                  <span>Competing bid</span>
                </label>
                <label className="pl-check">
                  <input
                    type="checkbox"
                    checked={existing}
                    onChange={(e) => setExisting(e.target.checked)}
                  />
                  <span>Existing customer</span>
                </label>
                <button className="pl-go" onClick={submit} disabled={busy}>
                  {busy ? "Predicting…" : "Plan it"}
                </button>
              </div>
            </section>

            {plan && (
              <>
                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">Fair price</div>
                    <div className="kpi-val">
                      {plan.price ? fmtAmount(plan.price.median_eur) : "—"}
                    </div>
                    <div className="kpi-sub">
                      {plan.price
                        ? `${fmtAmount(plan.price.low_eur)}–${fmtAmount(
                            plan.price.high_eur,
                          )} · ${plan.price.comparable_count} comparable`
                        : "no comparable history"}
                    </div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Your quote sits</div>
                    <div className="kpi-val">
                      {plan.price ? `${Math.round(plan.price.ratio * 100)}%` : "—"}
                    </div>
                    <div className="kpi-sub">
                      {plan.price ? BAND_LABEL[plan.price.band] : ""}
                    </div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Chance they say yes</div>
                    <div
                      className="kpi-val"
                      style={{
                        color:
                          (plan.sales?.win_p ?? 1) < 0.5
                            ? "var(--red)"
                            : "var(--green)",
                      }}
                    >
                      {pct(plan.sales?.win_p)}
                    </div>
                    <div className="kpi-sub">
                      {plan.sales
                        ? `${plan.sales.quote_history} comparable quotes`
                        : "no quote history"}
                    </div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Delivers successfully</div>
                    <div className="kpi-val">
                      {pct(plan.delivery.success_p)}
                    </div>
                    <div className="kpi-sub">
                      on time {pct(plan.delivery.on_time_p)} · on budget{" "}
                      {pct(plan.delivery.on_budget_p)}
                    </div>
                  </div>
                </div>

                <div className="proj-grid">
                  <section className="card">
                    <div className="card-head">
                      <span className="card-title">
                        Proposed team — role mix from comparable work
                      </span>
                      <span className="card-meta">{plan.team_size} people</span>
                    </div>
                    {plan.roles.map((slot) => {
                      const best = bestFit(slot.candidates);
                      return (
                        <div className="pl-role" key={slot.role}>
                          <div className="pl-role-head">
                            <span className="pl-role-name">
                              {slot.count} × {slot.role}
                            </span>
                            <span className="pl-role-share">
                              {pct(slot.share)} of comparable teams
                            </span>
                          </div>
                          <table className="tbl">
                            <tbody>
                              {slot.candidates.map((c) => (
                                <tr
                                  key={c.person}
                                  className="clickable"
                                  onClick={() => showCandidate(slot.role, c)}
                                >
                                  <td style={{ width: "52%" }}>
                                    <div className="pl-person">{c.person}</div>
                                    {/* The reason, in the person's own
                                        attributes — returned by the same
                                        call that ranked them, because
                                        assignments.person links to people. */}
                                    <div className="pl-chips">
                                      {c.matches.map((m) => (
                                        <span
                                          className={
                                            site && m === `based in ${site}`
                                              ? "pl-chip pl-chip-hit"
                                              : "pl-chip"
                                          }
                                          key={m}
                                        >
                                          {m}
                                        </span>
                                      ))}
                                    </div>
                                  </td>
                                  <td style={{ width: "20%" }}>
                                    <div className="pl-fit-track">
                                      <div
                                        className="pl-fit-bar"
                                        style={{
                                          width: `${(c.fit / best) * 100}%`,
                                        }}
                                      />
                                    </div>
                                  </td>
                                  <td
                                    style={{ width: "12%", textAlign: "right" }}
                                  >
                                    {pct(c.fit)}
                                  </td>
                                  <td
                                    style={{ width: "16%", textAlign: "right" }}
                                  >
                                    <span className={loadClass(c.status)}>
                                      {c.current_load_pct}%
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      );
                    })}
                  </section>

                  <section className="card">
                    <div className="card-head">
                      <span className="card-title">
                        If they say no, this is what they say
                      </span>
                      <span className="card-meta">quotes._predict</span>
                    </div>
                    {plan.sales ? (
                      <div className="pl-obj">
                        {plan.sales.objections.map((o) => (
                          <div className="pl-obj-row" key={o.reason}>
                            <span className="pl-obj-label">
                              {OBJECTION_LABEL[o.reason] ?? o.reason}
                            </span>
                            <div className="pl-obj-track">
                              <div
                                className="pl-obj-bar"
                                style={{ width: `${o.p * 100}%` }}
                              />
                            </div>
                            <span className="pl-obj-p">{pct(o.p)}</span>
                          </div>
                        ))}
                        <p className="pl-note">
                          Conditioned on the deal being lost — these are the
                          reasons ranked among losses, not the chance of
                          losing.{" "}
                          {(plan.sales.win_why as WhyExplanation)?.lifts && (
                            <WhyPopover
                              value="win"
                              confidence={plan.sales.win_p ?? 0}
                              why={plan.sales.win_why as WhyExplanation}
                            />
                          )}
                        </p>
                      </div>
                    ) : (
                      <p className="pl-note">
                        This tenant has no quote history, so the sales read is
                        unavailable — the delivery numbers above still apply.
                      </p>
                    )}

                    <div className="card-head" style={{ marginTop: 8 }}>
                      <span className="card-title">Delivery risk</span>
                    </div>
                    <table className="tbl">
                      <tbody>
                        <tr>
                          <td>Succeeds</td>
                          <td style={{ textAlign: "right" }}>
                            <span className={riskClass(plan.delivery.success_p)}>
                              {pct(plan.delivery.success_p)}
                            </span>
                          </td>
                          <td style={{ width: 30 }}>
                            {(plan.delivery.success_why as WhyExplanation)
                              ?.lifts && (
                              <WhyPopover
                                value="success"
                                confidence={plan.delivery.success_p ?? 0}
                                why={plan.delivery.success_why as WhyExplanation}
                              />
                            )}
                          </td>
                        </tr>
                        <tr>
                          <td>Lands on time</td>
                          <td style={{ textAlign: "right" }}>
                            <span className={riskClass(plan.delivery.on_time_p)}>
                              {pct(plan.delivery.on_time_p)}
                            </span>
                          </td>
                          <td>
                            {(plan.delivery.on_time_why as WhyExplanation)
                              ?.lifts && (
                              <WhyPopover
                                value="on time"
                                confidence={plan.delivery.on_time_p ?? 0}
                                why={plan.delivery.on_time_why as WhyExplanation}
                              />
                            )}
                          </td>
                        </tr>
                        <tr>
                          <td>Lands on budget</td>
                          <td style={{ textAlign: "right" }}>
                            <span className={riskClass(plan.delivery.on_budget_p)}>
                              {pct(plan.delivery.on_budget_p)}
                            </span>
                          </td>
                          <td></td>
                        </tr>
                      </tbody>
                    </table>
                  </section>
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

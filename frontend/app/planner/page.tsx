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

/** A role row as the user has it: how many seats, and what that seat
 *  requires. Requirements live here rather than on the proposal —
 *  "must have Next.js" is a fact about the frontend seat. */
interface PlannerRoleEdit {
  role: string;
  count: number;
  skills?: string;
  seniority?: string;
}

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

/** Availability over the project's window — the axis that decides
 *  whether a match is usable at all. Being on leave for part of the
 *  build is a different answer from being 90% booked, so they read
 *  differently. */
function availClass(c: PlannerCandidate): string {
  if (c.absent_months.length) return "pl-load pl-load-bad";
  if (!c.available) return "pl-load pl-load-warn";
  return "pl-load pl-load-ok";
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
  const [startMonth, setStartMonth] = useState(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  });
  const [competing, setCompeting] = useState(true);
  const [localOnly, setLocalOnly] = useState(false);
  // null = use the predicted role mix. Any edit pins the list, so the
  // prediction stops overwriting a decision the user just made.
  const [roleEdits, setRoleEdits] = useState<PlannerRoleEdit[] | null>(null);
  // Which seat's picker is open, and any manual reassignments. Aito
  // proposes; the scheduler disposes, and the override is per seat.
  const [openSeat, setOpenSeat] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [existing, setExisting] = useState(true);

  useEffect(() => {
    setPlan(null);
    setRoleEdits(null);
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

  const submit = (roles?: PlannerRoleEdit[] | null) => {
    const useRoles = roles === undefined ? roleEdits : roles;
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
        start_month: startMonth,
        local_only: localOnly,
        roles: useRoles,
        competing_bid: competing,
        existing_customer: existing,
      }),
    })
      .then((p) => {
        setPlan(p);
        setOverrides({});
        setOpenSeat(null);
      })
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

  /** The role list currently in force — the user's edit if there is
   *  one, otherwise whatever the prediction returned. */
  const currentRoles = (): PlannerRoleEdit[] =>
    roleEdits ??
    (plan?.roles ?? []).map((r) => ({
      role: r.role,
      count: r.count,
      skills: r.skills,
      seniority: r.seniority,
    }));

  const editRoles = (next: PlannerRoleEdit[]) => {
    const cleaned = next.filter((r) => r.count > 0);
    setRoleEdits(cleaned);
    submit(cleaned);
  };

  const changeCount = (role: string, delta: number) =>
    editRoles(
      currentRoles().map((r) =>
        r.role === role ? { ...r, count: r.count + delta } : r,
      ),
    );

  const setRoleReq = (role: string, patch: Partial<PlannerRoleEdit>) =>
    editRoles(
      currentRoles().map((r) => (r.role === role ? { ...r, ...patch } : r)),
    );

  const addRole = (role: string) => {
    const rows = currentRoles();
    editRoles(
      rows.some((r) => r.role === role)
        ? rows.map((r) => (r.role === role ? { ...r, count: r.count + 1 } : r))
        : [...rows, { role, count: 1 }],
    );
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
                  <span>
                    Team size
                    {plan?.shape.suggested_size ? (
                      <button
                        className="pl-hint"
                        onClick={(e) => {
                          e.preventDefault();
                          setTeamSize(plan.shape.suggested_size ?? teamSize);
                        }}
                      >
                        Aito says {plan.shape.suggested_size}
                      </button>
                    ) : null}
                  </span>
                  <input
                    type="number"
                    value={teamSize}
                    min={1}
                    max={20}
                    onChange={(e) => setTeamSize(Number(e.target.value))}
                  />
                </label>
                <label className="pl-field">
                  <span>Starts</span>
                  <input
                    type="month"
                    value={startMonth}
                    onChange={(e) => setStartMonth(e.target.value)}
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
                    checked={localOnly}
                    onChange={(e) => setLocalOnly(e.target.checked)}
                  />
                  <span>Based on site only</span>
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
                <button
                  className="pl-go"
                  onClick={() => {
                    setRoleEdits(null);
                    submit(null);
                  }}
                  disabled={busy}
                >
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
                      money · team · customer
                    </div>
                  </div>
                </div>

                <div className="proj-grid">
                  <section className="card card-overflow">
                    <div className="card-head">
                      <span className="card-title">The team</span>
                      <span className="card-meta">
                        {plan.roles.reduce((n, r) => n + r.count, 0)} seats ·
                        free across {plan.window_months} months from{" "}
                        {plan.start_month}
                        <select
                          className="pl-add-role"
                          value=""
                          onChange={(e) => {
                            if (e.target.value) addRole(e.target.value);
                          }}
                        >
                          <option value="">+ add role</option>
                          {(options?.roles ?? []).map((r) => (
                            <option key={r} value={r}>{r}</option>
                          ))}
                        </select>
                        {roleEdits && (
                          <button
                            className="pl-reset"
                            onClick={() => {
                              setRoleEdits(null);
                              submit(null);
                            }}
                          >
                            reset to predicted mix
                          </button>
                        )}
                      </span>
                    </div>
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th style={{ width: "26%" }}>Role</th>
                          <th>Assignee</th>
                          <th style={{ width: "16%", textAlign: "right" }}>
                            Fit
                          </th>
                          <th style={{ width: "20%", textAlign: "right" }}>
                            Free in window
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {plan.roles.flatMap((slot) =>
                          slot.assignees.map((_, seat) => {
                            const key = `${slot.role}#${seat}`;
                            const chosenName = overrides[key] ?? slot.assignees[seat];
                            const chosen = slot.candidates.find(
                              (c) => c.person === chosenName,
                            );
                            const best = bestFit(slot.candidates);
                            return (
                              <tr key={key}>
                                <td>
                                  <div className="pl-role-cell">
                                    {slot.role}
                                    {seat === 0 && (
                                      <span className="pl-role-edit">
                                        <button
                                          title="one fewer"
                                          onClick={() => changeCount(slot.role, -1)}
                                        >
                                          −
                                        </button>
                                        <button
                                          title="one more"
                                          onClick={() => changeCount(slot.role, 1)}
                                        >
                                          +
                                        </button>
                                      </span>
                                    )}
                                  </div>
                                  <div className="pl-role-sub">
                                    {slot.share
                                      ? `${pct(slot.share)} of comparable teams`
                                      : "added by hand"}
                                  </div>
                                  {seat === 0 && (
                                    <div className="pl-role-req">
                                      <input
                                        type="text"
                                        placeholder="must have…"
                                        defaultValue={slot.skills}
                                        onBlur={(e) => {
                                          if (e.target.value !== slot.skills)
                                            setRoleReq(slot.role, {
                                              skills: e.target.value,
                                            });
                                        }}
                                      />
                                      <select
                                        value={slot.seniority}
                                        onChange={(e) =>
                                          setRoleReq(slot.role, {
                                            seniority: e.target.value,
                                          })
                                        }
                                      >
                                        <option value="">any</option>
                                        {(options?.seniorities ?? []).map((sn) => (
                                          <option key={sn} value={sn}>
                                            {sn}
                                          </option>
                                        ))}
                                      </select>
                                    </div>
                                  )}
                                </td>
                                <td>
                                  <button
                                    className="pl-pick"
                                    onClick={() =>
                                      setOpenSeat(openSeat === key ? null : key)
                                    }
                                  >
                                    <span>{chosenName || "unstaffed"}</span>
                                    <span className="pl-pick-sub">
                                      {chosen?.title ?? ""}
                                    </span>
                                    <span className="pl-caret">▾</span>
                                  </button>
                                  {openSeat === key && (
                                    <div className="pl-menu">
                                      <div className="pl-menu-head">
                                        Ranked by <em>_predict person</em> given
                                        role + site
                                      {slot.skills || slot.seniority ||
                                       plan.local_only
                                        ? ", filtered on person.skills / " +
                                          "person.seniority / person.site"
                                        : ""}
                                      . Availability is over the project's own
                                        window — click to reassign
                                      </div>
                                      {slot.candidates.map((c) => (
                                        <button
                                          key={c.person}
                                          className={
                                            c.person === chosenName
                                              ? "pl-opt pl-opt-on"
                                              : "pl-opt"
                                          }
                                          onClick={() => {
                                            setOverrides({
                                              ...overrides,
                                              [key]: c.person,
                                            });
                                            setOpenSeat(null);
                                            showCandidate(slot.role, c);
                                          }}
                                        >
                                          <div className="pl-opt-top">
                                            <span className="pl-opt-name">
                                              {c.person}
                                            </span>
                                            {(c.why as WhyExplanation)?.lifts && (
                                              <span
                                                onClick={(e) => e.stopPropagation()}
                                              >
                                                <WhyPopover
                                                  value={c.person}
                                                  confidence={c.fit}
                                                  why={c.why as WhyExplanation}
                                                />
                                              </span>
                                            )}
                                            <span className="pl-opt-fit">
                                              {pct(c.fit)}
                                            </span>
                                            <span className={availClass(c)}>
                                              {c.available
                                                ? `${c.free_pct}% free`
                                                : c.absent_months.length
                                                  ? `${c.absence_kind} ${c.absent_months.join(", ")}`
                                                  : `${c.booked_pct}% booked`}
                                            </span>
                                          </div>
                                          <div className="pl-fit-track">
                                            <div
                                              className="pl-fit-bar"
                                              style={{
                                                width: `${(c.fit / best) * 100}%`,
                                              }}
                                            />
                                          </div>
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
                                        </button>
                                      ))}
                                    </div>
                                  )}
                                </td>
                                <td style={{ textAlign: "right" }}>
                                  {pct(chosen?.fit ?? null)}
                                </td>
                                <td style={{ textAlign: "right" }}>
                                  {chosen && (
                                    <span className={availClass(chosen)}>
                                      {chosen.available
                                        ? `${chosen.free_pct}% free`
                                        : chosen.absent_months.length
                                          ? chosen.absence_kind
                                          : `${chosen.booked_pct}% booked`}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            );
                          }),
                        )}
                      </tbody>
                    </table>
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
                      <span className="card-meta">projects._predict ×6</span>
                    </div>
                    {[
                      { rows: plan.delivery.core, head: "Was it worth doing" },
                      { rows: plan.delivery.qualifying, head: "And did it hold up" },
                    ].map((group) => (
                      <div key={group.head}>
                        <div className="pl-group">{group.head}</div>
                        <table className="tbl">
                          <tbody>
                            {group.rows.map((o) => (
                              <tr key={o.field}>
                                <td>{o.label}</td>
                                <td style={{ textAlign: "right", width: "22%" }}>
                                  <span className={riskClass(o.p)}>
                                    {pct(o.p)}
                                  </span>
                                </td>
                                <td style={{ width: 30 }}>
                                  {(o.why as WhyExplanation)?.lifts && (
                                    <WhyPopover
                                      value={o.label}
                                      confidence={o.p ?? 0}
                                      why={o.why as WhyExplanation}
                                    />
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ))}
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

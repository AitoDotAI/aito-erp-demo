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
  OutlookResponse,
  ProjectOutlook,
  WhyExplanation,
} from "@/lib/types";

const DEFAULT_PANEL: AitoPanelConfig = {
  operation: "_predict",
  endpoints: ["_search", "_predict"],
  stats: [
    { label: "Table", value: "projects" },
    { label: "Targets", value: "on_time · on_budget" },
    { label: "Model", value: "% of completion" },
  ],
  description:
    "The order book is arithmetic — every ERP can spread a signed project's " +
    "value across its scheduled months. What no ERP has is an opinion on " +
    "whether those months will hold. <em>aito.._predict</em> on " +
    "<em>on_time</em> asks the delivery history: for a project of this type, " +
    "this size, this duration, under this manager, how often did the schedule " +
    "survive? The blue bar is the schedule. The gold bar is the schedule after " +
    "that answer is applied — the same money, moved in time.",
  query: `<span class="q-k">POST</span> /api/{version}/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"projects"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"project_type"</span>: <span class="q-v">"construction"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"manager"</span>: <span class="q-v">"M. Hakala"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"team_size"</span>: <span class="q-n">9</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"budget_eur"</span>: <span class="q-n">130400</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"duration_days"</span>: <span class="q-n">136</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"priority"</span>: <span class="q-v">"high"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"on_time"</span><br/>
}`,
  links: [
    { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/19-revenue-outlook.md", kind: "doc" },
    { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
    {
      label: "Source code",
      url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/forecast_service.py",
      kind: "github",
    },
  ],
};

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function monthLabel(month: string): string {
  const [year, mon] = month.split("-");
  return `${MONTH_NAMES[Number(mon) - 1]} ${year.slice(2)}`;
}

function pct(p: number | null | undefined): string {
  if (p == null) return "—";
  return `${Math.round(p * 100)}%`;
}

/** Confidence colouring, matching the thresholds the other views use. */
function pClass(p: number | null): string {
  if (p == null) return "fc-p fc-p-none";
  if (p >= 0.85) return "fc-p fc-p-high";
  if (p >= 0.6) return "fc-p fc-p-mid";
  return "fc-p fc-p-low";
}

export default function ForecastPage() {
  const { tenantId } = useTenant();
  const [data, setData] = useState<OutlookResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [panel, setPanel] = useState<AitoPanelConfig>(DEFAULT_PANEL);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch<OutlookResponse>("/api/forecast/outlook")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  useEffect(() => {
    if (!data) return;
    setPanel({
      ...DEFAULT_PANEL,
      stats: [
        { label: "In flight", value: String(data.kpis.active_count) },
        { label: "Order book", value: fmtAmount(data.kpis.order_book_eur) },
        { label: "At risk", value: fmtAmount(data.kpis.at_risk_eur) },
      ],
    });
  }, [data]);

  // Trim the tail: the model runs nine months out so nothing slips off
  // the end, but months past the last euro are dead space on a chart.
  const months = useMemo(() => {
    const all = data?.months ?? [];
    let last = 0;
    all.forEach((m, i) => {
      if (m.scheduled_eur > 0 || m.expected_eur > 0) last = i;
    });
    return all.slice(0, last + 1);
  }, [data]);

  const peak = useMemo(
    () =>
      months.reduce(
        (max, m) => Math.max(max, m.scheduled_eur, m.expected_eur),
        0,
      ),
    [months],
  );

  const handleRowClick = (p: ProjectOutlook) => {
    setSelected(p.project_id);
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: "P(on time)", value: pct(p.on_time_p) },
        { label: "P(on budget)", value: pct(p.on_budget_p) },
        { label: "Unbilled", value: fmtAmount(p.remaining_eur) },
      ],
      description:
        `<em>${p.name}</em> for <em>${p.customer}</em>, scheduled to close ` +
        `<em>${monthLabel(p.scheduled_end_month)}</em> with ` +
        `<em>${fmtAmount(p.remaining_eur)}</em> still to recognise. Aito puts ` +
        `<em>${pct(p.on_time_p)}</em> on that date holding, which moves ` +
        `<em>${fmtAmount(p.at_risk_eur)}</em> of it past the scheduled end. ` +
        `Open the <em>?</em> on the row for which parts of the project's ` +
        `shape drove that number.`,
      query: `<span class="q-k">POST</span> /api/{version}/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"projects"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"project_type"</span>: <span class="q-v">"${p.project_type}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"manager"</span>: <span class="q-v">"${p.manager}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"budget_eur"</span>: <span class="q-n">${p.budget_eur}</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"on_time"</span><br/>
}<br/>
<br/>
<span class="q-d">// P(on_time) = ${pct(p.on_time_p)} → ${fmtAmount(p.at_risk_eur)} slips</span>`,
      links: [
        { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar title="Revenue Outlook" breadcrumb="Operations" />
        <div className="content-area">
          <div className="content">
            {error && (
              <ErrorState message={error} command="GET /api/forecast/outlook" />
            )}
            {!error && (loading || !data) && (
              <p style={{ padding: 24, color: "var(--mid)" }}>Loading…</p>
            )}
            {!error && data && (
              <>
                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">Order book</div>
                    <div className="kpi-val">
                      {fmtAmount(data.kpis.order_book_eur)}
                    </div>
                    <div className="kpi-sub">
                      unbilled across {data.kpis.active_count} projects
                    </div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Next three months</div>
                    <div className="kpi-val">
                      {fmtAmount(data.kpis.next_quarter_eur)}
                    </div>
                    <div className="kpi-sub">risk-adjusted</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">At risk of slipping</div>
                    <div className="kpi-val" style={{ color: "var(--red)" }}>
                      {fmtAmount(data.kpis.at_risk_eur)}
                    </div>
                    <div className="kpi-sub">
                      past its scheduled month
                    </div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Overdue</div>
                    <div
                      className="kpi-val"
                      style={{
                        color:
                          data.kpis.overdue_count > 0
                            ? "var(--red)"
                            : "var(--green)",
                      }}
                    >
                      {data.kpis.overdue_count}
                    </div>
                    <div className="kpi-sub">
                      {data.kpis.overdue_count > 0
                        ? `${fmtAmount(data.kpis.overdue_eur)} unbilled`
                        : "every project inside its schedule"}
                    </div>
                  </div>
                </div>

                <section className="card">
                  <div className="card-head">
                    <span className="card-title">
                      Revenue by month — scheduled vs predicted
                    </span>
                    <span className="card-meta">as of {monthLabel(data.as_of)}</span>
                  </div>
                  <div className="fc-chart">
                    {months.map((m) => (
                      <div className="fc-col" key={m.month}>
                        <div className="fc-bars">
                          <div
                            className="fc-bar fc-bar-sched"
                            style={{
                              height: peak
                                ? `${(m.scheduled_eur / peak) * 100}%`
                                : "0%",
                            }}
                            title={`Scheduled ${fmtAmount(m.scheduled_eur)}`}
                          />
                          <div
                            className="fc-bar fc-bar-exp"
                            style={{
                              height: peak
                                ? `${(m.expected_eur / peak) * 100}%`
                                : "0%",
                            }}
                            title={`Predicted ${fmtAmount(m.expected_eur)}`}
                          />
                        </div>
                        <div className="fc-col-val">
                          {fmtAmount(m.expected_eur)}
                        </div>
                        <div className="fc-col-label">{monthLabel(m.month)}</div>
                      </div>
                    ))}
                  </div>
                  <div className="fc-legend">
                    <span>
                      <i className="fc-swatch fc-bar-sched" /> Scheduled by the
                      order book
                    </span>
                    <span>
                      <i className="fc-swatch fc-bar-exp" /> Predicted after
                      slip risk
                    </span>
                  </div>
                </section>

                <section className="card">
                  <div className="card-head">
                    <span className="card-title">
                      In flight — most value at risk first
                    </span>
                    <span className="card-meta">
                      {data.projects.length} projects
                    </span>
                  </div>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Manager</th>
                        <th>Closes</th>
                        <th style={{ textAlign: "right" }}>Unbilled</th>
                        <th style={{ textAlign: "right" }}>P(on time)</th>
                        <th style={{ textAlign: "right" }}>P(on budget)</th>
                        <th style={{ textAlign: "right" }}>At risk</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.projects.map((p) => {
                        const why = (p.on_time_why ?? {}) as WhyExplanation;
                        return (
                          <tr
                            key={p.project_id}
                            className={`clickable${
                              selected === p.project_id ? " selected" : ""
                            }`}
                            onClick={() => handleRowClick(p)}
                          >
                            <td>
                              <div className="proj-name">{p.name}</div>
                              <div className="proj-sub">
                                {p.customer} · {p.project_type}
                              </div>
                            </td>
                            <td>{p.manager}</td>
                            <td>
                              {monthLabel(p.scheduled_end_month)}
                              {p.overdue && (
                                <span className="fc-overdue">overdue</span>
                              )}
                            </td>
                            <td style={{ textAlign: "right" }}>
                              {fmtAmount(p.remaining_eur)}
                            </td>
                            <td style={{ textAlign: "right" }}>
                              <span className={pClass(p.on_time_p)}>
                                {pct(p.on_time_p)}
                              </span>
                            </td>
                            <td style={{ textAlign: "right" }}>
                              <span className={pClass(p.on_budget_p)}>
                                {pct(p.on_budget_p)}
                              </span>
                            </td>
                            <td
                              style={{
                                textAlign: "right",
                                color: p.at_risk_eur > 0 ? "var(--red)" : undefined,
                              }}
                            >
                              {fmtAmount(p.at_risk_eur)}
                            </td>
                            <td>
                              {why.lifts && (
                                <WhyPopover
                                  value="on time"
                                  confidence={p.on_time_p ?? 0}
                                  why={why}
                                />
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </section>
              </>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

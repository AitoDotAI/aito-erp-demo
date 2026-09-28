"use client";

import { useState, useEffect } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import type { InventoryResponse, StockCheck, WarningScore, AitoPanelConfig } from "@/lib/types";

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Below this many real shortfalls, a difference of one warning is noise.
// The page says so rather than letting a 1-vs-0 read as a result.
const MIN_SHORTFALLS_TO_COMPARE = 10;

function monthOf(yyyyMm: string): number {
  const m = Number(yyyyMm.split("-")[1]);
  if (!Number.isInteger(m) || m < 1 || m > 12) {
    throw new Error(`Unexpected month ${JSON.stringify(yyyyMm)} — expected YYYY-MM`);
  }
  return m;
}

const fmtMonth = (yyyyMm: string) => `${MONTH_NAMES[monthOf(yyyyMm) - 1]} ${yyyyMm.split("-")[0]}`;
const fmtDaily = (n: number) => n.toFixed(2);

const escapeHtml = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// A value as it would appear in the JSON body, made safe for the panel's HTML.
const asJsonHtml = (v: string) => escapeHtml(JSON.stringify(v));

// The forecast body the backend sent for one item, read from the
// response rather than rebuilt here, so the panel cannot drift from it.
function forecastQuery(item: StockCheck): string {
  const where = Object.entries(item.where)
    .map(([k, v]) => `    <span class="q-k">"${escapeHtml(k)}"</span>: <span class="q-v">${asJsonHtml(v)}</span>`)
    .join(",\n");
  return `<span class="q-k">POST</span> <span class="q-v">/api/{version}/_estimate</span>\n{\n` +
    `  <span class="q-k">"from"</span>: <span class="q-v">"monthly_demand"</span>,\n` +
    `  <span class="q-k">"where"</span>: {\n${where}\n  },\n` +
    `  <span class="q-k">"estimate"</span>: <span class="q-p">"units_sold"</span>\n}`;
}

const panelDescription =
  "Will what is on the shelf, plus what lands within the lead time, cover demand until a new order could arrive? " +
  "The <em>stock</em> table is <strong>synthetic</strong>: simulated from the same sales history, managed by a trailing-average min/max reorder rule." +
  "<br/><br/>The question is asked twice — with aito.._estimate's forecast for the month, and with the <em>trailing three-month average</em> that rule uses." +
  "<br/><br/>The month after the cutoff is <em>held out</em>, so each warning is checked against what actually sold.";

const panelLinks: AitoPanelConfig["links"] = [
  { label: "aito.ai/docs/estimate", url: "https://aito.ai/docs/api/estimate" },
  { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/10-inventory-intelligence.md", kind: "doc" },
  { label: "Source code", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/inventory_service.py", kind: "github" },
];

function panelFor(data: InventoryResponse | null, item: StockCheck | null): AitoPanelConfig {
  const base = { operation: "_estimate", endpoints: ["_estimate", "_search"], links: panelLinks };
  if (!data || !item) {
    return {
      ...base,
      stats: data
        ? [
          { label: "Critical", value: String(data.counts.critical) },
          { label: "Low", value: String(data.counts.low) },
          { label: "Overstock", value: String(data.counts.overstock) },
        ]
        : [{ label: "Critical", value: "—" }, { label: "Low", value: "—" }, { label: "Overstock", value: "—" }],
      description: panelDescription,
      query: data && data.items.length > 0
        ? forecastQuery(data.items[0])
        // Before the first response there is no real query to show.
        : "",
    };
  }
  const cover = item.days_of_cover === null ? "unbounded (no demand forecast)" : `${item.days_of_cover} days`;
  return {
    ...base,
    stats: [
      { label: "Aito /day", value: fmtDaily(item.aito_daily) },
      { label: "Rule /day", value: fmtDaily(item.trailing_daily) },
      { label: "Actual /day", value: fmtDaily(item.actual_daily) },
    ],
    description:
      `<strong>${escapeHtml(item.name)}</strong> (${escapeHtml(item.sku)})<br/><br/>` +
      `On hand <em>${item.on_hand}</em>, arriving within the ${item.lead_time_days}-day lead time <em>${item.arriving_in_time}</em>. ` +
      `By Aito's forecast that covers <em>${cover}</em>.<br/><br/>` +
      `Aito says <em>${item.aito_short ? "will run short" : "covered"}</em>; the trailing rule says <em>${item.rule_short ? "will run short" : "covered"}</em>. ` +
      `In the held-out month it <em>${item.actually_short ? "did run short" : "did not run short"}</em>.` +
      `<br/><br/>${panelDescription}`,
    query: forecastQuery(item),
  };
}

function statusBadge(status: StockCheck["status"]) {
  switch (status) {
    case "critical": return <span className="badge b-red">Critical</span>;
    case "low": return <span className="badge b-gold">Low</span>;
    case "ok": return <span className="badge b-green">OK</span>;
    case "overstock": return <span className="badge b-blue">Overstock</span>;
  }
}

// Plain words for the comparison, with no winner unless the counts carry one.
function verdict(aito: WarningScore, rule: WarningScore): string {
  const shortfalls = aito.real_shortfalls;
  if (aito.real_shortfalls !== rule.real_shortfalls) {
    throw new Error("Both methods are scored against the same held-out month; real_shortfalls must match");
  }
  const same = aito.raised === rule.raised && aito.right === rule.right && aito.caught === rule.caught;
  if (same) {
    return `Both raised the same warnings with the same outcome. ${shortfalls} real shortfall${shortfalls === 1 ? "" : "s"} is too few to separate the two methods.`;
  }
  if (shortfalls < MIN_SHORTFALLS_TO_COMPARE) {
    return `The counts differ, but with ${shortfalls} real shortfall${shortfalls === 1 ? "" : "s"} in the held-out month that difference is too small to separate the two methods.`;
  }
  return "The counts differ; compare the right and caught columns directly — each is out of the numbers shown.";
}

export default function InventoryPage() {
  const { tenantId } = useTenant();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<InventoryResponse | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [bannerOpen, setBannerOpen] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setSelected(null);
    apiFetch<InventoryResponse>("/api/inventory/status")
      .then((res) => setData(res))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  const items = data?.items ?? [];
  const panel = panelFor(data, selected === null ? null : items[selected] ?? null);

  if (error) {
    return (
      <>
        <Nav />
        <div className="main">
          <TopBar title="Inventory Intelligence" breadcrumb="Product" />
          <div className="content-area">
            <div className="content">
              <ErrorState message={error} command="GET /api/inventory/status" />
            </div>
            <AitoPanel config={panelFor(null, null)} />
          </div>
        </div>
      </>
    );
  }

  const asOf = data ? fmtMonth(data.as_of) : "—";
  const kpis: Array<{ key: StockCheck["status"]; label: string; color: string; sub: string }> = [
    { key: "critical", label: "Critical", color: "var(--red)", sub: "cover shorter than the lead time" },
    { key: "low", label: "Low", color: "var(--gold-dark)", sub: "cover under twice the lead time" },
    { key: "ok", label: "OK", color: "var(--green)", sub: "at least twice the lead time" },
    { key: "overstock", label: "Overstock", color: "var(--blue)", sub: "more than 90 days of cover" },
  ];

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar
          title="Inventory Intelligence"
          breadcrumb="Product"
          kpis={[{ icon: "🏗️", label: `${data?.counts.critical ?? 0} critical` }]}
        />
        <div className="content-area">
          <div className="content">
            {bannerOpen && (
              <div className="intro-banner">
                <div className="intro-banner-text">
                  <strong>Will it run out before the next delivery?</strong> For the {data?.items_checked ?? "—"} busiest
                  stocked items as of {asOf}, stock on hand plus what arrives within the lead time is set against
                  demand — once with aito..&apos;s forecast, once with the trailing average a plain ERP reorder rule
                  uses. The following month is held out, so both answers are checked against what really sold.
                  {data?.synthetic_stock && (
                    <> The stock levels are <strong>synthetic</strong>: simulated from the same sales history, not
                      taken from a real warehouse.</>
                  )}
                </div>
                <span className="intro-banner-close" onClick={() => setBannerOpen(false)}>&times;</span>
              </div>
            )}

            <div className="kpi-row">
              {kpis.map((k) => (
                <div className="kpi" key={k.key}>
                  <div className="kpi-label">{k.label}</div>
                  <div className="kpi-val" style={{ color: k.color }}>{data?.counts[k.key] ?? "—"}</div>
                  <div className="kpi-sub">{k.sub}, by Aito&apos;s forecast</div>
                </div>
              ))}
            </div>

            {data && (
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head">
                  <span className="card-title">Was the warning right?</span>
                  <span className="card-meta">&ldquo;will run short&rdquo; warnings, checked against {fmtMonth(data.as_of)} sales (held out)</span>
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Forecast</th>
                        <th>Warnings raised</th>
                        <th>Right</th>
                        <th>Real shortfalls caught</th>
                      </tr>
                    </thead>
                    <tbody>
                      {([
                        ["Aito _estimate", data.warnings.aito],
                        ["ERP rule: trailing 3-month average", data.warnings.trailing_rule],
                      ] as const).map(([label, w]) => (
                        <tr key={label}>
                          <td>{label}</td>
                          <td className="mono">{w.raised}</td>
                          <td className="mono">{w.right} of {w.raised}</td>
                          <td className="mono">{w.caught} of {w.real_shortfalls}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ padding: "10px 16px", fontSize: 11.5, color: "var(--mid)", borderTop: "1px solid var(--border)" }}>
                  {verdict(data.warnings.aito, data.warnings.trailing_rule)}
                </div>
              </div>
            )}

            <div className="card" style={{ marginBottom: 16 }}>
              <div className="card-head">
                <span className="card-title">Stock check · as of {asOf}</span>
                {data?.synthetic_stock && <span className="badge b-gray">Synthetic stock</span>}
              </div>
              <div style={{ overflowX: "auto" }}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>Status</th>
                      <th>On hand</th>
                      <th>Arriving in time</th>
                      <th>Lead time</th>
                      <th>Aito /day</th>
                      <th>Rule /day</th>
                      <th title="What actually sold in the held-out month">Actual /day</th>
                      <th>Days of cover</th>
                      <th>Ran short?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item, i) => (
                      <tr key={item.sku} className={`clickable${selected === i ? " selected" : ""}`} onClick={() => setSelected(i)}>
                        <td>
                          <div>{item.name}</div>
                          <div style={{ fontSize: 10.5, color: "var(--mid)" }}>
                            <span className="mono">{item.sku}</span> · {item.category}
                          </div>
                        </td>
                        <td style={{ whiteSpace: "nowrap" }}>
                          {statusBadge(item.status)}
                          {item.aito_short !== item.rule_short && (
                            <span
                              className="badge b-purple"
                              style={{ marginLeft: 4 }}
                              title={`The trailing rule says ${item.rule_short ? "it will run short" : "it is covered"}`}
                            >
                              rule disagrees
                            </span>
                          )}
                        </td>
                        <td className="mono">{item.on_hand}</td>
                        <td className="mono">
                          {item.arriving_in_time}
                          {item.next_delivery_month && item.arriving_in_time > 0 && (
                            <span style={{ color: "var(--mid)" }}> · {fmtMonth(item.next_delivery_month)}</span>
                          )}
                        </td>
                        <td className="mono">{item.lead_time_days}d</td>
                        <td className="mono">{fmtDaily(item.aito_daily)}</td>
                        <td className="mono">{fmtDaily(item.trailing_daily)}</td>
                        <td className="mono">{fmtDaily(item.actual_daily)}</td>
                        <td className="mono">{item.days_of_cover === null ? "∞" : `${item.days_of_cover}d`}</td>
                        <td>
                          {item.actually_short
                            ? <span style={{ color: "var(--red)", fontWeight: 600, fontSize: 11 }}>Yes</span>
                            : <span style={{ color: "var(--mid)", fontSize: 11 }}>No</span>}
                        </td>
                      </tr>
                    ))}
                    {items.length === 0 && !loading && (
                      <tr>
                        <td colSpan={10} style={{ textAlign: "center", color: "var(--mid)", padding: 32 }}>
                          No stocked items to check
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

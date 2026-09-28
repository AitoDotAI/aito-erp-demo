"use client";

import { useState, useEffect } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import type {
  DemandResponse,
  DemandProduct,
  DemandMeasured,
  DemandHorizonMonth,
  AitoPanelConfig,
} from "@/lib/types";

const LINKS: AitoPanelConfig["links"] = [
  { label: "aito.ai/docs/estimate", url: "https://aito.ai/docs/api/estimate" },
  { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/09-demand-forecast.md", kind: "doc" },
  { label: "Source code", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/demand_service.py", kind: "github" },
];

const DESCRIPTION =
  "The last six months of sales were <em>held out</em>: aito.._estimate never saw them, so every forecast here sits next to what actually sold. " +
  "It is scored against the two rules a buyer already has &mdash; <em>same month last year</em>, and the <em>trailing 3-month mean</em> a plain ERP reorder rule uses. " +
  "The error is WAPE: total units missed divided by total units sold.";

const defaultPanel: AitoPanelConfig = {
  operation: "_estimate",
  endpoints: ["_estimate"],
  stats: [
    { label: "Aito WAPE", value: "—" },
    { label: "Last year", value: "—" },
    { label: "Held out", value: "—" },
  ],
  description: DESCRIPTION,
  query: `<span class="q-k">POST</span> <span class="q-v">/api/{version}/_estimate</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"monthly_demand"</span>,\n  <span class="q-k">"where"</span>: { … },\n  <span class="q-k">"estimate"</span>: <span class="q-p">"units_sold"</span>\n}`,
  links: LINKS,
};

// ─── Formatting ───

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthIndex(month: string): number {
  const m = Number(month.slice(5, 7));
  if (!Number.isInteger(m) || m < 1 || m > 12) throw new Error(`Unexpected month string: ${month}`);
  return m - 1;
}

const fmtMonth = (month: string) => `${MONTH_ABBR[monthIndex(month)]} ${month.slice(0, 4)}`;
const fmtPct = (x: number) => `${(x * 100).toFixed(1)}%`;
const fmtWape = (x: number | null) => (x == null ? "—" : fmtPct(x));
const fmtSigned = (x: number) => {
  const r = Math.round(x);
  return r > 0 ? `+${r}` : String(r);
};

// A value as it would appear in the JSON body, made safe for the panel's
// HTML: a name with `"` or `<` must neither end the string nor open a tag.
const asJsonHtml = (v: string) =>
  JSON.stringify(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escHtml = (v: string) => v.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// The body the backend sent for one held-out month, read from the
// response rather than rebuilt here, so the panel cannot drift from it.
function estimateQuery(h: DemandHorizonMonth): string {
  const where = Object.entries(h.where)
    .map(([k, v]) => `    <span class="q-k">"${escHtml(k)}"</span>: <span class="q-v">${asJsonHtml(v)}</span>`)
    .join(",\n");
  return `<span class="q-k">POST</span> <span class="q-v">/api/{version}/_estimate</span>\n{\n` +
    `  <span class="q-k">"from"</span>: <span class="q-v">"monthly_demand"</span>,\n` +
    `  <span class="q-k">"where"</span>: {\n${where}\n  },\n` +
    `  <span class="q-k">"estimate"</span>: <span class="q-p">"units_sold"</span>\n}`;
}

// ─── The measured claim ───

const METHODS = [
  { key: "aito", label: "Aito _estimate" },
  { key: "last_year", label: "Same month last year" },
  { key: "trailing", label: "Trailing 3-month rule" },
] as const;

// The one sentence the page commits to, written from the numbers so it
// stays true for every tenant — on some corpora last year's rule wins,
// and the page must say so rather than carry a fixed boast.
function measuredSentence(m: DemandMeasured): string {
  const vs = (label: string, other: number) => {
    if (m.aito < other) return `lower than ${label} (${fmtPct(other)})`;
    if (m.aito > other) return `higher than ${label} (${fmtPct(other)})`;
    return `equal to ${label}`;
  };
  return `Over ${m.n} held-out product-months, Aito's forecasts missed by ${fmtPct(m.aito)} of units sold — ` +
    `${vs("same month last year", m.last_year)} and ${vs("the trailing 3-month rule", m.trailing)}.`;
}

// ─── Chart ───

const CHART = { w: 720, h: 260, left: 44, right: 12, top: 14, bottom: 30 };

const COLOURS = {
  history: "var(--ink)",
  aito: "var(--aito-teal)",
  lastYear: "var(--gold)",
  trailing: "var(--mid)",
};

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (step * mag >= v) return step * mag;
  }
  return 10 * mag;
}

function DemandChart({ product }: { product: DemandProduct }) {
  const { history, horizon } = product;
  const n = history.length + horizon.length;
  const values = [
    ...history.map((p) => p.units),
    ...horizon.flatMap((h) => [h.actual, h.aito, h.last_year, h.trailing]),
  ];
  const yMax = niceMax(Math.max(...values));
  const plotW = CHART.w - CHART.left - CHART.right;
  const plotH = CHART.h - CHART.top - CHART.bottom;
  const x = (i: number) => CHART.left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) => CHART.top + plotH - (v / yMax) * plotH;
  const path = (pts: Array<[number, number]>) =>
    pts.map(([i, v], k) => `${k === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  const h0 = history.length;
  const lastHist: [number, number] | null = h0 > 0 ? [h0 - 1, history[h0 - 1].units] : null;
  const actualPts: Array<[number, number]> = [
    ...(lastHist ? [lastHist] : []),
    ...horizon.map((h, k): [number, number] => [h0 + k, h.actual]),
  ];
  const cutoffX = h0 > 0 ? (x(h0 - 1) + x(h0)) / 2 : x(0);
  const months = [...history.map((p) => p.month), ...horizon.map((h) => h.month)];
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);

  return (
    <svg
      viewBox={`0 0 ${CHART.w} ${CHART.h}`}
      role="img"
      aria-label={`Monthly units sold for ${product.name}, with forecasts for the held-out months`}
      style={{ width: "100%", height: "auto", display: "block" }}
    >
      {/* Held-out band: everything right of the cutoff was hidden from _estimate. */}
      <rect x={cutoffX} y={CHART.top} width={CHART.w - CHART.right - cutoffX} height={plotH}
        style={{ fill: "var(--gold-light)", opacity: 0.45 }} />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={CHART.left} x2={CHART.w - CHART.right} y1={y(t)} y2={y(t)}
            style={{ stroke: "var(--border)", strokeWidth: 1 }} />
          <text x={CHART.left - 6} y={y(t) + 3} textAnchor="end"
            style={{ fill: "var(--mid)", fontSize: 10, fontFamily: "'DM Mono', monospace" }}>
            {Math.round(t)}
          </text>
        </g>
      ))}
      {months.map((m, i) =>
        monthIndex(m) % 6 === 0 ? (
          <text key={m} x={x(i)} y={CHART.h - 10} textAnchor="middle"
            style={{ fill: "var(--mid)", fontSize: 10, fontFamily: "'DM Mono', monospace" }}>
            {fmtMonth(m)}
          </text>
        ) : null,
      )}
      <line x1={cutoffX} x2={cutoffX} y1={CHART.top} y2={CHART.top + plotH}
        style={{ stroke: "var(--gold-dark)", strokeWidth: 1, strokeDasharray: "3 3" }} />
      <text x={cutoffX + 5} y={CHART.top + 11}
        style={{ fill: "var(--gold-dark)", fontSize: 10, fontWeight: 600 }}>
        held out →
      </text>

      {horizon.length > 0 && (
        <path d={path(horizon.map((h, k): [number, number] => [h0 + k, h.trailing]))}
          style={{ fill: "none", stroke: COLOURS.trailing, strokeWidth: 1.25, strokeDasharray: "2 3" }} />
      )}
      {horizon.length > 0 && (
        <path d={path(horizon.map((h, k): [number, number] => [h0 + k, h.last_year]))}
          style={{ fill: "none", stroke: COLOURS.lastYear, strokeWidth: 2, strokeDasharray: "6 3" }} />
      )}
      {history.length > 0 && (
        <path d={path(history.map((p, i): [number, number] => [i, p.units]))}
          style={{ fill: "none", stroke: COLOURS.history, strokeWidth: 1.5 }} />
      )}
      {actualPts.length > 1 && (
        <path d={path(actualPts)} style={{ fill: "none", stroke: COLOURS.history, strokeWidth: 2 }} />
      )}
      {horizon.length > 0 && (
        <path d={path(horizon.map((h, k): [number, number] => [h0 + k, h.aito]))}
          style={{ fill: "none", stroke: COLOURS.aito, strokeWidth: 2.5 }} />
      )}
      {horizon.map((h, k) => (
        <g key={h.month}>
          <circle cx={x(h0 + k)} cy={y(h.actual)} r={3} style={{ fill: COLOURS.history }} />
          <circle cx={x(h0 + k)} cy={y(h.aito)} r={3.5}
            style={{ fill: "var(--card)", stroke: COLOURS.aito, strokeWidth: 2 }} />
        </g>
      ))}
    </svg>
  );
}

function LegendItem({ colour, dash, label }: { colour: string; dash?: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <svg width="22" height="8" aria-hidden="true">
        <line x1="0" x2="22" y1="4" y2="4" style={{ stroke: colour, strokeWidth: 2, strokeDasharray: dash }} />
      </svg>
      {label}
    </span>
  );
}

// ─── Page ───

export default function DemandPage() {
  const { tenantId } = useTenant();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DemandResponse | null>(null);
  const [selected, setSelected] = useState(0);
  const [bannerOpen, setBannerOpen] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch<DemandResponse>("/api/demand/forecast")
      .then((res) => {
        setData(res);
        // A different tenant has different products; an index into the
        // old list would point at an unrelated one.
        setSelected(0);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  const measured = data?.measured ?? null;
  const product = data?.products[selected] ?? null;

  const panel: AitoPanelConfig =
    data && measured
      ? {
          operation: "_estimate",
          endpoints: ["_estimate"],
          stats: [
            { label: "Aito WAPE", value: fmtPct(measured.aito) },
            { label: "Last year", value: fmtPct(measured.last_year) },
            { label: "Held out", value: String(measured.n) },
          ],
          description: product
            ? `${DESCRIPTION}<br/><br/>The query below is the one sent for <strong>${escHtml(product.name)}</strong>, ${fmtMonth(product.horizon[0]?.month ?? data.cutoff)}. ` +
              `The <em>where</em> says which product, when in the year, and what it sold in the same month last year &mdash; banded, so the evidence generalises across products instead of matching one exact count.`
            : DESCRIPTION,
          query: product && product.horizon.length > 0
            ? estimateQuery(product.horizon[0])
            : defaultPanel.query,
          links: LINKS,
        }
      : defaultPanel;

  if (error) {
    return (
      <>
        <Nav />
        <div className="main">
          <TopBar title="Demand Forecast" breadcrumb="Product" />
          <div className="content-area">
            <div className="content">
              <ErrorState message={error} command="GET /api/demand/forecast" />
            </div>
            <AitoPanel config={defaultPanel} />
          </div>
        </div>
      </>
    );
  }

  const lowest = measured ? Math.min(measured.aito, measured.last_year, measured.trailing) : null;

  // Per-product WAPE, from the rows in the table below it.
  const productWape = (key: "aito" | "last_year" | "trailing") => {
    if (!product) return null;
    const actual = product.horizon.reduce((s, h) => s + h.actual, 0);
    if (actual === 0) return null;
    return product.horizon.reduce((s, h) => s + Math.abs(h[key] - h.actual), 0) / actual;
  };

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar
          title="Demand Forecast"
          breadcrumb="Product"
          kpis={data ? [{ icon: "📈", label: `${data.products.length} products · cutoff ${fmtMonth(data.cutoff)}` }] : []}
        />
        <div className="content-area">
          <div className="content">
            {bannerOpen && (
              <div className="intro-banner">
                <div className="intro-banner-text">
                  <strong>A forecast you can check.</strong> The last six months were hidden from aito.., forecast from the history before them, and are shown here next to what actually sold &mdash; and next to the rules a buyer would otherwise use.
                </div>
                <span className="intro-banner-close" onClick={() => setBannerOpen(false)}>&times;</span>
              </div>
            )}

            <div className="kpi-row">
              {METHODS.map(({ key, label }) => {
                const v = measured ? measured[key] : null;
                const isLowest = v != null && v === lowest;
                return (
                  <div
                    key={key}
                    className="kpi"
                    style={key === "aito" ? { borderColor: "var(--aito-teal)" } : undefined}
                  >
                    <div className="kpi-label" style={key === "aito" ? { color: "var(--aito-teal)" } : undefined}>
                      {label}
                    </div>
                    <div className="kpi-val">{v != null ? fmtPct(v) : "—"}</div>
                    <div className="kpi-sub" style={isLowest ? { color: "var(--green)", fontWeight: 600 } : undefined}>
                      {v == null ? "WAPE" : isLowest ? "WAPE · lowest error" : "WAPE"}
                    </div>
                  </div>
                );
              })}
              <div className="kpi">
                <div className="kpi-label">Held-out forecasts</div>
                <div className="kpi-val">{measured ? measured.n : "—"}</div>
                <div className="kpi-sub">
                  {measured ? `measured ${measured.measured_on} on ${measured.engine_build}` : ""}
                </div>
              </div>
            </div>
            {measured && (
              <div style={{ fontSize: 12.5, color: "var(--ink)", margin: "-4px 0 16px", lineHeight: 1.55 }}>
                {measuredSentence(measured)}{" "}
                <span style={{ color: "var(--mid)" }}>{measured.metric}.</span>
              </div>
            )}

            {data && (
              <div className="pill-tabs" style={{ flexWrap: "wrap" }}>
                {data.products.map((p, i) => (
                  <div
                    key={p.sku}
                    className={`pill-tab${i === selected ? " active" : ""}`}
                    onClick={() => setSelected(i)}
                    role="button"
                    title={`${p.sku} · ${p.supplier}`}
                  >
                    {p.name} <span style={{ opacity: 0.7 }}>· {p.category}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="card">
              <div className="card-head">
                <span className="card-title">
                  {product ? `${product.name} — units sold per month` : "Units sold per month"}
                </span>
                <span className="card-meta">{product ? `${product.sku} · ${product.supplier}` : ""}</span>
              </div>
              <div style={{ padding: "12px 16px 8px" }}>
                {loading && !product && (
                  <div style={{ color: "var(--mid)", padding: 32, textAlign: "center" }}>Loading…</div>
                )}
                {!loading && !product && (
                  <div style={{ color: "var(--mid)", padding: 32, textAlign: "center" }}>No demand history for this tenant</div>
                )}
                {/* The SVG scales to the card: on a phone the held-out months
                    stay on screen, which is the part the chart exists to show. */}
                {product && <DemandChart product={product} />}
              </div>
              {product && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", padding: "0 16px 12px", fontSize: 11, color: "var(--mid)" }}>
                  <LegendItem colour={COLOURS.history} label="Actual units sold" />
                  <LegendItem colour={COLOURS.aito} label="Aito _estimate" />
                  <LegendItem colour={COLOURS.lastYear} dash="6 3" label="Same month last year" />
                  <LegendItem colour={COLOURS.trailing} dash="2 3" label="Trailing 3-month mean" />
                </div>
              )}
              <div className="card-meta" style={{ padding: "0 16px 12px" }}>
                Data: a synthetic demo corpus generated with per-category seasonality.
              </div>
            </div>

            {product && (
              <div className="card">
                <div className="card-head">
                  <span className="card-title">Held-out months — forecast against actual</span>
                  <span className="card-meta">error = forecast − actual, in units</span>
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Month</th>
                        <th>Actual</th>
                        <th>Aito</th>
                        <th>Error</th>
                        <th>Last year</th>
                        <th>Error</th>
                        <th>Trailing</th>
                        <th>Error</th>
                        <th>Rows weighted</th>
                      </tr>
                    </thead>
                    <tbody>
                      {product.horizon.map((h) => {
                        const errs = { aito: h.aito - h.actual, last_year: h.last_year - h.actual, trailing: h.trailing - h.actual };
                        const best = Math.min(...Object.values(errs).map(Math.abs));
                        const errCell = (e: number) => (
                          <td className="mono" style={Math.abs(e) === best ? { color: "var(--green)", fontWeight: 600 } : { color: "var(--mid)" }}>
                            {fmtSigned(e)}
                          </td>
                        );
                        return (
                          <tr key={h.month}>
                            <td className="mono">{fmtMonth(h.month)}</td>
                            <td className="mono" style={{ fontWeight: 600 }}>{h.actual}</td>
                            <td className="mono" style={{ color: "var(--aito-teal)", fontWeight: 600 }}>{Math.round(h.aito)}</td>
                            {errCell(errs.aito)}
                            <td className="mono">{Math.round(h.last_year)}</td>
                            {errCell(errs.last_year)}
                            <td className="mono">{Math.round(h.trailing)}</td>
                            {errCell(errs.trailing)}
                            <td className="mono" style={{ color: "var(--mid)" }}>{h.neighbours}</td>
                          </tr>
                        );
                      })}
                      <tr>
                        <td colSpan={2} style={{ color: "var(--mid)", fontSize: 11 }}>WAPE, this product</td>
                        <td />
                        <td className="mono">{fmtWape(productWape("aito"))}</td>
                        <td />
                        <td className="mono">{fmtWape(productWape("last_year"))}</td>
                        <td />
                        <td className="mono">{fmtWape(productWape("trailing"))}</td>
                        <td />
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

"use client";

import { useState, useEffect } from "react";
import type { ReactNode } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import type {
  PricingResponse,
  PricingProduct,
  PricedQuote,
  PricingMeasured,
  AitoPanelConfig,
} from "@/lib/types";

// Unit prices run from a few euros to a few hundred, so whole-euro
// rounding (fmtAmount) would erase the very differences a buyer judges.
const fmtPrice = (n: number) =>
  "€ " + n.toLocaleString("fi-FI", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtPct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;

const signedPct = (x: number) => `${x > 0 ? "+" : ""}${x.toFixed(1)}%`;

// A value as it would appear in the JSON body, made safe for the panel's
// HTML: a supplier name must neither end the string early nor open a tag.
const asJsonHtml = (v: string) =>
  JSON.stringify(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// The body the backend sends for one quote. The `where` is exactly the
// response's `features`, filled from the quote's own row — the date is
// not in it, because the date is what separates history from the quote.
function estimateQuery(product: PricingProduct, quote: PricedQuote): string {
  return (
    `<span class="q-k">POST</span> <span class="q-v">/api/{version}/_estimate</span>\n{\n` +
    `  <span class="q-k">"from"</span>: <span class="q-v">"price_reference"</span>,\n` +
    `  <span class="q-k">"where"</span>: {\n` +
    `    <span class="q-k">"product_id"</span>: <span class="q-v">${asJsonHtml(product.sku)}</span>,\n` +
    `    <span class="q-k">"supplier"</span>: <span class="q-v">${asJsonHtml(quote.supplier)}</span>,\n` +
    `    <span class="q-k">"volume"</span>: <span class="q-v">${quote.volume}</span>\n` +
    `  },\n` +
    `  <span class="q-k">"estimate"</span>: <span class="q-p">"unit_price"</span>\n}`
  );
}

const PANEL_LINKS: AitoPanelConfig["links"] = [
  { label: "aito.ai/docs/estimate", url: "https://aito.ai/docs/api/estimate" },
  { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/08-price-intelligence.md", kind: "doc" },
  { label: "Source code", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/pricing_service.py", kind: "github" },
];

const PANEL_DESCRIPTION =
  "aito.._estimate predicts a quote's <em>unit price</em> from the product, the supplier and the volume, " +
  "using only price records dated before the cutoff &mdash; it never saw the quote it judges. " +
  "Beside it sits the product's own earlier median, the rule a buyer already has &mdash; " +
  "the measured strip on the page compares the two.";

const defaultPanel: AitoPanelConfig = {
  operation: "_estimate",
  endpoints: ["_estimate"],
  description: PANEL_DESCRIPTION,
  query:
    `<span class="q-k">POST</span> <span class="q-v">/api/{version}/_estimate</span>\n{\n` +
    `  <span class="q-k">"from"</span>: <span class="q-v">"price_reference"</span>,\n` +
    `  <span class="q-k">"where"</span>: { <span class="q-k">"product_id"</span>, <span class="q-k">"supplier"</span>, <span class="q-k">"volume"</span> },\n` +
    `  <span class="q-k">"estimate"</span>: <span class="q-p">"unit_price"</span>\n}`,
  links: PANEL_LINKS,
};

// One sentence, computed from the measurement rather than written for it:
// if the numbers move, the claim moves with them.
function measuredSentence(m: PricingMeasured): string {
  const gap = (m.median_error - m.aito_error) * 100;
  const errors =
    `Aito's estimate misses the list price by ${fmtPct(m.aito_error)} on average, ` +
    `the product's own earlier median by ${fmtPct(m.median_error)}`;
  const verdict =
    Math.abs(gap) < 1
      ? " — parity, within a point."
      : gap > 0
        ? ` — the estimate is closer by ${gap.toFixed(1)} points.`
        : ` — the median is closer by ${(-gap).toFixed(1)} points.`;
  const catches =
    ` Of ${m.overcharges} overcharges, Aito flags ${m.aito_caught} (raising ${m.aito_flagged} flags in all) ` +
    `and the median ${m.median_caught} (${m.median_flagged} flags).`;
  return errors + verdict + catches;
}

export default function PricingPage() {
  const { tenantId } = useTenant();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<PricingResponse | null>(null);
  const [selectedSku, setSelectedSku] = useState<string | null>(null);
  const [selectedQuoteId, setSelectedQuoteId] = useState<string | null>(null);
  const [bannerOpen, setBannerOpen] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch<PricingResponse>("/api/pricing/estimate")
      .then((res) => {
        setData(res);
        setSelectedSku(res.products[0]?.sku ?? null);
        setSelectedQuoteId(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  const product = data?.products.find((p) => p.sku === selectedSku) ?? null;
  // Default to the flagged quote if there is one: it is the row that asks
  // a buyer to do something.
  const quote =
    product?.quotes.find((q) => q.price_id === selectedQuoteId) ??
    product?.quotes.find((q) => q.flagged) ??
    product?.quotes[0] ??
    null;

  const panel: AitoPanelConfig =
    product && quote
      ? {
          ...defaultPanel,
          stats: [
            { label: "Quoted", value: fmtPrice(quote.quoted) },
            { label: "Estimate", value: fmtPrice(quote.aito) },
            { label: "Neighbours", value: String(quote.neighbours) },
          ],
          query: estimateQuery(product, quote),
        }
      : defaultPanel;

  if (error) {
    return (
      <>
        <Nav />
        <div className="main">
          <TopBar title="Price Intelligence" breadcrumb="Product" />
          <div className="content-area">
            <div className="content">
              <ErrorState message={error} command="GET /api/pricing/estimate" />
            </div>
            <AitoPanel config={defaultPanel} />
          </div>
        </div>
      </>
    );
  }

  const allQuotes = data?.products.flatMap((p) => p.quotes) ?? [];
  const flaggedShown = allQuotes.filter((q) => q.flagged).length;
  const m = data?.measured;
  const marginPct = data ? Math.round(data.flag_margin * 100) : null;

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar
          title="Price Intelligence"
          breadcrumb="Product"
          kpis={data ? [{ icon: "⚠", label: `${flaggedShown} of ${allQuotes.length} quotes flagged` }] : []}
        />
        <div className="content-area">
          <div className="content">
            {bannerOpen && data && (
              <div className="intro-banner">
                <div className="intro-banner-text">
                  <strong>Is this quote fair, judged only by what came before?</strong>{" "}
                  Every quote below is a real price record dated on or after {data.cutoff}. Aito estimates
                  its unit price from earlier records only, and a quote more than {marginPct}% above that
                  estimate is flagged. Products with no earlier price are not shown: with nothing to anchor
                  on, the estimate is not reliable enough to judge a quote.
                </div>
                <span className="intro-banner-close" onClick={() => setBannerOpen(false)}>&times;</span>
              </div>
            )}

            {loading && !data && <div className="card" style={{ padding: 16 }}>Loading price history…</div>}

            {m && (
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head">
                  <span className="card-title">Measured over every quote with history</span>
                  <span className="card-meta">
                    {m.n} quotes, {m.measured_on}, on {m.engine_build} ·{" "}
                    <span className="mono">./do price-eval</span>
                  </span>
                </div>
                <div style={{ padding: 14 }}>
                  <div className="kpi-row" style={{ marginBottom: 12 }}>
                    <div className="kpi" style={{ background: "var(--gold-light)", borderColor: "var(--gold)" }}>
                      <div className="kpi-label" style={{ color: "var(--gold-dark)" }}>Aito error</div>
                      <div className="kpi-val" style={{ color: "var(--gold-dark)" }}>{fmtPct(m.aito_error)}</div>
                      <div className="kpi-sub" style={{ color: "var(--gold-dark)" }}>mean |estimate − list| / list</div>
                    </div>
                    <div className="kpi">
                      <div className="kpi-label">Median error</div>
                      <div className="kpi-val">{fmtPct(m.median_error)}</div>
                      <div className="kpi-sub">product&apos;s own earlier median</div>
                    </div>
                    <div className="kpi">
                      <div className="kpi-label">Overcharges caught</div>
                      <div className="kpi-val">
                        {m.aito_caught}
                        <span style={{ fontSize: 14, color: "var(--mid)", fontWeight: 400 }}> / {m.overcharges}</span>
                      </div>
                      <div className="kpi-sub">Aito · {m.aito_flagged} flags raised</div>
                    </div>
                    <div className="kpi">
                      <div className="kpi-label">Overcharges caught</div>
                      <div className="kpi-val">
                        {m.median_caught}
                        <span style={{ fontSize: 14, color: "var(--mid)", fontWeight: 400 }}> / {m.overcharges}</span>
                      </div>
                      <div className="kpi-sub">median · {m.median_flagged} flags raised</div>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: "var(--ink)", lineHeight: 1.5 }}>{measuredSentence(m)}</div>
                  <div style={{ fontSize: 10.5, color: "var(--mid)", marginTop: 4 }}>
                    An overcharge is a quote more than {Math.round(m.overcharge_over_list * 100)}% over the
                    catalogue list price, as scored by <span className="mono">./do price-eval</span>.
                  </div>
                </div>
              </div>
            )}

            {data && data.products.length === 0 && (
              <div className="card" style={{ padding: 16 }}>
                The response carried no products with earlier prices, so there is nothing to score.
              </div>
            )}

            {data && data.products.length > 0 && (
              <>
                <div className="card" style={{ marginBottom: 16 }}>
                  <div className="card-head">
                    <span className="card-title">Products</span>
                    <span className="card-meta">history before {data.cutoff}</span>
                  </div>
                  <div style={{ overflowX: "auto" }}>
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>Product</th>
                          <th>Category</th>
                          <th style={{ textAlign: "right" }}>List price</th>
                          <th style={{ textAlign: "right" }}>Earlier prices</th>
                          <th style={{ textAlign: "right" }}>Quotes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.products.map((p) => (
                          <tr
                            key={p.sku}
                            className={`clickable${p.sku === selectedSku ? " selected" : ""}`}
                            onClick={() => {
                              setSelectedSku(p.sku);
                              setSelectedQuoteId(null);
                            }}
                          >
                            <td>
                              <div style={{ fontWeight: 600 }}>{p.name}</div>
                              <div className="mono" style={{ color: "var(--mid)" }}>{p.sku}</div>
                            </td>
                            <td>{p.category ?? "—"}</td>
                            <td className="mono" style={{ textAlign: "right" }}>
                              {p.list_price != null ? fmtPrice(p.list_price) : "—"}
                            </td>
                            <td className="mono" style={{ textAlign: "right" }}>{p.earlier_prices}</td>
                            <td style={{ textAlign: "right" }}>
                              {p.quotes.length}
                              {p.quotes.some((q) => q.flagged) && (
                                <span className="badge b-red" style={{ marginLeft: 6 }}>
                                  {p.quotes.filter((q) => q.flagged).length} flagged
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {product && (
                  <>
                    <div className="card" style={{ marginBottom: 16 }}>
                      <div className="card-head">
                        <span className="card-title">Where each quote lands</span>
                        <span className="card-meta">{product.name}</span>
                      </div>
                      <div style={{ padding: 14 }}>
                        <PriceStrip
                          product={product}
                          flagMargin={data.flag_margin}
                          selectedId={quote?.price_id ?? null}
                          onSelect={setSelectedQuoteId}
                        />
                      </div>
                    </div>

                    <div className="card">
                      <div className="card-head">
                        <span className="card-title">Incoming quotes</span>
                        <span className="card-meta">dated on or after {data.cutoff} · click a row for its query</span>
                      </div>
                      <div style={{ overflowX: "auto" }}>
                        <table className="tbl" style={{ minWidth: 640 }}>
                          <thead>
                            <tr>
                              <th>Date</th>
                              <th>Supplier</th>
                              <th style={{ textAlign: "right" }}>Volume</th>
                              <th style={{ textAlign: "right" }}>Quoted</th>
                              <th style={{ textAlign: "right" }}>Aito estimate</th>
                              <th style={{ textAlign: "right" }}>Earlier median</th>
                              <th style={{ textAlign: "right" }}>vs estimate</th>
                              <th>Flag</th>
                            </tr>
                          </thead>
                          <tbody>
                            {product.quotes.map((q) => (
                              <tr
                                key={q.price_id}
                                className={`clickable${q.price_id === quote?.price_id ? " selected" : ""}`}
                                onClick={() => setSelectedQuoteId(q.price_id)}
                              >
                                <td className="mono">{q.order_date}</td>
                                <td>{q.supplier}</td>
                                <td className="mono" style={{ textAlign: "right" }}>{q.volume}</td>
                                <td className="mono" style={{ textAlign: "right", fontWeight: 600 }}>{fmtPrice(q.quoted)}</td>
                                <td className="mono" style={{ textAlign: "right" }}>
                                  {fmtPrice(q.aito)}
                                  <div style={{ fontSize: 10, color: "var(--mid)" }}>{q.neighbours} earlier rows</div>
                                </td>
                                <td className="mono" style={{ textAlign: "right" }}>
                                  {q.median != null ? fmtPrice(q.median) : "—"}
                                  {q.median != null && (
                                    <div style={{ fontSize: 10, color: "var(--mid)" }}>
                                      quote {signedPct(((q.quoted - q.median) / q.median) * 100)}
                                    </div>
                                  )}
                                </td>
                                <td style={{ textAlign: "right" }}>
                                  <span className={`badge ${q.flagged ? "b-red" : q.deviation_pct > 0 ? "b-gold" : "b-green"}`}>
                                    {signedPct(q.deviation_pct)}
                                  </span>
                                </td>
                                <td>
                                  {q.flagged ? (
                                    <span className="badge b-red">review</span>
                                  ) : (
                                    <span className="badge b-gray">within {marginPct}%</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </>
                )}
              </>
            )}
          </div>

          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

/* ─── The range strip ────────────────────────────────────────────
   One row per quote on a shared price axis. Each row shows Aito's
   estimate (gold diamond), the flag line 15% above it, and the quote
   itself (red when flagged), joined by a segment so the gap reads at a
   glance. The list price and the earlier median are vertical lines —
   they belong to the product, not the quote — so a reader sees both
   yardsticks beside the estimate rather than the estimate alone. */

const W = 600;
const PAD_L = 12;
const PAD_R = 12;
const ROW_H = 46;
const TOP = 22;
const AXIS_H = 26;

function PriceStrip({
  product,
  flagMargin,
  selectedId,
  onSelect,
}: {
  product: PricingProduct;
  flagMargin: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const quotes = product.quotes;
  const medians = quotes.map((q) => q.median).filter((v): v is number => v != null);
  // The median is the product's own earlier median, identical on every
  // quote; if the backend ever sends differing values we draw each row's
  // own tick instead of pretending there is one line.
  const sharedMedian = medians.length > 0 && medians.every((v) => v === medians[0]) ? medians[0] : null;

  const values = [
    ...quotes.flatMap((q) => [q.quoted, q.aito, q.aito * (1 + flagMargin)]),
    ...medians,
    ...(product.list_price != null ? [product.list_price] : []),
  ];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.08 || hi * 0.05;
  const min = lo - pad;
  const max = hi + pad;
  const x = (v: number) => PAD_L + ((v - min) / (max - min)) * (W - PAD_L - PAD_R);

  const H = TOP + quotes.length * ROW_H + AXIS_H;
  const axisY = TOP + quotes.length * ROW_H;
  const ticks = Array.from({ length: 5 }, (_, i) => min + ((i + 0.5) / 5) * (max - min));

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`Quotes for ${product.name} against Aito's estimate, the earlier median and the list price`}
        style={{ display: "block", fontFamily: "'DM Sans', sans-serif" }}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={TOP - 6} y2={axisY} style={{ stroke: "var(--border)" }} strokeWidth={0.6} />
            <text x={x(t)} y={axisY + 16} textAnchor="middle" fontSize={10} style={{ fill: "var(--mid)", fontFamily: "'DM Mono', monospace" }}>
              €{t.toFixed(t < 20 ? 2 : 0)}
            </text>
          </g>
        ))}

        {product.list_price != null && (
          <g>
            <line x1={x(product.list_price)} x2={x(product.list_price)} y1={TOP - 6} y2={axisY}
              style={{ stroke: "var(--blue)" }} strokeWidth={1.5} strokeDasharray="5 3" />
            <text x={x(product.list_price)} y={TOP - 10} textAnchor="middle" fontSize={10} style={{ fill: "var(--blue)" }}>
              list
            </text>
          </g>
        )}
        {sharedMedian != null && (
          <g>
            <line x1={x(sharedMedian)} x2={x(sharedMedian)} y1={TOP - 6} y2={axisY}
              style={{ stroke: "var(--mid)" }} strokeWidth={1.5} strokeDasharray="2 3" />
            <text x={x(sharedMedian)} y={TOP - 10} textAnchor="middle" fontSize={10} style={{ fill: "var(--mid)" }}>
              median
            </text>
          </g>
        )}

        {quotes.map((q, i) => {
          const y = TOP + i * ROW_H + ROW_H / 2 + 6;
          const selected = q.price_id === selectedId;
          const limit = q.aito * (1 + flagMargin);
          const quoteColour = q.flagged ? "var(--red)" : "var(--ink)";
          return (
            <g key={q.price_id} onClick={() => onSelect(q.price_id)} style={{ cursor: "pointer" }}>
              <rect x={0} y={TOP + i * ROW_H} width={W} height={ROW_H}
                style={{ fill: selected ? "var(--gold-light)" : "transparent" }} opacity={selected ? 0.6 : 1} />
              <text x={PAD_L} y={TOP + i * ROW_H + 13} fontSize={10.5} style={{ fill: "var(--mid)" }}>
                {q.order_date} · {q.supplier} · {q.volume} units
              </text>
              {sharedMedian == null && q.median != null && (
                <line x1={x(q.median)} x2={x(q.median)} y1={y - 7} y2={y + 7} style={{ stroke: "var(--mid)" }} strokeWidth={2} />
              )}
              <line x1={x(q.aito)} x2={x(q.quoted)} y1={y} y2={y} style={{ stroke: quoteColour }} strokeWidth={1.5} opacity={0.5} />
              <line x1={x(limit)} x2={x(limit)} y1={y - 8} y2={y + 8} style={{ stroke: "var(--red)" }} strokeWidth={1} strokeDasharray="2 2" />
              <rect x={x(q.aito) - 5} y={y - 5} width={10} height={10} transform={`rotate(45 ${x(q.aito)} ${y})`}
                style={{ fill: "var(--gold)", stroke: "var(--gold-dark)" }} strokeWidth={1} />
              <circle cx={x(q.quoted)} cy={y} r={q.flagged ? 6.5 : 5}
                style={{ fill: q.flagged ? "var(--red)" : "var(--card)", stroke: quoteColour }} strokeWidth={2} />
            </g>
          );
        })}

        <line x1={PAD_L} x2={W - PAD_R} y1={axisY} y2={axisY} style={{ stroke: "var(--border)" }} />
      </svg>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 8, fontSize: 10.5, color: "var(--mid)" }}>
        <LegendItem swatch={<span style={{ width: 8, height: 8, background: "var(--gold)", transform: "rotate(45deg)", display: "inline-block" }} />}>
          Aito estimate
        </LegendItem>
        <LegendItem swatch={<span style={{ width: 9, height: 9, borderRadius: "50%", border: "2px solid var(--ink)", display: "inline-block" }} />}>
          Quote
        </LegendItem>
        <LegendItem swatch={<span style={{ width: 9, height: 9, borderRadius: "50%", background: "var(--red)", display: "inline-block" }} />}>
          Flagged quote
        </LegendItem>
        <LegendItem swatch={<span style={{ width: 0, height: 12, borderLeft: "1px dashed var(--red)", display: "inline-block" }} />}>
          Flag line (+{Math.round(flagMargin * 100)}%)
        </LegendItem>
        <LegendItem swatch={<span style={{ width: 0, height: 12, borderLeft: "2px dotted var(--mid)", display: "inline-block" }} />}>
          Earlier median
        </LegendItem>
        <LegendItem swatch={<span style={{ width: 0, height: 12, borderLeft: "2px dashed var(--blue)", display: "inline-block" }} />}>
          List price
        </LegendItem>
      </div>
    </div>
  );
}

function LegendItem({ swatch, children }: { swatch: ReactNode; children: ReactNode }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      {swatch}
      {children}
    </span>
  );
}

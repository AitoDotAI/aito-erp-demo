"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import type { PricingResponse, PricingProduct, PriceEstimate, QuoteScore, AitoPanelConfig } from "@/lib/types";

const defaultPanel: AitoPanelConfig = {
  operation: "_estimate",
  endpoints: ["_search"],
  stats: [
    { label: "Quotes/mo", value: "38" },
    { label: "Flagged", value: "4" },
    { label: "Accuracy", value: "87%" },
  ],
  description:
    "aito.._estimate scores incoming quotes against <em>historical purchase data</em>. It learns fair price ranges from past orders, similar products, and volume tiers &mdash; flagging quotes that deviate beyond the expected range. No pricing rules needed.",
  query: `<span class="q-k">POST</span> <span class="q-v">/api/v1/_estimate</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"purchase_orders"</span>,\n  <span class="q-k">"where"</span>: {\n    <span class="q-k">"product"</span>: <span class="q-v">"Industrial Relay"</span>,\n    <span class="q-k">"volume"</span>: <span class="q-n">100</span>\n  },\n  <span class="q-k">"estimate"</span>: <span class="q-p">"unit_price"</span>\n}`,
  links: [
    { label: "aito.ai/docs/estimate", url: "https://aito.ai/docs/api/estimate" },
  ],
};

export default function PricingPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<PricingResponse | null>(null);
  const [selectedProduct, setSelectedProduct] = useState<string | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);
  const [bannerOpen, setBannerOpen] = useState(true);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    apiFetch<PricingResponse>("/api/pricing/estimate")
      .then((res) => {
        setData(res);
        const keys = Object.keys(res.products);
        if (keys.length > 0) setSelectedProduct(keys[0]);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const currentProduct: PricingProduct | null = selectedProduct && data ? data.products[selectedProduct] ?? null : null;

  useEffect(() => {
    if (!currentProduct) return;
    const est = currentProduct.estimate;
    setPanel({
      ...defaultPanel,
      stats: [
        { label: "Fair price", value: fmtAmount(est.estimated_price) },
        { label: "Range", value: `${fmtAmount(est.range_low)} - ${fmtAmount(est.range_high)}` },
        { label: "Confidence", value: est.confidence != null ? `${Math.round(est.confidence * 100)}%` : "—" },
      ],
      query: `<span class="q-k">POST</span> <span class="q-v">/api/v1/_estimate</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"purchase_orders"</span>,\n  <span class="q-k">"where"</span>: {\n    <span class="q-k">"product"</span>: <span class="q-v">"${currentProduct.name}"</span>\n  },\n  <span class="q-k">"estimate"</span>: <span class="q-p">"unit_price"</span>\n}`,
    });
  }, [currentProduct]);

  const drawChart = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !currentProduct) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const est = currentProduct.estimate;
    const quotes = currentProduct.quotes;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;

    ctx.clearRect(0, 0, W, H);

    const ml = 50, mr = 20, mt = 20, mb = 40;
    const cw = W - ml - mr;
    const ch = H - mt - mb;

    const allPrices = [
      ...quotes.map((q) => q.quoted_price),
      est.range_low,
      est.range_high,
      est.price_min,
      est.price_max,
    ];
    const pMin = Math.min(...allPrices) * 0.9;
    const pMax = Math.max(...allPrices) * 1.1;

    const xScale = (price: number) => ml + ((price - pMin) / (pMax - pMin)) * cw;

    // Gold band for predicted range
    const x1 = xScale(est.range_low);
    const x2 = xScale(est.range_high);
    ctx.fillStyle = "rgba(212, 160, 48, 0.12)";
    ctx.fillRect(x1, mt, x2 - x1, ch);

    // Gold dashed lines
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = "rgba(212, 160, 48, 0.6)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x1, mt);
    ctx.lineTo(x1, mt + ch);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x2, mt);
    ctx.lineTo(x2, mt + ch);
    ctx.stroke();
    ctx.setLineDash([]);

    // Axes
    ctx.strokeStyle = "#ddd8cc";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(ml, mt + ch);
    ctx.lineTo(ml + cw, mt + ch);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(ml, mt);
    ctx.lineTo(ml, mt + ch);
    ctx.stroke();

    // X-axis labels
    ctx.fillStyle = "#5a5a4a";
    ctx.font = "10px 'DM Mono', monospace";
    ctx.textAlign = "center";
    const steps = 5;
    for (let i = 0; i <= steps; i++) {
      const p = pMin + (i / steps) * (pMax - pMin);
      const x = xScale(p);
      ctx.fillText(`\u20AC${p.toFixed(0)}`, x, mt + ch + 16);
      ctx.strokeStyle = "#f0ede6";
      ctx.beginPath();
      ctx.moveTo(x, mt);
      ctx.lineTo(x, mt + ch);
      ctx.stroke();
    }

    // Plot quotes
    quotes.forEach((q, i) => {
      const y = mt + (i + 1) * (ch / (quotes.length + 1));
      const x = xScale(q.quoted_price);
      const isFlagged = q.flagged;
      ctx.beginPath();
      ctx.arc(x, y, isFlagged ? 7 : 5, 0, Math.PI * 2);
      ctx.fillStyle = isFlagged ? "rgba(192, 57, 43, 0.8)" : "rgba(70, 130, 180, 0.6)";
      ctx.fill();
      ctx.strokeStyle = isFlagged ? "#c0392b" : "rgba(50, 100, 150, 0.5)";
      ctx.lineWidth = isFlagged ? 2 : 1;
      ctx.stroke();

      if (isFlagged) {
        ctx.fillStyle = "#c0392b";
        ctx.font = "bold 12px 'DM Sans', sans-serif";
        ctx.textAlign = "left";
        ctx.fillText("\u26A0", x + 10, y + 4);
        ctx.font = "9px 'DM Sans', sans-serif";
        ctx.fillText(q.supplier, x + 22, y + 4);
      }
    });

    // Predicted mean line
    const xMean = xScale(est.estimated_price);
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = "rgba(212, 160, 48, 1)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(xMean, mt);
    ctx.lineTo(xMean, mt + ch);
    ctx.stroke();
    ctx.setLineDash([]);
  }, [currentProduct]);

  useEffect(() => {
    drawChart();
    window.addEventListener("resize", drawChart);
    return () => window.removeEventListener("resize", drawChart);
  }, [drawChart]);

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

  const productKeys = data ? Object.keys(data.products) : [];
  const flaggedCount = currentProduct?.quotes.filter(q => q.flagged).length ?? 0;

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar
          title="Price Intelligence"
          breadcrumb="Product"
          kpis={[{ icon: "\uD83D\uDCB0", label: `${flaggedCount} flagged` }]}
        />
        <div className="content-area">
          <div className="content">
            {bannerOpen && (
              <div className="intro-banner">
                <div className="intro-banner-text">
                  <strong>Every quote scored against historical data.</strong> aito.._estimate learns fair price ranges from past orders and similar products. Quotes outside the predicted range are flagged for review &mdash; saving an average of &euro;1,240 per flagged quote.
                </div>
                <span className="intro-banner-close" onClick={() => setBannerOpen(false)}>&times;</span>
              </div>
            )}

            <div className="kpi-row">
              <div className="kpi">
                <div className="kpi-label">PPV (Avg)</div>
                <div className="kpi-val" style={{ color: (data?.ppv?.overall_pct ?? 0) > 0 ? "var(--red)" : "var(--green)" }}>
                  {data?.ppv?.overall_pct != null
                    ? (data.ppv.overall_pct > 0 ? "+" : "") + data.ppv.overall_pct + "%"
                    : "—"}
                </div>
                <div className="kpi-sub">price variance vs estimate</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Flagged Quotes</div>
                <div className="kpi-val" style={{ color: "var(--red)" }}>
                  {data?.ppv?.flagged_quotes ?? flaggedCount}
                  <span style={{ fontSize: 14, color: "var(--mid)", fontWeight: 400 }}>
                    /{data?.ppv?.total_quotes ?? "?"}
                  </span>
                </div>
                <div className="kpi-sub">&gt;20% above estimate</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Overpayment Caught</div>
                <div className="kpi-val" style={{ color: "var(--red)" }}>
                  {data?.ppv?.total_overpayment_eur != null
                    ? fmtAmount(data.ppv.total_overpayment_eur)
                    : "—"}
                </div>
                <div className="kpi-sub">across flagged quotes</div>
              </div>
              <div className="kpi" style={{ background: "var(--gold-light)", borderColor: "var(--gold)" }}>
                <div className="kpi-label" style={{ color: "var(--gold-dark)" }}>Annualized Risk</div>
                <div className="kpi-val" style={{ color: "var(--gold-dark)" }}>
                  {data?.ppv?.annualized_overpayment_eur != null
                    ? fmtAmount(data.ppv.annualized_overpayment_eur)
                    : "—"}
                </div>
                <div className="kpi-sub" style={{ color: "var(--gold-dark)" }}>if no quote scoring</div>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 16 }}>
              {/* Left column - selectors and quotes */}
              <div>
                <div className="card" style={{ marginBottom: 12 }}>
                  <div style={{ padding: 14 }}>
                    <div className="form-group" style={{ marginBottom: 10 }}>
                      <label className="form-label">Product</label>
                      <select className="form-select" value={selectedProduct ?? ""} onChange={(e) => setSelectedProduct(e.target.value)}>
                        {productKeys.map((key) => <option key={key} value={key}>{data!.products[key].name}</option>)}
                      </select>
                    </div>
                  </div>
                </div>

                {currentProduct && (
                  <>
                    <div className="card" style={{ marginBottom: 12, background: "var(--gold-light)", borderColor: "var(--gold)" }}>
                      <div style={{ padding: 14 }}>
                        <div style={{ fontSize: 9.5, fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--gold-dark)", marginBottom: 6 }}>Predicted Fair Price</div>
                        <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 24, color: "var(--gold-dark)" }}>{fmtAmount(currentProduct.estimate.estimated_price)}</div>
                        <div style={{ fontSize: 10.5, color: "var(--gold-dark)", marginTop: 4 }}>
                          Range: {fmtAmount(currentProduct.estimate.range_low)} &ndash; {fmtAmount(currentProduct.estimate.range_high)}
                        </div>
                      </div>
                    </div>

                    <div className="card">
                      <div className="card-head">
                        <span className="card-title">Incoming Quotes</span>
                      </div>
                      <table className="tbl">
                        <thead>
                          <tr>
                            <th>Supplier</th>
                            <th>Quote</th>
                            <th>vs Est.</th>
                          </tr>
                        </thead>
                        <tbody>
                          {currentProduct.quotes.map((q) => (
                            <tr key={q.supplier} className="clickable">
                              <td style={{ fontSize: 11 }}>{q.supplier}</td>
                              <td className="mono">{fmtAmount(q.quoted_price)}</td>
                              <td>
                                <span className={`badge ${q.deviation_pct > 0 ? "b-red" : "b-green"}`}>
                                  {q.deviation_pct > 0 ? "+" : ""}{q.deviation_pct.toFixed(1)}%
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>

              {/* Right column - chart */}
              <div className="card">
                <div className="card-head">
                  <span className="card-title">Price Distribution</span>
                  <span className="card-meta">{currentProduct?.name ?? ""}</span>
                </div>
                <div style={{ padding: 16 }}>
                  <canvas
                    ref={canvasRef}
                    style={{ width: "100%", height: 280, display: "block" }}
                  />
                  <div style={{ display: "flex", gap: 16, marginTop: 12, flexWrap: "wrap" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10, color: "var(--mid)" }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: "rgba(70, 130, 180, 0.8)", display: "inline-block" }} />
                      Quotes
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10, color: "var(--mid)" }}>
                      <span style={{ width: 16, height: 8, borderRadius: 2, background: "rgba(212, 160, 48, 0.25)", border: "1px dashed var(--gold)", display: "inline-block" }} />
                      Predicted range
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10, color: "var(--mid)" }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#c0392b", display: "inline-block" }} />
                      Flagged quote
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

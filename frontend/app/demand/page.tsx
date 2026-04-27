"use client";

import { useState, useEffect } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import type { DemandResponse, DemandForecast, AitoPanelConfig } from "@/lib/types";

const defaultPanel: AitoPanelConfig = {
  operation: "_estimate",
  stats: [
    { label: "Tracked", value: "—" },
    { label: "Accuracy", value: "—" },
    { label: "Alerts", value: "—" },
  ],
  description:
    "Same purchase order data, different question. aito.._estimate predicts <em>future demand</em> from historical order patterns. aito.._relate discovers <em>seasonality</em> and <em>demand drivers</em> automatically &mdash; no manual feature engineering.",
  query: `<span class="q-k">POST</span> <span class="q-v">/api/v1/_estimate</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"purchase_orders"</span>,\n  <span class="q-k">"where"</span>: {\n    <span class="q-k">"product"</span>: <span class="q-v">"*"</span>,\n    <span class="q-k">"period"</span>: <span class="q-v">"next_30d"</span>\n  },\n  <span class="q-k">"estimate"</span>: <span class="q-p">"quantity"</span>\n}`,
  links: [
    { label: "aito.ai/docs/estimate", url: "https://aito.ai/docs/api/estimate" },
    { label: "aito.ai/docs/relate", url: "https://aito.ai/docs/api/relate" },
  ],
};

export default function DemandPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DemandResponse | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);
  const [bannerOpen, setBannerOpen] = useState(true);

  useEffect(() => {
    apiFetch<DemandResponse>("/api/demand/forecast")
      .then((res) => setData(res))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const forecasts = data?.forecasts ?? [];

  useEffect(() => {
    if (forecasts.length === 0) return;
    const trendingUp = forecasts.filter((f) => f.trend === "up").length;
    const avgConf = forecasts.reduce((acc, f) => acc + f.confidence, 0) / forecasts.length;
    setPanel({
      ...defaultPanel,
      stats: [
        { label: "Tracked", value: String(forecasts.length) },
        { label: "Avg conf.", value: `${Math.round(avgConf * 100)}%` },
        { label: "Trending up", value: String(trendingUp) },
      ],
    });
  }, [forecasts.length]);

  const handleRowClick = (idx: number) => {
    const f = forecasts[idx];
    setSelected(idx);
    setPanel({
      operation: "_estimate",
      stats: [
        { label: "Forecast", value: String(f.forecast) },
        { label: "Baseline", value: String(f.baseline) },
        { label: "Confidence", value: `${Math.round(f.confidence * 100)}%` },
      ],
      description: `<strong>${f.product_name}</strong> (${f.product_id})<br/><br/>Forecast: <em>${f.forecast} units</em> (baseline: ${f.baseline}).<br/><br/>Trend: ${f.trend === "up" ? "Increasing" : f.trend === "down" ? "Decreasing" : "Stable"}.`,
      query: `<span class="q-k">POST</span> <span class="q-v">/api/v1/_estimate</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"purchase_orders"</span>,\n  <span class="q-k">"where"</span>: {\n    <span class="q-k">"product"</span>: <span class="q-v">"${f.product_id}"</span>\n  },\n  <span class="q-k">"estimate"</span>: <span class="q-p">"quantity"</span>\n}`,
      links: [
        { label: "aito.ai/docs/estimate", url: "https://aito.ai/docs/api/estimate" },
      ],
    });
  };

  const trendBadge = (trend: "up" | "down" | "stable", baseline: number, forecast: number) => {
    const pct = baseline > 0 ? Math.round(((forecast - baseline) / baseline) * 100) : 0;
    if (trend === "up") return <span className="badge b-red">{"\u2191"} +{pct}%</span>;
    if (trend === "down") return <span className="badge b-green">{"\u2193"} {pct}%</span>;
    return <span className="badge b-gray">{"\u2192"} {pct > 0 ? "+" : ""}{pct}%</span>;
  };

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

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar
          title="Demand Forecast"
          breadcrumb="Product"
          kpis={[{ icon: "\uD83D\uDCC8", label: `${forecasts.length} products` }]}
        />
        <div className="content-area">
          <div className="content">
            {bannerOpen && (
              <div className="intro-banner">
                <div className="intro-banner-text">
                  <strong>Same data, different question.</strong> Your purchase order history already contains demand signals. aito.. extracts forecasts, discovers seasonality, and identifies demand drivers &mdash; all from the data you already have.
                </div>
                <span className="intro-banner-close" onClick={() => setBannerOpen(false)}>&times;</span>
              </div>
            )}

            <div className="kpi-row">
              <div className="kpi">
                <div className="kpi-label">Stockouts Prevented</div>
                <div className="kpi-val" style={{ color: "var(--green)" }}>
                  {data?.impact?.stockouts_prevented_eur != null
                    ? fmtAmount(data.impact.stockouts_prevented_eur)
                    : "—"}
                </div>
                <div className="kpi-sub">{data?.impact?.spikes_predicted ?? 0} spikes predicted × €800</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Excess Avoided</div>
                <div className="kpi-val" style={{ color: "var(--blue)" }}>
                  {data?.impact?.excess_prevented_eur != null
                    ? fmtAmount(data.impact.excess_prevented_eur)
                    : "—"}
                </div>
                <div className="kpi-sub">{data?.impact?.drops_predicted ?? 0} drops predicted × €400</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">High-Confidence</div>
                <div className="kpi-val">{data?.impact?.high_confidence_count ?? 0}<span style={{ fontSize: 14, color: "var(--mid)", fontWeight: 400 }}>/{forecasts.length}</span></div>
                <div className="kpi-sub">forecasts ≥70% confidence</div>
              </div>
              <div className="kpi" style={{ background: "var(--gold-light)", borderColor: "var(--gold)" }}>
                <div className="kpi-label" style={{ color: "var(--gold-dark)" }}>Total Impact</div>
                <div className="kpi-val" style={{ color: "var(--gold-dark)" }}>
                  {data?.impact?.total_impact_eur != null
                    ? fmtAmount(data.impact.total_impact_eur)
                    : "—"}
                </div>
                <div className="kpi-sub" style={{ color: "var(--gold-dark)" }}>{data?.month ?? ""} forecast cycle</div>
              </div>
            </div>

            <div className="card" style={{ marginBottom: 16 }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Product ID</th>
                    <th>Product</th>
                    <th>Baseline</th>
                    <th>Forecast</th>
                    <th>Trend</th>
                    <th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasts.map((f, i) => (
                    <tr key={f.product_id} className={`clickable${selected === i ? " selected" : ""}`} onClick={() => handleRowClick(i)}>
                      <td className="mono">{f.product_id}</td>
                      <td>{f.product_name}</td>
                      <td className="mono">{f.baseline}</td>
                      <td className="mono" style={{ fontWeight: 600 }}>{f.forecast}</td>
                      <td>{trendBadge(f.trend, f.baseline, f.forecast)}</td>
                      <td>
                        <div className={`conf ${confClass(f.confidence)}`}>
                          <div className="conf-track">
                            <div className="conf-fill" style={{ width: `${f.confidence * 100}%` }} />
                          </div>
                          <span className="conf-val">{Math.round(f.confidence * 100)}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {forecasts.length === 0 && !loading && (
                    <tr>
                      <td colSpan={6} style={{ textAlign: "center", color: "var(--mid)", padding: 32 }}>
                        No forecast data available
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

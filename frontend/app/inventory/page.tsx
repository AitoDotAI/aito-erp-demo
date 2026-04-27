"use client";

import { useState, useEffect } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import type { InventoryResponse, InventoryItem, AitoPanelConfig } from "@/lib/types";

const defaultPanel: AitoPanelConfig = {
  operation: "_estimate + _relate",
  stats: [
    { label: "Critical", value: "—" },
    { label: "Low", value: "—" },
    { label: "Overstock", value: "—" },
  ],
  description:
    "Demand forecast meets stock levels. aito.._estimate predicts <em>demand per product</em>, then compares against current inventory and lead times to flag stockout risks. aito.._relate finds <em>substitution candidates</em> when primary stock runs low.",
  query: `<span class="q-k">POST</span> <span class="q-v">/api/v1/_estimate</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"inventory"</span>,\n  <span class="q-k">"where"</span>: { <span class="q-k">"status"</span>: <span class="q-v">"active"</span> },\n  <span class="q-k">"estimate"</span>: <span class="q-p">"days_of_supply"</span>\n}\n\n<span class="q-d">// Then for low-stock items:</span>\n<span class="q-k">POST</span> <span class="q-v">/api/v1/_relate</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"products"</span>,\n  <span class="q-k">"where"</span>: { <span class="q-k">"category"</span>: <span class="q-v">"same"</span> },\n  <span class="q-k">"relate"</span>: <span class="q-p">"substitution"</span>\n}`,
  links: [
    { label: "aito.ai/docs/estimate", url: "https://aito.ai/docs/api/estimate" },
    { label: "aito.ai/docs/relate", url: "https://aito.ai/docs/api/relate" },
  ],
};

export default function InventoryPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<InventoryResponse | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);
  const [bannerOpen, setBannerOpen] = useState(true);

  useEffect(() => {
    apiFetch<InventoryResponse>("/api/inventory/status")
      .then((res) => setData(res))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const items = data?.items ?? [];
  const [reordering, setReordering] = useState<string | null>(null);
  const [reordered, setReordered] = useState<Record<string, string>>({});

  const supplierFor = (productId: string): string => {
    const map: Record<string, string> = {
      "SKU-4421": "Wärtsilä Components",
      "SKU-FUEL": "Neste Oyj",
      "SKU-2234": "Lindström Oy",
      "SKU-HVAC": "Caverion Suomi",
      "SKU-5560": "Fazer Food Services",
      "SKU-9901": "Generic Supplier",
    };
    return map[productId] ?? "Generic Supplier";
  };

  const priceFor = (productId: string): number => {
    const map: Record<string, number> = {
      "SKU-4421": 148, "SKU-FUEL": 94, "SKU-2234": 89,
      "SKU-HVAC": 82, "SKU-5560": 25, "SKU-9901": 3.4,
    };
    return map[productId] ?? 50;
  };

  const handleReorder = async (item: InventoryItem) => {
    setReordering(item.product_id);
    try {
      const reorderQty = Math.max(
        Math.ceil(item.daily_demand * (item.lead_time_days + 14)),
        Math.ceil(item.forecast_units),
      );
      const amount = reorderQty * priceFor(item.product_id);
      const res = await apiFetch<{ purchase_id: string }>("/api/po/submit", {
        method: "POST",
        body: JSON.stringify({
          supplier: supplierFor(item.product_id),
          description: `Reorder ${reorderQty}× ${item.product_name}`,
          amount_eur: Math.round(amount * 100) / 100,
          category: "reorder",
          source: "inventory_reorder",
        }),
      });
      setReordered((prev) => ({ ...prev, [item.product_id]: res.purchase_id }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setReordering(null);
    }
  };

  useEffect(() => {
    if (!data) return;
    setPanel({
      ...defaultPanel,
      stats: [
        { label: "Critical", value: String(data.critical_count) },
        { label: "Low", value: String(data.low_count) },
        { label: "Overstock", value: String(data.overstock_count) },
      ],
    });
  }, [data]);

  const handleRowClick = (idx: number) => {
    const item = items[idx];
    setSelected(idx);
    const subText = item.substitutions?.length
      ? `<br/><br/>Substitution available: <em>${item.substitutions[0].name}</em> (${Math.round(item.substitutions[0].similarity * 100)}% similarity)`
      : "";
    setPanel({
      operation: "_estimate",
      stats: [
        { label: "In stock", value: String(item.stock_on_hand) },
        { label: "Daily demand", value: String(item.daily_demand) },
        { label: "Days supply", value: String(item.days_of_supply) },
      ],
      description: `<strong>${item.product_name}</strong> (${item.product_id})<br/><br/>Current stock: <em>${item.stock_on_hand}</em><br/>Daily demand: <em>${item.daily_demand}</em><br/>Days of supply: <em>${item.days_of_supply} days</em><br/>Lead time: <em>${item.lead_time_days} days</em><br/>Forecast units: <em>${item.forecast_units}</em>${subText}`,
      query: `<span class="q-k">POST</span> <span class="q-v">/api/v1/_estimate</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"inventory"</span>,\n  <span class="q-k">"where"</span>: { <span class="q-k">"product_id"</span>: <span class="q-v">"${item.product_id}"</span> },\n  <span class="q-k">"estimate"</span>: <span class="q-p">"days_of_supply"</span>\n}\n\n<span class="q-d">// Stockout math:</span>\n<span class="q-d">// ${item.stock_on_hand} units / ${item.daily_demand} per day</span>\n<span class="q-d">// = ${item.days_of_supply} days of supply</span>\n<span class="q-d">// Lead time: ${item.lead_time_days} days</span>`,
      links: [
        { label: "aito.ai/docs/estimate", url: "https://aito.ai/docs/api/estimate" },
      ],
    });
  };

  const statusBadge = (status: string) => {
    switch (status) {
      case "critical": return <span className="badge b-red">Critical</span>;
      case "low": return <span className="badge b-gold">Low</span>;
      case "ok": return <span className="badge b-green">OK</span>;
      case "overstock": return <span className="badge b-blue">Overstock</span>;
      default: return <span className="badge b-gray">{status}</span>;
    }
  };

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
          title="Inventory Intelligence"
          breadcrumb="Product"
          kpis={[{ icon: "\uD83C\uDFD7\uFE0F", label: `${data?.critical_count ?? 0} critical` }]}
        />
        <div className="content-area">
          <div className="content">
            {bannerOpen && (
              <div className="intro-banner">
                <div className="intro-banner-text">
                  <strong>Demand forecast meets stock levels.</strong> aito.. combines predicted demand with current inventory and supplier lead times to flag stockout risks before they happen &mdash; and suggests substitutes when primary items run low.
                </div>
                <span className="intro-banner-close" onClick={() => setBannerOpen(false)}>&times;</span>
              </div>
            )}

            <div className="kpi-row">
              <div className="kpi">
                <div className="kpi-label">Critical Stockouts</div>
                <div className="kpi-val" style={{ color: "var(--red)" }}>{data?.critical_count ?? 0}</div>
                <div className="kpi-sub">{fmtAmount(data?.total_stockout_risk_eur ?? 0)} weekly margin at risk</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Low Stock</div>
                <div className="kpi-val" style={{ color: "var(--gold)" }}>{data?.low_count ?? 0}</div>
                <div className="kpi-sub">items need attention</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Overstock Items</div>
                <div className="kpi-val">{data?.overstock_count ?? 0}</div>
                <div className="kpi-sub">&gt;90 days supply</div>
              </div>
              <div className="kpi" style={{ background: "var(--gold-light)", borderColor: "var(--gold)" }}>
                <div className="kpi-label" style={{ color: "var(--gold-dark)" }}>Capital Recoverable</div>
                <div className="kpi-val" style={{ color: "var(--gold-dark)" }}>{fmtAmount(data?.target_freed_eur ?? 0)}</div>
                <div className="kpi-sub" style={{ color: "var(--gold-dark)" }}>by reducing overstock to 60d target</div>
              </div>
            </div>

            <div className="card" style={{ marginBottom: 16 }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Product ID</th>
                    <th>Product</th>
                    <th>In Stock</th>
                    <th>Daily Demand</th>
                    <th>Days Supply</th>
                    <th>Lead Time</th>
                    <th>Status</th>
                    <th>Cash Impact</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, i) => (
                    <tr key={item.product_id} className={`clickable${selected === i ? " selected" : ""}`} onClick={() => handleRowClick(i)}>
                      <td className="mono">{item.product_id}</td>
                      <td>{item.product_name}</td>
                      <td className="mono">{item.stock_on_hand}</td>
                      <td className="mono">{item.daily_demand}</td>
                      <td>
                        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, fontWeight: 700, color: item.days_of_supply <= 5 ? "var(--red)" : item.days_of_supply <= 14 ? "var(--gold-dark)" : "var(--ink)" }}>
                          {item.days_of_supply}d
                        </span>
                      </td>
                      <td className="mono">{item.lead_time_days}d</td>
                      <td>{statusBadge(item.status)}</td>
                      <td>
                        {item.status === "overstock" && (item.tied_capital_eur ?? 0) > 0 ? (
                          <span style={{ color: "var(--blue)", fontWeight: 600, fontSize: 11 }}>
                            {fmtAmount(item.tied_capital_eur ?? 0)} tied
                          </span>
                        ) : item.status === "critical" && (item.stockout_risk_eur ?? 0) > 0 ? (
                          <span style={{ color: "var(--red)", fontWeight: 600, fontSize: 11 }}>
                            {fmtAmount(item.stockout_risk_eur ?? 0)}/wk at risk
                          </span>
                        ) : (
                          <span style={{ color: "var(--mid)", fontSize: 11 }}>—</span>
                        )}
                      </td>
                      <td>
                        {reordered[item.product_id] ? (
                          <span style={{ fontSize: 11, color: "var(--green)" }}>
                            ✓ {reordered[item.product_id]}
                          </span>
                        ) : (item.status === "critical" || item.status === "low") ? (
                          <button
                            className="btn btn-primary"
                            style={{ fontSize: 10.5, padding: "4px 10px" }}
                            disabled={reordering === item.product_id}
                            onClick={(e) => { e.stopPropagation(); handleReorder(item); }}
                          >
                            {reordering === item.product_id ? "..." : "Reorder now"}
                          </button>
                        ) : (
                          <span style={{ fontSize: 11, color: "var(--mid)" }}>—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {items.length === 0 && !loading && (
                    <tr>
                      <td colSpan={9} style={{ textAlign: "center", color: "var(--mid)", padding: 32 }}>
                        No inventory data available
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

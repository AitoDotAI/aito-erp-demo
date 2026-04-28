"use client";

import { useEffect, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { supplierPanel } from "@/lib/panel-content";
import type { SupplierResponse, SupplierSpend, DeliveryRisk, AitoPanelConfig } from "@/lib/types";

export default function SupplierPage() {
  const { tenantId } = useTenant();
  const defaultPanel = supplierPanel(tenantId);
  const [data, setData] = useState<SupplierResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);

  const [selectedSpend, setSelectedSpend] = useState<string | null>(null);
  const [selectedRisk, setSelectedRisk] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<SupplierResponse>("/api/supplier/overview")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Re-tone whenever data loads OR the tenant changes — the persona
  // description swaps to the new industry, but live stats (suppliers,
  // risk counts) are preserved from the loaded data.
  useEffect(() => {
    const base = supplierPanel(tenantId);
    if (!data) {
      setPanel(base);
      return;
    }
    const high = data.delivery_risks.filter((r) => r.risk_level === "high").length;
    setPanel({
      ...base,
      stats: [
        { label: "Suppliers", value: String(data.top_suppliers.length) },
        { label: "Risk factors", value: String(data.delivery_risks.length) },
        { label: "High risk", value: String(high) },
      ],
    });
  }, [data, tenantId]);

  const handleSpendClick = (item: SupplierSpend) => {
    setSelectedSpend(item.supplier);
    setSelectedRisk(null);
    setPanel({
      operation: "_relate",
      stats: [
        { label: "Spend", value: fmtAmount(item.total_amount) },
        { label: "POs", value: `${item.po_count}` },
        { label: "Avg", value: fmtAmount(item.avg_amount) },
      ],
      description:
        `Supplier profile for <em>${item.supplier}</em>. Total spend: <em>${fmtAmount(item.total_amount)}</em> ` +
        `across <em>${item.po_count}</em> orders. Average order: <em>${fmtAmount(item.avg_amount)}</em>. ` +
        `Categories: <em>${item.categories.join(", ")}</em>.`,
      query: `<span class="q-k">POST</span> /api/v1/_relate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchase_orders"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>: <span class="q-v">"${item.supplier}"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"relate"</span>: [<span class="q-p">"on_time"</span>, <span class="q-p">"delivery_days"</span>]<br/>
}`,
      links: [
        { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
      ],
    });
  };

  const handleRiskClick = (item: DeliveryRisk) => {
    setSelectedRisk(item.supplier);
    setSelectedSpend(null);
    setPanel({
      operation: "_relate",
      stats: [
        { label: "Supplier", value: item.supplier },
        { label: "Lift", value: `${item.lift.toFixed(1)}x` },
        { label: "Risk", value: item.risk_level },
      ],
      description:
        `Delivery risk for <em>${item.supplier}</em>: risk level <em>${item.risk_level}</em>. ` +
        `Late rate: <em>${(item.late_rate * 100).toFixed(1)}%</em>. ` +
        `This factor has a lift of <em>${item.lift.toFixed(1)}x</em>, meaning it increases ` +
        `the probability of late delivery by ${item.lift.toFixed(1)} times.`,
      query: `<span class="q-k">POST</span> /api/v1/_relate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"deliveries"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>: <span class="q-v">"${item.supplier}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"on_time"</span>: <span class="q-n">false</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"relate"</span>: [<span class="q-p">"risk_factor"</span>]<br/>
}`,
      links: [
        { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
      ],
    });
  };

  const spend = data?.top_suppliers ?? [];
  const risks = data?.delivery_risks ?? [];

  return (
    <>
      <Nav />
      <main className="main">
        <TopBar
          breadcrumb="Intelligence"
          title="Supplier Intelligence"
          subtitle={`${spend.length} suppliers tracked`}
        />
        <div className="content-area">
          <div className="content">
            {loading && <p style={{ padding: 24, color: "var(--mid)" }}>Loading...</p>}
            {error && <ErrorState message={error} command="GET /api/supplier/overview" />}
            {data && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                <div className="card">
                  <div className="card-head">
                    <span className="card-title">Top Suppliers by Spend</span>
                    <span className="card-meta">{spend.length} suppliers</span>
                  </div>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Supplier</th>
                        <th>Spend</th>
                        <th>POs</th>
                        <th>Avg Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {spend.map((s) => (
                        <tr
                          key={s.supplier}
                          className={`clickable${selectedSpend === s.supplier ? " selected" : ""}`}
                          onClick={() => handleSpendClick(s)}
                        >
                          <td>{s.supplier}</td>
                          <td className="mono">{fmtAmount(s.total_amount)}</td>
                          <td>{s.po_count}</td>
                          <td className="mono">{fmtAmount(s.avg_amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="card">
                  <div className="card-head">
                    <span className="card-title">Predicted Delivery Risk</span>
                    <span className="card-meta">{risks.length} risk factors</span>
                  </div>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Supplier</th>
                        <th>Risk Level</th>
                        <th>Late Rate</th>
                        <th>Lift</th>
                      </tr>
                    </thead>
                    <tbody>
                      {risks.map((r, i) => (
                        <tr
                          key={`${r.supplier}-${i}`}
                          className={`clickable${selectedRisk === r.supplier ? " selected" : ""}`}
                          onClick={() => handleRiskClick(r)}
                        >
                          <td>{r.supplier}</td>
                          <td>
                            <span className={`badge ${r.lift >= 2 ? "b-red" : r.lift >= 1.5 ? "b-gold" : "b-green"}`}>
                              {r.risk_level}
                            </span>
                          </td>
                          <td className="mono">{(r.late_rate * 100).toFixed(1)}%</td>
                          <td className="mono">{r.lift.toFixed(1)}x</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </main>
    </>
  );
}

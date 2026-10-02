"use client";

import { useEffect, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import { readParam, writeParam } from "@/lib/url-state";
import { useTenant } from "@/lib/tenant-context";
import { supplierPanel } from "@/lib/panel-content";
import { findQuery } from "@/lib/query";
import type { SupplierResponse, SupplierSpend, DeliveryRisk, AitoPanelConfig } from "@/lib/types";

// The badge colour follows the backend's risk level, never its own
// reading of lift: a lift of 2.4 on one late delivery is "low", and a
// red badge saying "low" was the contradiction on screen. An unknown
// level renders uncoloured rather than borrowing a colour.
const RISK_BADGE: Record<string, string> = { high: "b-red", medium: "b-gold", low: "b-green" };

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
    setLoading(true);
    setError(null);
    apiFetch<SupplierResponse>("/api/supplier/overview")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

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
    // Rows arrive ranked by lift, so the first is the one to quote.
    const top = data.delivery_risks[0];
    setPanel({
      ...supplierPanel(tenantId, top, data._queries),
      stats: [
        { label: "Suppliers", value: String(data.top_suppliers.length) },
        { label: "Risk factors", value: String(data.delivery_risks.length) },
        { label: "High risk", value: String(high) },
      ],
    });
  }, [data, tenantId]);

  // A shared link opens with the same row selected: `?spend=` or `?risk=`
  // names the supplier, in whichever table the sender clicked it.
  useEffect(() => {
    if (!data) return;
    const spend = readParam("spend");
    const risk = readParam("risk");
    const spendRow = spend ? data.spend_overview?.find((s) => s.supplier === spend) : undefined;
    const riskRow = risk ? data.delivery_risks.find((r) => r.supplier === risk) : undefined;
    if (riskRow) handleRiskClick(riskRow);
    else if (spendRow) handleSpendClick(spendRow);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const handleSpendClick = (item: SupplierSpend) => {
    setSelectedSpend(item.supplier);
    setSelectedRisk(null);
    writeParam("spend", item.supplier);
    writeParam("risk", null);
    // Spend is not an Aito inference: one `_search` reads the purchase
    // history and the totals are summed in src/supplier_service.py.
    const read = findQuery(data?._queries, { endpoint: "_search", from: "purchases" });
    setPanel({
      operation: "_search",
      endpoints: ["_search"],
      stats: [
        { label: "Spend", value: fmtAmount(item.total_amount) },
        { label: "POs", value: `${item.po_count}` },
        { label: "Avg", value: fmtAmount(item.avg_amount) },
      ],
      description:
        `Supplier profile for <em>${item.supplier}</em>. Total spend: <em>${fmtAmount(item.total_amount)}</em> ` +
        `across <em>${item.po_count}</em> orders. Average order: <em>${fmtAmount(item.avg_amount)}</em>. ` +
        `Categories: <em>${item.categories.join(", ")}</em>. ` +
        `These are plain sums: a <em>_search</em> reads the purchases and the ` +
        `backend groups them by supplier — no prediction involved.`,
      queries: read ? [read] : [],
      links: [
        { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/05-supplier-intel.md", kind: "doc" },
        { label: "Search API reference", url: "https://aito.ai/docs/api/search" },
      ],
    });
  };

  const handleRiskClick = (item: DeliveryRisk) => {
    setSelectedRisk(item.supplier);
    setSelectedSpend(null);
    writeParam("risk", item.supplier);
    writeParam("spend", null);
    // One `_relate` ranks every supplier; this row is one hit of it.
    const relate = findQuery(data?._queries, {
      endpoint: "_relate", from: "purchases", target: "supplier", where: { delivery_late: true },
    });
    setPanel({
      operation: "_relate",
      endpoints: ["_relate"],
      stats: [
        { label: "Supplier", value: item.supplier },
        { label: "Raw ratio", value: `${item.raw_lift.toFixed(1)}x` },
        { label: "Aito lift", value: `${item.lift.toFixed(1)}x` },
        { label: "Risk", value: item.risk_level },
      ],
      description:
        `Delivery risk for <em>${item.supplier}</em>: risk level <em>${item.risk_level}</em>. ` +
        `Late rate: <em>${(item.late_rate * 100).toFixed(1)}%</em> ` +
        `(${item.late_orders} of ${item.total_orders} deliveries), against ` +
        `${(item.base_late_rate * 100).toFixed(1)}% across all suppliers. ` +
        `That is <em>${item.raw_lift.toFixed(1)}x</em> the overall rate; Aito's lift is ` +
        `<em>${item.lift.toFixed(1)}x</em>. It is shrunk toward 1 when a supplier ` +
        `has few deliveries, so it can read lower than the raw ratio; that caution is ` +
        `what lets the risk level trust it. This row is one hit of the single ` +
        `<em>_relate</em> below, which ranks every supplier at once.`,
      queries: relate ? [relate] : [],
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
              <div className="split-2-col">
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
                        <th title="This supplier's late rate over the rate across all suppliers, from the counts">
                          Raw ratio
                        </th>
                        <th title="Aito's lift: the same ratio shrunk toward 1 when a supplier has few deliveries. The risk level is read from this one.">
                          Aito lift
                        </th>
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
                            <span className={`badge ${RISK_BADGE[r.risk_level] ?? ""}`}>
                              {r.risk_level}
                            </span>
                          </td>
                          <td className="mono">
                            {(r.late_rate * 100).toFixed(1)}%{" "}
                            <span className="pl-unknown">({r.late_orders} of {r.total_orders})</span>
                          </td>
                          <td className="mono">{r.raw_lift.toFixed(1)}x</td>
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

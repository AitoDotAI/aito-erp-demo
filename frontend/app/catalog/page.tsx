"use client";

import { useState, useEffect } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import type { CatalogResponse, IncompleteProduct, AitoPanelConfig } from "@/lib/types";

const defaultPanel: AitoPanelConfig = {
  operation: "_predict",
  endpoints: ["_predict"],
  stats: [
    { label: "Incomplete", value: "12" },
    { label: "Predictable", value: "9" },
    { label: "Avg missing", value: "2.3" },
  ],
  description:
    "Products with <em>missing attributes</em> block downstream workflows: quoting, customs export, warehouse picking. aito.._predict fills gaps by learning from complete products in the same category &mdash; no rules needed.",
  query: `<span class="q-k">POST</span> <span class="q-v">/api/v1/_predict</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"products"</span>,\n  <span class="q-k">"where"</span>: { <span class="q-k">"sku"</span>: <span class="q-v">"EL-4420"</span> },\n  <span class="q-k">"predict"</span>: <span class="q-p">"hs_code"</span>\n}`,
  links: [
    { label: "aito.ai/docs/predict", url: "https://aito.ai/docs/api/predict" },
  ],
};

import type { WhyExplanation, Alternative } from "@/lib/types";
import WhyPopover from "@/components/prediction/WhyPopover";

interface CatalogPredictionResponse {
  sku: string;
  name: string;
  predictions: Array<{
    field: string;
    predicted_value: string;
    confidence: number;
    alternatives?: Alternative[];
    why?: WhyExplanation;
  }>;
  overall_confidence: number;
}

export default function CatalogPage() {
  const [products, setProducts] = useState<IncompleteProduct[]>([]);
  const [totalProducts, setTotalProducts] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);
  const [bannerOpen, setBannerOpen] = useState(true);
  const [appliedSku, setAppliedSku] = useState<string | null>(null);
  const [predictedFields, setPredictedFields] = useState<CatalogPredictionResponse | null>(null);

  const [bulkApplied, setBulkApplied] = useState<{ count: number; fields: number } | null>(null);
  const [bulkRunning, setBulkRunning] = useState(false);

  const handleApply = async (sku: string) => {
    try {
      const res = await apiFetch<CatalogPredictionResponse>("/api/catalog/predict", {
        method: "POST",
        body: JSON.stringify({ sku }),
      });
      setPredictedFields(res);
      setAppliedSku(sku);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleBulkApply = async (threshold: number) => {
    setBulkRunning(true);
    setBulkApplied(null);
    let appliedCount = 0;
    let fieldsCount = 0;
    for (const p of products) {
      try {
        const res = await apiFetch<CatalogPredictionResponse>("/api/catalog/predict", {
          method: "POST",
          body: JSON.stringify({ sku: p.sku }),
        });
        const highConf = res.predictions.filter((pr) => pr.confidence >= threshold);
        if (highConf.length > 0) {
          appliedCount += 1;
          fieldsCount += highConf.length;
        }
      } catch {
        // Skip failed ones
      }
    }
    setBulkApplied({ count: appliedCount, fields: fieldsCount });
    setBulkRunning(false);
  };

  useEffect(() => {
    apiFetch<CatalogResponse>("/api/catalog/incomplete")
      .then((data) => {
        if (data.products?.length) {
          setProducts(data.products);
        }
        if (data.total != null) {
          setTotalProducts(data.total);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleRowClick = (idx: number) => {
    const p = products[idx];
    setSelected(idx);
    setAppliedSku(null);
    setPredictedFields(null);
    setPanel({
      operation: "_predict",
      endpoints: ["_predict"],
      stats: [
        { label: "Missing", value: String(p.missing_count) },
        { label: "Completeness", value: `${Math.round(p.completeness * 100)}%` },
        { label: "Category", value: p.category ?? "—" },
      ],
      description: `<strong>${p.name}</strong> (${p.sku}) is missing ${p.missing_count} field(s): <em>${p.missing_fields.join(", ")}</em>.<br/><br/>Completeness: ${Math.round(p.completeness * 100)}%.<br/><br/>aito.._predict learns from <em>${p.category ?? "similar"}</em> products with complete data to fill these gaps with no manual rules.`,
      query: `<span class="q-k">POST</span> <span class="q-v">/api/v1/_predict</span>\n{\n  <span class="q-k">"from"</span>: <span class="q-v">"products"</span>,\n  <span class="q-k">"where"</span>: { <span class="q-k">"sku"</span>: <span class="q-v">"${p.sku}"</span> },\n  <span class="q-k">"predict"</span>: <span class="q-p">"${p.missing_fields[0] ?? "hs_code"}"</span>\n}`,
      links: [
        { label: "aito.ai/docs/predict", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const selectedProduct = selected !== null ? products[selected] : null;

  if (error) {
    return (
      <>
        <Nav />
        <div className="main">
          <TopBar title="Catalog Intelligence" breadcrumb="Product" />
          <div className="content-area">
            <div className="content">
              <ErrorState message={error} command="GET /api/catalog/incomplete" />
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
          title="Catalog Intelligence"
          breadcrumb="Product"
          kpis={[{ icon: "\uD83D\uDCE6", label: `${products.length} incomplete` }]}
        />
        <div className="content-area">
          <div className="content">
            {bannerOpen && (
              <div className="intro-banner">
                <div className="intro-banner-text">
                  <strong>Products with missing attributes can&apos;t be sold.</strong> Missing HS codes block customs export. Missing weights block quoting. aito.. predicts the missing fields from complete products in the same category &mdash; no rules required.
                </div>
                <span className="intro-banner-close" onClick={() => setBannerOpen(false)}>&times;</span>
              </div>
            )}

            <div className="kpi-row">
              <div className="kpi">
                <div className="kpi-label">Total Products</div>
                <div className="kpi-val">{totalProducts || products.length}</div>
                <div className="kpi-sub">in catalog</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Incomplete</div>
                <div className="kpi-val" style={{ color: "var(--red)" }}>{products.filter(p => p.missing_count > 0).length}</div>
                <div className="kpi-sub">missing attributes</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Catalog Completeness</div>
                <div className="kpi-val" style={{ color: "var(--gold)" }}>
                  {totalProducts > 0 ? Math.round((1 - products.length / totalProducts) * 100 + (products.reduce((a, p) => a + p.completeness, 0) / totalProducts) * 100) : 0}%
                </div>
                <div className="kpi-sub">overall (complete + partial)</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Avg Fields Missing</div>
                <div className="kpi-val">
                  {products.length > 0 ? (products.reduce((a, p) => a + p.missing_count, 0) / products.length).toFixed(1) : 0}
                </div>
                <div className="kpi-sub">per incomplete product</div>
              </div>
            </div>

            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14 }}>
              <button
                className="btn btn-primary"
                disabled={bulkRunning || products.length === 0}
                onClick={() => handleBulkApply(0.85)}
              >
                {bulkRunning ? "Predicting..." : "✨ Auto-apply all >85% confidence"}
              </button>
              <button
                className="btn btn-secondary"
                disabled={bulkRunning || products.length === 0}
                onClick={() => handleBulkApply(0.70)}
              >
                Auto-apply &gt;70%
              </button>
              {bulkApplied && (
                <div style={{
                  padding: "8px 14px",
                  background: "var(--green-light)",
                  border: "1px solid var(--green)",
                  color: "var(--green)",
                  borderRadius: 5,
                  fontSize: 12,
                }}>
                  ✓ Applied <strong>{bulkApplied.fields}</strong> field predictions across <strong>{bulkApplied.count}</strong> products. Each becomes training data for future predictions.
                </div>
              )}
            </div>

            <div className="card">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Product</th>
                    <th>Category</th>
                    <th>Missing Fields</th>
                    <th>Price</th>
                    <th>HS Code</th>
                    <th>Unit</th>
                    <th>Completeness</th>
                  </tr>
                </thead>
                <tbody>
                  {products.map((p, i) => (
                    <tr key={p.sku} className={`clickable${selected === i ? " selected" : ""}`} onClick={() => handleRowClick(i)}>
                      <td className="mono">{p.sku}</td>
                      <td>{p.name}</td>
                      <td><span className="badge b-gray">{p.category ?? "—"}</span></td>
                      <td>
                        {p.missing_fields.map((f) => (
                          <span key={f} className="badge b-red" style={{ marginRight: 3 }}>{f}</span>
                        ))}
                      </td>
                      <td className="mono">{p.unit_price != null ? fmtAmount(p.unit_price) : "—"}</td>
                      <td>
                        {p.hs_code ? (
                          <span className="mono">{p.hs_code}</span>
                        ) : (
                          <span className="badge b-red">missing</span>
                        )}
                      </td>
                      <td>
                        {p.unit_of_measure ? (
                          <span className="mono">{p.unit_of_measure}</span>
                        ) : (
                          <span className="badge b-gray">&mdash;</span>
                        )}
                      </td>
                      <td>
                        <div className={`conf ${confClass(p.completeness)}`}>
                          <div className="conf-track">
                            <div className="conf-fill" style={{ width: `${p.completeness * 100}%` }} />
                          </div>
                          <span className="conf-val">{Math.round(p.completeness * 100)}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {products.length === 0 && !loading && (
                    <tr>
                      <td colSpan={8} style={{ textAlign: "center", color: "var(--mid)", padding: 32 }}>
                        No incomplete products found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ position: "relative" }}>
            <AitoPanel config={panel} />
            {selectedProduct && (
              <div style={{
                position: "absolute",
                bottom: 16,
                left: 16,
                right: 16,
                padding: "12px 14px",
                background: appliedSku === selectedProduct.sku ? "rgba(45,122,79,0.15)" : "rgba(212,160,48,0.15)",
                border: `1px solid ${appliedSku === selectedProduct.sku ? "var(--green)" : "var(--gold)"}`,
                borderRadius: 6,
                color: "var(--aito-text)",
                fontSize: 11.5,
                lineHeight: 1.5,
              }}>
                {appliedSku === selectedProduct.sku && predictedFields ? (
                  <>
                    <div style={{ fontWeight: 600, color: "var(--green)", marginBottom: 6 }}>
                      ✓ Predictions applied to {selectedProduct.sku}
                    </div>
                    {predictedFields.predictions.map((p) => (
                      <div key={p.field} style={{ marginBottom: 3, display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ color: "var(--aito-dim)" }}>{p.field}:</span>{" "}
                        <strong>{p.predicted_value}</strong>{" "}
                        <span style={{ color: "var(--aito-teal)" }}>({Math.round(p.confidence * 100)}%)</span>
                        {p.why && (
                          <WhyPopover
                            value={p.predicted_value}
                            confidence={p.confidence}
                            why={p.why}
                            alternatives={p.alternatives}
                          />
                        )}
                      </div>
                    ))}
                    <div style={{ marginTop: 8, fontSize: 10.5, color: "var(--aito-dim)", fontStyle: "italic" }}>
                      This transaction becomes training data — future predictions for similar products will improve.
                    </div>
                  </>
                ) : (
                  <button
                    className="btn btn-primary"
                    style={{ width: "100%" }}
                    onClick={() => handleApply(selectedProduct.sku)}
                  >
                    ✨ Apply predictions to {selectedProduct.sku}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

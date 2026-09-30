"use client";

import { useState, useEffect } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount, confClass } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import type { CatalogResponse, IncompleteProduct, AitoPanelConfig } from "@/lib/types";

// The query the backend sends for one missing field, drawn from the row
// itself. It never names the SKU: a unique id matches only the product
// being filled, blank in exactly that field, and the answer collapses
// onto it. A number is estimated from comparable products rather than
// predicted as an exact value, and the name stays out of that `where`.
const NUMERIC_FIELDS = new Set(["unit_price", "weight_kg"]);

// A value as it would appear in the JSON body, made safe for the panel's
// HTML: `TV 55"` must neither end the string early nor open a tag.
const asJsonHtml = (v: string) =>
  JSON.stringify(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function catalogQuery(p: Pick<IncompleteProduct, "name" | "supplier" | "category" | "hs_code" | "unit_of_measure">, field: string): string {
  const numeric = NUMERIC_FIELDS.has(field);
  const context: [string, string | null][] = [
    ["name", numeric ? null : p.name],
    ["supplier", p.supplier],
    ["category", p.category],
    ["hs_code", p.hs_code],
    ["unit_of_measure", p.unit_of_measure],
  ];
  const where = context
    .filter(([k, v]) => k !== field && v != null && v !== "")
    .map(([k, v]) => `    <span class="q-k">"${k}"</span>: <span class="q-v">${asJsonHtml(v as string)}</span>`)
    .join(",\n");
  const op = numeric ? "_estimate" : "_predict";
  return `<span class="q-k">POST</span> <span class="q-v">/api/{version}/${op}</span>\n{\n` +
    `  <span class="q-k">"from"</span>: <span class="q-v">"products"</span>,\n` +
    `  <span class="q-k">"where"</span>: {\n${where}\n  },\n` +
    `  <span class="q-k">"${numeric ? "estimate" : "predict"}"</span>: <span class="q-p">"${field}"</span>\n}`;
}

const defaultPanel: AitoPanelConfig = {
  operation: "_predict",
  endpoints: ["_predict", "_estimate"],
  stats: [
    // Filled from the loaded list (see the fetch below). These were
    // "12 / 9 / 2.3" and stayed on screen after the real list arrived.
    { label: "Incomplete", value: "—" },
    { label: "Catalogue", value: "—" },
    { label: "Avg missing", value: "—" },
  ],
  description:
    "Products with <em>missing attributes</em> block downstream workflows: quoting, customs export, warehouse picking. aito.._predict fills categorical gaps by learning from complete products in the same category, and aito.._estimate fills numbers such as price from comparable products &mdash; no rules needed.",
  query: catalogQuery({ name: "Cable Tray 300mm", supplier: "Onninen", category: "Electrical", hs_code: null, unit_of_measure: "m" }, "hs_code"),
  links: [
    { label: "aito.ai/docs/predict", url: "https://aito.ai/docs/api/predict" },
    { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/07-catalog-intelligence.md", kind: "doc" },
    { label: "Source code", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/catalog_service.py", kind: "github" },
  ],
};

import type { WhyExplanation, Alternative } from "@/lib/types";
import WhyPopover from "@/components/prediction/WhyPopover";

/** One field. `kind` says what sort of claim it is, because they are
 *  not the same claim: a category comes with a probability; a price or
 *  a weight is an ESTIMATE from comparable products and has none; and a
 *  field no product in the category carries does not apply — an hour of
 *  inspection has no weight. */
interface CatalogPrediction {
  field: string;
  predicted_value: string;
  kind: "predict" | "estimate" | "not_applicable";
  neighbours: number;
  confidence: number | null;
  alternatives?: Alternative[];
  why?: WhyExplanation;
}

interface CatalogPredictionResponse {
  sku: string;
  name: string;
  predictions: CatalogPrediction[];
  overall_confidence: number | null;  // null when no field was a categorical prediction
}

export default function CatalogPage() {
  const { tenantId } = useTenant();
  const [products, setProducts] = useState<IncompleteProduct[]>([]);
  const [totalProducts, setTotalProducts] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);
  const [bannerOpen, setBannerOpen] = useState(true);
  const [appliedSku, setAppliedSku] = useState<string | null>(null);
  const [predictedFields, setPredictedFields] = useState<CatalogPredictionResponse | null>(null);

  const [bulkApplied, setBulkApplied] = useState<{ count: number; fields: number; failed: number } | null>(null);
  // What has been filled in, per SKU and field, so the TABLE shows it.
  // It used to live only in the result box; the rows never changed.
  const [applied, setApplied] = useState<Record<string, Record<string, CatalogPrediction>>>({});
  const applyTo = (sku: string, preds: CatalogPrediction[]) =>
    setApplied((prev) => ({
      ...prev,
      [sku]: { ...(prev[sku] ?? {}), ...Object.fromEntries(preds.map((p) => [p.field, p])) },
    }));
  const [bulkRunning, setBulkRunning] = useState(false);

  const handleApply = async (sku: string) => {
    try {
      const res = await apiFetch<CatalogPredictionResponse>("/api/catalog/predict", {
        method: "POST",
        body: JSON.stringify({ sku }),
      });
      setPredictedFields(res);
      setAppliedSku(sku);
      applyTo(sku, res.predictions);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleBulkApply = async (threshold: number) => {
    setBulkRunning(true);
    setBulkApplied(null);
    let appliedCount = 0;
    let fieldsCount = 0;
    let failed = 0;
    for (const p of products) {
      try {
        const res = await apiFetch<CatalogPredictionResponse>("/api/catalog/predict", {
          method: "POST",
          body: JSON.stringify({ sku: p.sku }),
        });
        // Only probabilities can clear a threshold. Estimates have none,
        // so bulk leaves them for a person to look at; "does not apply"
        // is always recorded, since it is a fact about the category.
        const confident = res.predictions.filter(
          (pr) => pr.kind === "predict" && (pr.confidence ?? 0) >= threshold);
        const na = res.predictions.filter((pr) => pr.kind === "not_applicable");
        if (confident.length + na.length > 0) applyTo(p.sku, [...confident, ...na]);
        if (confident.length > 0) {
          appliedCount += 1;
          fieldsCount += confident.length;
        }
      } catch {
        // Counted and shown. It used to be skipped in silence, so a run
        // where every request failed reported "0 applied" as a result.
        failed += 1;
      }
    }
    setBulkApplied({ count: appliedCount, fields: fieldsCount, failed });
    setBulkRunning(false);
  };

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch<CatalogResponse>("/api/catalog/incomplete")
      .then((data) => {
        if (data.products?.length) {
          setProducts(data.products);
        }
        if (data.total != null) {
          setTotalProducts(data.total);
        }
        const missing = data.products.reduce((a, p) => a + p.missing_count, 0);
        setPanel((current) => ({
          ...current,
          stats: [
            { label: "Incomplete", value: String(data.products.length) },
            { label: "Catalogue", value: String(data.total) },
            { label: "Avg missing", value: data.products.length ? (missing / data.products.length).toFixed(1) : "—" },
          ],
        }));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  const handleRowClick = (idx: number) => {
    const p = products[idx];
    setSelected(idx);
    setAppliedSku(null);
    setPredictedFields(null);
    setPanel({
      operation: NUMERIC_FIELDS.has(p.missing_fields[0] ?? "") ? "_estimate" : "_predict",
      endpoints: ["_predict", "_estimate"],
      stats: [
        { label: "Missing", value: String(p.missing_count) },
        { label: "Completeness", value: `${Math.round(p.completeness * 100)}%` },
        { label: "Category", value: p.category ?? "—" },
      ],
      description: `<strong>${p.name}</strong> (${p.sku}) is missing ${p.missing_count} field(s): <em>${p.missing_fields.join(", ")}</em>.<br/><br/>Completeness: ${Math.round(p.completeness * 100)}%.<br/><br/>aito.._predict learns from <em>${p.category ?? "similar"}</em> products with complete data to fill these gaps with no manual rules.`,
      query: catalogQuery(p, p.missing_fields[0] ?? "hs_code"),
      links: [
        { label: "aito.ai/docs/predict", url: "https://aito.ai/docs/api/predict" },
      ],
    });
  };

  const selectedProduct = selected !== null ? products[selected] : null;

  /** A filled-in value, styled so it can never be mistaken for data the
   *  catalogue already held: it is a suggestion until someone accepts it. */
  const filled = (sku: string, field: string) => {
    const pr = applied[sku]?.[field];
    if (!pr || pr.kind === "not_applicable") return null;
    return (
      <span title={pr.kind === "estimate"
                    ? `estimated from ${pr.neighbours} comparable products`
                    : `predicted, ${Math.round((pr.confidence ?? 0) * 100)}%`}
            style={{ color: "var(--aito-teal)", fontStyle: "italic" }}>
        {field === "unit_price" ? fmtAmount(Number(pr.predicted_value)) : pr.predicted_value}
      </span>
    );
  };

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
                  ✓ Filled <strong>{bulkApplied.fields}</strong> fields across <strong>{bulkApplied.count}</strong> products — shown in the table below.
                  {bulkApplied.failed > 0 && (
                    <> <strong style={{ color: "var(--red)" }}>{bulkApplied.failed} requests failed</strong> and were not applied.</>
                  )}
                </div>
              )}
            </div>

            {selectedProduct && (
              // In the main column. It was absolutely positioned inside the
              // Aito panel's container, so it rendered on top of the
              // panel's own content — the "squashed toast" — and on a phone,
              // where the panel is hidden, it vanished with it.
              <div className="card" style={{
                marginBottom: 14,
                padding: "12px 14px",
                background: appliedSku === selectedProduct.sku ? "rgba(45,122,79,0.15)" : "rgba(212,160,48,0.15)",
                border: `1px solid ${appliedSku === selectedProduct.sku ? "var(--green)" : "var(--gold)"}`,
                borderRadius: 6,
                color: "var(--ink)",
                fontSize: 11.5,
                lineHeight: 1.5,
              }}>
                {appliedSku === selectedProduct.sku && predictedFields ? (
                  <>
                    <div style={{ fontWeight: 600, color: "var(--green)", marginBottom: 6 }}>
                      ✓ Filled in for {selectedProduct.sku} — see the table
                    </div>
                    {predictedFields.predictions.map((p) => (
                      <div key={p.field} style={{ marginBottom: 3, display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ color: "var(--mid)" }}>{p.field}:</span>{" "}
                        {p.kind === "not_applicable" ? (
                          <span style={{ color: "var(--mid)" }}>does not apply in this category</span>
                        ) : (
                          <>
                            <strong>{p.predicted_value}</strong>{" "}
                            <span style={{ color: "var(--aito-teal)" }}>
                              {p.kind === "estimate"
                                ? `(estimated from ${p.neighbours} comparable products)`
                                : `(${Math.round((p.confidence ?? 0) * 100)}%)`}
                            </span>
                          </>
                        )}
                        {p.why && p.confidence != null && (
                          <WhyPopover
                            value={p.predicted_value}
                            confidence={p.confidence ?? 0}
                            why={p.why}
                            alternatives={p.alternatives}
                          />
                        )}
                      </div>
                    ))}
                    <div style={{ marginTop: 8, fontSize: 10.5, color: "var(--mid)", fontStyle: "italic" }}>
                      Shown here only — this demo does not write to the catalogue. In production,
                      accepting a value writes it back, and it becomes history for the next prediction.
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
                      <td>{p.category
                        ? <span className="badge b-gray">{p.category}</span>
                        : filled(p.sku, "category") ?? <span className="badge b-gray">—</span>}</td>
                      <td>
                        {p.missing_fields.map((f) => {
                          const pr = applied[p.sku]?.[f];
                          const cls = !pr ? "badge b-red" : pr.kind === "not_applicable" ? "badge b-gray" : "badge b-green";
                          const label = !pr ? f : pr.kind === "not_applicable" ? `${f}: n/a` : `${f} ✓`;
                          return <span key={f} className={cls} style={{ marginRight: 3 }}>{label}</span>;
                        })}
                      </td>
                      <td className="mono">{p.unit_price != null ? fmtAmount(p.unit_price) : filled(p.sku, "unit_price") ?? "—"}</td>
                      <td>
                        {p.hs_code ? (
                          <span className="mono">{p.hs_code}</span>
                        ) : applied[p.sku]?.hs_code?.kind === "not_applicable" ? (
                          <span className="badge b-gray">n/a</span>
                        ) : (
                          filled(p.sku, "hs_code") ?? <span className="badge b-red">missing</span>
                        )}
                      </td>
                      <td>
                        {p.unit_of_measure ? (
                          <span className="mono">{p.unit_of_measure}</span>
                        ) : (
                          filled(p.sku, "unit_of_measure") ?? <span className="badge b-gray">&mdash;</span>
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
          </div>
        </div>
      </div>
    </>
  );
}

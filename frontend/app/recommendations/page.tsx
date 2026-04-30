"use client";

import { useEffect, useMemo, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch, fmtAmount } from "@/lib/api";
import type {
  AitoPanelConfig,
  RecommendationOverview,
  RecommendationProduct,
  CrossSellItem,
  SimilarItem,
} from "@/lib/types";

const DEFAULT_PANEL: AitoPanelConfig = {
  operation: "_search + _match",
  endpoints: ["_recommend", "_match"],
  stats: [
    { label: "Tables", value: "products + orders" },
    { label: "Pattern", value: "co-occurrence" },
    { label: "Latency", value: "20-60ms" },
  ],
  description:
    "Recommendations combine two Aito patterns. <em>aito.._search</em> over " +
    "<em>orders</em> finds products that appear in the same months as the " +
    "anchor item — the basket co-occurrence signal that drives cross-sell. " +
    "<em>aito.._match</em> over <em>products</em> finds items with overlapping " +
    "category, supplier, and price-band — the &ldquo;similar products&rdquo; " +
    "ribbon. Both are queried per request; no offline batch jobs, no model " +
    "retraining.",
  query: `<span class="q-k">POST</span> /api/v1/_search<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"orders"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"product_id"</span>: <span class="q-v">"SKU-1234"</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"limit"</span>: <span class="q-n">300</span><br/>
}<br/>
<br/>
<span class="q-k">POST</span> /api/v1/_match<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"products"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"category"</span>: <span class="q-v">"Beauty"</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"limit"</span>: <span class="q-n">10</span><br/>
}`,
  links: [
    { label: "Search API reference", url: "https://aito.ai/docs/api/search" },
    { label: "Match API reference", url: "https://aito.ai/docs/api/match" },
  ],
};

function fmtPriceMaybe(p: number | null): string {
  return p == null ? "—" : fmtAmount(p);
}

export default function RecommendationsPage() {
  const [overview, setOverview] = useState<RecommendationOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [anchorSku, setAnchorSku] = useState<string | null>(null);
  const [crossSell, setCrossSell] = useState<CrossSellItem[]>([]);
  const [similar, setSimilar] = useState<SimilarItem[]>([]);
  const [recsLoading, setRecsLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [panel, setPanel] = useState<AitoPanelConfig>(DEFAULT_PANEL);

  useEffect(() => {
    apiFetch<RecommendationOverview>("/api/recommendations/overview")
      .then((data) => {
        setOverview(data);
        if (data.trending.length && !anchorSku) {
          setAnchorSku(data.trending[0].sku);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Fetch cross-sell + similar whenever the anchor changes.
  useEffect(() => {
    if (!anchorSku) return;
    setRecsLoading(true);
    Promise.all([
      apiFetch<{ items: CrossSellItem[] }>(
        `/api/recommendations/cross-sell?sku=${encodeURIComponent(anchorSku)}`,
      ),
      apiFetch<{ items: SimilarItem[] }>(
        `/api/recommendations/similar?sku=${encodeURIComponent(anchorSku)}`,
      ),
    ])
      .then(([cs, sim]) => {
        setCrossSell(cs.items);
        setSimilar(sim.items);
      })
      .catch((e) => setError(e.message))
      .finally(() => setRecsLoading(false));
  }, [anchorSku]);

  const anchorProduct: RecommendationProduct | undefined = useMemo(() => {
    if (!overview || !anchorSku) return undefined;
    return overview.products.find((p) => p.sku === anchorSku);
  }, [overview, anchorSku]);

  // Update Aito panel whenever the anchor changes.
  useEffect(() => {
    if (!anchorProduct) return;
    setPanel({
      ...DEFAULT_PANEL,
      stats: [
        { label: "Anchor", value: anchorProduct.name.slice(0, 18) },
        { label: "Cross-sell", value: String(crossSell.length) },
        { label: "Similar", value: String(similar.length) },
      ],
      description:
        `Recommendations for <em>${anchorProduct.name}</em>. ` +
        (crossSell.length
          ? `Top cross-sell: <em>${crossSell[0].name}</em> ` +
            `&mdash; P(click | prev = anchor) = ${(crossSell[0].p_click * 100).toFixed(1)}%. `
          : "") +
        (similar.length
          ? `Top similar item: <em>${similar[0].name}</em> ` +
            `(score ${similar[0].score.toFixed(2)}). `
          : "") +
        `Both lists update on every anchor change &mdash; no precomputed batch.`,
    });
  }, [anchorProduct, crossSell, similar]);

  const filteredProducts = useMemo(() => {
    if (!overview) return [];
    const q = filter.trim().toLowerCase();
    if (!q) return overview.products.slice(0, 30);
    return overview.products
      .filter((p) =>
        p.name.toLowerCase().includes(q) ||
        (p.category ?? "").toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q),
      )
      .slice(0, 30);
  }, [overview, filter]);

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar
          title="Recommendations"
          breadcrumb="Product"
          subtitle={anchorProduct ? `for ${anchorProduct.name}` : undefined}
        />
        <div className="content-area">
          <div className="content">
            {error && (
              <ErrorState message={error} command="GET /api/recommendations/overview" />
            )}
            {!error && (loading || !overview) && (
              <p style={{ padding: 24, color: "var(--mid)" }}>Loading…</p>
            )}
            {!error && overview && (
              <>
                {/* Trending ribbon — quick-pick anchors */}
                <section className="card" style={{ marginBottom: 16 }}>
                  <div className="card-head">
                    <span className="card-title">Trending now</span>
                    <span className="card-meta">last 6 months · top 15 by units</span>
                  </div>
                  <div className="recs-trend-row">
                    {overview.trending.map((t) => (
                      <button
                        key={t.sku}
                        type="button"
                        className={`recs-trend-pill${anchorSku === t.sku ? " active" : ""}`}
                        onClick={() => setAnchorSku(t.sku)}
                        title={`${t.units_sold} units across ${t.months} months`}
                      >
                        <span className="recs-trend-name">{t.name}</span>
                        <span className="recs-trend-units">{t.units_sold}</span>
                      </button>
                    ))}
                  </div>
                </section>

                {/* Two-column: catalog picker + recommendations panel */}
                <div className="recs-grid">
                  {/* Catalog picker */}
                  <section className="card">
                    <div className="card-head">
                      <span className="card-title">Pick an anchor product</span>
                      <span className="card-meta">{overview.products.length} in catalog</span>
                    </div>
                    <div style={{ padding: "10px 14px" }}>
                      <input
                        type="text"
                        className="form-input"
                        placeholder="Filter by name, category, or SKU…"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      />
                    </div>
                    <div className="recs-product-list">
                      {filteredProducts.map((p) => (
                        <button
                          key={p.sku}
                          type="button"
                          className={`recs-product-row${anchorSku === p.sku ? " active" : ""}`}
                          onClick={() => setAnchorSku(p.sku)}
                        >
                          <div className="recs-product-name">{p.name}</div>
                          <div className="recs-product-sub">
                            {p.category}
                            {p.supplier ? <> · {p.supplier}</> : null}
                            {p.unit_price != null ? <> · {fmtAmount(p.unit_price)}</> : null}
                          </div>
                        </button>
                      ))}
                      {filteredProducts.length === 0 && (
                        <div style={{ padding: 14, fontSize: 11, color: "var(--mid)", fontStyle: "italic" }}>
                          No products match "{filter}".
                        </div>
                      )}
                    </div>
                  </section>

                  {/* Recommendations for the anchor */}
                  <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    {anchorProduct && (
                      <div className="recs-anchor-card">
                        <div className="recs-anchor-label">Anchor product</div>
                        <div className="recs-anchor-name">{anchorProduct.name}</div>
                        <div className="recs-anchor-sub">
                          {anchorProduct.sku}
                          {anchorProduct.category ? <> · {anchorProduct.category}</> : null}
                          {anchorProduct.unit_price != null ? <> · {fmtAmount(anchorProduct.unit_price)}</> : null}
                        </div>
                      </div>
                    )}

                    {/* Cross-sell */}
                    <div className="card">
                      <div className="card-head">
                        <span className="card-title">Frequently bought together</span>
                        <span className="card-meta">aito.._recommend · goal: clicked</span>
                      </div>
                      <div style={{ padding: "8px 14px 10px", fontSize: 11, color: "var(--mid)", lineHeight: 1.5 }}>
                        Ranked by P(click | prev = anchor) from the impressions table — the same
                        operator that drives help-article CTR ranking. One <code>_recommend</code>
                        call returns the full product row via linked <code>select</code>.
                      </div>
                      {recsLoading ? (
                        <div style={{ padding: 14, fontSize: 11, color: "var(--mid)" }}>Loading…</div>
                      ) : crossSell.length === 0 ? (
                        <div style={{ padding: 14, fontSize: 11, color: "var(--mid)", fontStyle: "italic" }}>
                          No impressions paired with this anchor — try a more popular SKU.
                        </div>
                      ) : (
                        <table className="tbl">
                          <thead>
                            <tr>
                              <th>Product</th>
                              <th style={{ textAlign: "right" }}>Category</th>
                              <th style={{ textAlign: "right" }}>P(click)</th>
                            </tr>
                          </thead>
                          <tbody>
                            {crossSell.map((c) => (
                              <tr key={c.sku} className="clickable" onClick={() => setAnchorSku(c.sku)}>
                                <td>
                                  <div className="proj-name">{c.name}</div>
                                  <div className="proj-sub">
                                    {c.sku}{c.supplier ? <> · {c.supplier}</> : null}
                                  </div>
                                </td>
                                <td style={{ textAlign: "right" }} className="mono">
                                  {c.category ?? "—"}
                                </td>
                                <td
                                  className="mono"
                                  style={{ textAlign: "right", color: c.p_click > 0.5 ? "var(--green)" : "var(--ink)" }}
                                >
                                  {Math.round(c.p_click * 100)}%
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>

                    {/* Similar */}
                    <div className="card">
                      <div className="card-head">
                        <span className="card-title">Similar products</span>
                        <span className="card-meta">aito.._match · attribute overlap</span>
                      </div>
                      <div style={{ padding: "8px 14px 10px", fontSize: 11, color: "var(--mid)", lineHeight: 1.5 }}>
                        Products with overlapping category, supplier, and price band.
                        Different from cross-sell: similar items are <em>substitutes</em>, not <em>complements</em>.
                      </div>
                      {recsLoading ? (
                        <div style={{ padding: 14, fontSize: 11, color: "var(--mid)" }}>Loading…</div>
                      ) : similar.length === 0 ? (
                        <div style={{ padding: 14, fontSize: 11, color: "var(--mid)", fontStyle: "italic" }}>
                          No similar items in this category.
                        </div>
                      ) : (
                        <table className="tbl">
                          <thead>
                            <tr>
                              <th>Product</th>
                              <th>Supplier</th>
                              <th style={{ textAlign: "right" }}>Price</th>
                              <th style={{ textAlign: "right" }}>Match score</th>
                            </tr>
                          </thead>
                          <tbody>
                            {similar.map((s) => (
                              <tr key={s.sku} className="clickable" onClick={() => setAnchorSku(s.sku)}>
                                <td>
                                  <div className="proj-name">{s.name}</div>
                                  <div className="proj-sub">{s.sku}{s.category ? <> · {s.category}</> : null}</div>
                                </td>
                                <td>{s.supplier ?? "—"}</td>
                                <td style={{ textAlign: "right" }} className="mono">{fmtPriceMaybe(s.unit_price)}</td>
                                <td style={{ textAlign: "right" }} className="mono">
                                  {s.score.toFixed(2)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  </section>
                </div>
              </>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

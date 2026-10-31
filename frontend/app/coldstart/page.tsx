"use client";

import { useEffect, useMemo, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import { findQuery } from "@/lib/query";
import type {
  AitoPanelConfig,
  ColdStartCutoff,
  ColdStartLiveResponse,
  ColdStartResponse,
} from "@/lib/types";

const PANEL: AitoPanelConfig = {
  operation: "cold start (live)",
  endpoints: ["_evaluate"],
  stats: [
    { label: "Cutoffs", value: "5" },
    { label: "Mode", value: "live" },
    { label: "Endpoint", value: "_evaluate" },
  ],
  description:
    "Drag the slider to ask: <em>what would prediction quality look like " +
    "for a tenant whose data only goes through this month?</em><br/><br/>" +
    "Each slider position runs three live <em>_evaluate</em> queries " +
    "against the current tenant's <code>purchases</code> table, with " +
    "<code>order_month: { $lte: cutoff }</code> tacked onto the " +
    "evaluate-step <code>where</code>. Aito's conditional probabilities " +
    "then condition on only rows up to that cutoff — same shape as a " +
    "younger tenant. No data manipulation; works against read-only keys.",
  // Filled from the slider position on screen: the `_evaluate` that
  // /api/coldstart/live sent for it (see `panel` below).
  queries: [],
  links: [
    { label: "_evaluate API reference", url: "https://aito.ai/docs/api/evaluate" },
    { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/15-cold-start.md", kind: "doc" },
    { label: "Source code", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/frontend/app/coldstart/page.tsx", kind: "github" },
  ],
};

export default function ColdStartPage() {
  const { tenantId } = useTenant();
  const [cutoffs, setCutoffs] = useState<ColdStartCutoff[]>([]);
  const [activeIdx, setActiveIdx] = useState<number>(4);
  // Cache responses per cutoff so dragging the slider after the
  // first round-trip is instant. Backend caches too (Aito-level),
  // but keeping a frontend cache means even the apiFetch round-trip
  // is skipped.
  const [cache, setCache] = useState<Record<string, ColdStartLiveResponse>>({});
  const [loadingCutoff, setLoadingCutoff] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<ColdStartResponse | null>(null);

  // Pull the cutoffs metadata + the captured static snapshot once.
  useEffect(() => {
    apiFetch<{ cutoffs: ColdStartCutoff[] }>("/api/coldstart/cutoffs")
      .then((res) => setCutoffs(res.cutoffs))
      .catch((e) => setError(e.message));
    apiFetch<ColdStartResponse>("/api/coldstart")
      .then(setSnapshot)
      .catch(() => { /* snapshot is optional */ });
  }, []);

  // Switching tenants invalidates the cache — different DB, different
  // numbers. The active index stays put so the user lands on the same
  // slider position they were inspecting.
  useEffect(() => {
    setCache({});
  }, [tenantId]);

  const activeCutoff = cutoffs[activeIdx]?.cutoff;

  // Fetch on cutoff change. Cached responses skip the round-trip.
  useEffect(() => {
    if (!activeCutoff) return;
    if (cache[activeCutoff]) return;
    setLoadingCutoff(activeCutoff);
    apiFetch<ColdStartLiveResponse>(
      `/api/coldstart/live?cutoff=${encodeURIComponent(activeCutoff)}`,
    )
      .then((res) => {
        setCache((prev) => ({ ...prev, [activeCutoff]: res }));
      })
      .catch((e) => setError(e.message))
      .finally(() => {
        setLoadingCutoff((cur) => (cur === activeCutoff ? null : cur));
      });
  }, [activeCutoff, cache]);

  const active = activeCutoff ? cache[activeCutoff] : undefined;
  const activeMeta = cutoffs[activeIdx];
  const isLoading = loadingCutoff === activeCutoff && !active;

  // The pane shows the first of the three `_evaluate` queries behind the
  // cutoff on screen, as sent: its evidence is a nested `from` that ends at
  // the test month, and its test rows are that month's purchases.
  const panel = useMemo<AitoPanelConfig>(() => {
    const q = findQuery(active?._queries, { endpoint: "_evaluate" });
    return { ...PANEL, queries: q ? [q] : [] };
  }, [active]);

  const summary = useMemo(() => {
    if (!active) return null;
    const fields = active.fields;
    const avg = (k: keyof typeof fields[number]) =>
      fields.reduce((a, f) => a + (f[k] as number), 0) / fields.length;
    return {
      accuracy: avg("accuracy"),
      base_accuracy: avg("base_accuracy"),
      high_confidence_share: avg("high_confidence_share"),
      high_confidence_accuracy: avg("high_confidence_accuracy"),
    };
  }, [active]);

  return (
    <>
      <Nav />
      <main className="main">
        <TopBar
          breadcrumb="Quality"
          title="Cold Start"
          subtitle="Live _evaluate · drag to simulate younger tenants"
          live
        />
        <div className="content-area">
          <div className="content">
            {error && <ErrorState message={error} command="GET /api/coldstart/live" />}

            <div className="intro-banner">
              <div className="intro-banner-text">
                <strong>Drag the slider</strong> to ask: <em>what would
                prediction quality look like for a tenant whose data only
                goes through this month?</em>
                <span className="intro-banner-freshness">
                  Each position runs <code>_evaluate</code> live: Aito learns only
                  from the tenant's <code>purchases</code> up to the cutoff and is
                  tested on the month after it, which it has never seen.
                </span>
              </div>
            </div>

            {cutoffs.length > 0 && (
              <div className="card cs-slider-card">
                <div className="cs-slider-row">
                  <input
                    type="range"
                    min={0}
                    max={cutoffs.length - 1}
                    step={1}
                    value={activeIdx}
                    onChange={(e) => setActiveIdx(Number(e.target.value))}
                    className="cs-slider"
                    aria-label="Cold-start cutoff"
                  />
                </div>
                <div className="cs-slider-ticks">
                  {cutoffs.map((c, i) => (
                    <button
                      key={c.cutoff}
                      type="button"
                      className={`cs-slider-tick${i === activeIdx ? " cs-slider-tick--active" : ""}`}
                      onClick={() => setActiveIdx(i)}
                    >
                      <div className="cs-slider-tick-label">{c.label}</div>
                      <div className="cs-slider-tick-rows">
                        ~{c.approx_rows.toLocaleString("fi-FI")} rows
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {activeMeta && (
              <div className="cs-headline">
                <div className="cs-headline-prefix">Tenant has</div>
                <div className="cs-headline-amount">{activeMeta.label}</div>
                <div className="cs-headline-suffix">
                  of data &middot; ~{activeMeta.approx_rows.toLocaleString("fi-FI")} purchase orders
                  {active && (
                    <> &middot; learned from {active.fields[0].training_rows.toLocaleString("fi-FI")},
                    tested on the {active.fields[0].total_cases} purchases of {activeMeta.test_month}</>
                  )}
                </div>
              </div>
            )}

            {isLoading && (
              <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--mid)" }}>
                Running _evaluate against Aito… (typically 5-20s per cutoff)
              </div>
            )}

            {active && summary && (
              <>
                {/* Headline KPIs across all fields */}
                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">Accuracy (avg)</div>
                    <div className="kpi-val">{Math.round(summary.accuracy * 100)}%</div>
                    <div className="kpi-sub">across cost_center / account_code / approver</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Baseline (avg)</div>
                    <div className="kpi-val">{Math.round(summary.base_accuracy * 100)}%</div>
                    <div className="kpi-sub">most-common-value</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">≥ 0.85 share</div>
                    <div className="kpi-val">{Math.round(summary.high_confidence_share * 100)}%</div>
                    <div className="kpi-sub">cases Aito will auto-approve</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Accuracy in band</div>
                    <div className="kpi-val">{Math.round(summary.high_confidence_accuracy * 100)}%</div>
                    <div className="kpi-sub">of those, what's right</div>
                  </div>
                </div>

                <div className="card">
                  <div className="card-head">
                    <span className="card-title">_evaluate: learn up to {activeMeta?.train_through}, test on {activeMeta?.test_month}</span>
                    <span className="card-meta">{active.fields.length} target fields · live</span>
                  </div>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Field</th>
                        <th>Accuracy</th>
                        <th>± (95%)</th>
                        <th>Tested on</th>
                        <th>Baseline</th>
                        <th>Gain</th>
                        <th>≥ 0.85 share</th>
                        <th>Accuracy in band</th>
                      </tr>
                    </thead>
                    <tbody>
                      {active.fields.map((f) => {
                        const gain = f.accuracy - f.base_accuracy;
                        return (
                          <tr key={f.name}>
                            <td style={{ fontWeight: 500 }}>{f.name}</td>
                            <td>
                              <div className="conf">
                                <div className="conf-track">
                                  <div className="conf-fill" style={{ width: `${f.accuracy * 100}%` }} />
                                </div>
                                <span className="conf-val">{Math.round(f.accuracy * 100)}%</span>
                              </div>
                            </td>
                            <td className="mono" style={{ fontSize: 11, color: "var(--mid)" }}>
                              ±{Math.round(196 * Math.sqrt(f.accuracy * (1 - f.accuracy) / f.total_cases))}pt
                            </td>
                            <td className="mono" style={{ fontSize: 11, color: "var(--mid)" }}>
                              n = {f.total_cases}
                            </td>
                            <td className="mono" style={{ fontSize: 11, color: "var(--mid)" }}>
                              {Math.round(f.base_accuracy * 100)}%
                            </td>
                            <td className="mono" style={{ fontSize: 11, color: gain >= 0 ? "var(--green)" : "#c54" }}>
                              {gain >= 0 ? "+" : ""}{Math.round(gain * 100)}pt
                            </td>
                            <td className="mono" style={{ fontSize: 11 }}>
                              {Math.round(f.high_confidence_share * 100)}%
                            </td>
                            <td className="mono" style={{ fontSize: 11, color: "var(--gold-dark)", fontWeight: 600 }}>
                              {Math.round(f.high_confidence_accuracy * 100)}%
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <div style={{ padding: "10px 14px 14px", fontSize: 11, color: "var(--mid)", lineHeight: 1.55 }}>
                    <strong>Reading this:</strong> each position is tested on one month of
                    purchases, so every accuracy rests on the <em>n</em> shown and carries the
                    margin beside it. A step smaller than that margin is noise, not a trend.
                    The baseline is the base rate: always guessing the most common value
                    among the purchases Aito learned from. Aito's calibration ($p) is what
                    makes the ≥ 0.85 band meaningful, and it too is measured on these same few
                    purchases.
                    <br/><br/>
                    <em>Method:</em> the query in the panel gives <code>_evaluate</code> a
                    nested <code>from</code> that ends at the test month; the test month's
                    rows are held out of what it learns from, so it learns from the purchases
                    up to the cutoff and nothing later. The last position has no later month: it
                    learns from everything but the last month and is tested on that.
                  </div>
                </div>
              </>
            )}

            {/* Captured snapshot from the offline capture script. It measures something else
                than the live curve above (a random subsample whose rows are predicted from
                each other, no time order), so it sits behind a disclosure with that said. */}
            {snapshot && (
              <details className="card" style={{ marginTop: 20 }}>
                <summary className="card-head" style={{ cursor: "pointer" }}>
                  <span className="card-title">Older capture: random subsamples, not comparable to the curve above</span>
                  <span className="card-meta">
                    captured {snapshot.captured_at} · not re-captured
                  </span>
                </summary>
                <div style={{ padding: "8px 14px 6px", fontSize: 11, color: "var(--mid)", lineHeight: 1.55 }}>
                  Random subsamples of 50 / 500 / 5,000 purchases, loaded into a separate Aito DB
                  by <code>capture_coldstart.py</code>, with each row predicted from the others:
                  no time order, and the tested rows are the subsample itself (n = 50 at the
                  first size, at most 200 after). It answers a different question from the
                  curve above, so read the two separately.
                </div>
                <div className="cs-curve">
                  {snapshot.snapshots.map((s) => {
                    const avgAcc = s.fields.reduce((a, b) => a + b.accuracy, 0) / s.fields.length;
                    const avgShare = s.fields.reduce((a, b) => a + b.high_confidence_share, 0) / s.fields.length;
                    const avgBandAcc = s.fields.reduce((a, b) => a + b.high_confidence_accuracy, 0) / s.fields.length;
                    return (
                      <div key={s.size} className="cs-curve-col">
                        <div className="cs-curve-size">{s.size.toLocaleString("fi-FI")}</div>
                        <div className="cs-curve-label">{s.label}</div>
                        <div className="cs-curve-bar">
                          <div className="cs-curve-bar-share" style={{ width: `${avgShare * 100}%` }} />
                        </div>
                        <div className="cs-curve-meta">
                          <span><strong>{Math.round(avgAcc * 100)}%</strong> overall</span>
                          <span><strong>{Math.round(avgShare * 100)}%</strong> ≥ 0.85</span>
                          <span><strong>{Math.round(avgBandAcc * 100)}%</strong> in band</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </details>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </main>
    </>
  );
}

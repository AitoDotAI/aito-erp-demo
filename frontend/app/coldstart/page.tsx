"use client";

import { useEffect, useMemo, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
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
  query: `<span class="q-k">POST</span> /api/v1/_evaluate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"testSource"</span>: { <span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>, <span class="q-k">"limit"</span>: <span class="q-n">200</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"evaluate"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>:    { <span class="q-k">"$get"</span>: <span class="q-v">"supplier"</span> },<br/>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"description"</span>: { <span class="q-k">"$get"</span>: <span class="q-v">"description"</span> },<br/>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"amount_eur"</span>:  { <span class="q-k">"$get"</span>: <span class="q-v">"amount_eur"</span> },<br/>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"order_month"</span>: { <span class="q-k">"$lte"</span>: <span class="q-v">"$cutoff"</span> }<br/>
&nbsp;&nbsp;&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"cost_center"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"select"</span>: [<span class="q-v">"accuracy"</span>, <span class="q-v">"baseAccuracy"</span>, <span class="q-v">"cases"</span>]<br/>
}`,
  links: [
    { label: "_evaluate API reference", url: "https://aito.ai/docs/api/evaluate" },
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
                  Each position runs <code>_evaluate</code> live with{" "}
                  <code>order_month: {"{"} $lte: cutoff {"}"}</code> on the
                  current tenant's <code>purchases</code>.
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
                    <span className="card-title">_evaluate at order_month ≤ {activeMeta?.cutoff}</span>
                    <span className="card-meta">{active.fields.length} target fields · live</span>
                  </div>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Field</th>
                        <th>Accuracy</th>
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
                    <strong>Reading this:</strong> on the metsa fixture, supplier-driven
                    patterns for these fields saturate fast — even <em>one week</em> of
                    history (~70 POs) gets accuracy in the 90s, and the ≥ 0.85 confidence
                    band is right 95-100% of the time at every slider position. That's
                    the cold-start story: Aito doesn't need a lot of data to be useful, and
                    its calibration ($p) honestly reflects what it knows.
                    <br/><br/>
                    <em>Note:</em> this slider runs <code>_evaluate</code> with{" "}
                    <code>where: {"{"} order_month: {"{"} $lte: cutoff {"}"} {"}"}</code> on
                    a real Aito DB. That conditions Aito's probabilities on only that slice
                    of history. For a true cold-start simulation (smaller DB end-to-end), see
                    the captured snapshot below.
                  </div>
                </div>
              </>
            )}

            {/* Captured snapshot from the offline capture script —
                a smaller-DB-end-to-end simulation, not a where-filter
                trick. Numbers are real but frozen in time. */}
            {snapshot && (
              <div className="card" style={{ marginTop: 20 }}>
                <div className="card-head">
                  <span className="card-title">Captured snapshot — true cold start</span>
                  <span className="card-meta">
                    captured {snapshot.captured_at} · 50 / 500 / 5,000 row DBs
                  </span>
                </div>
                <div style={{ padding: "8px 14px 6px", fontSize: 11, color: "var(--mid)", lineHeight: 1.55 }}>
                  Ran <code>capture_coldstart.py</code> against three different-size Aito
                  DBs (the slider above can't shrink the DB itself). At 50 rows the
                  high-confidence band is small but right; at 5,000 it covers most of the
                  queue at near-perfect accuracy.
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
              </div>
            )}
          </div>
          <AitoPanel config={PANEL} />
        </div>
      </main>
    </>
  );
}

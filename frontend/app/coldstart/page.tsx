"use client";

import { useEffect, useMemo, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch } from "@/lib/api";
import type { AitoPanelConfig, ColdStartResponse } from "@/lib/types";

const PANEL: AitoPanelConfig = {
  operation: "cold start",
  endpoints: ["_evaluate"],
  stats: [
    { label: "Snapshots", value: "3" },
    { label: "Sizes", value: "50 / 500 / 5K" },
    { label: "Method", value: "_evaluate" },
  ],
  description:
    "Cold start is the question every CTO asks: <em>what does prediction " +
    "quality look like for a tenant with one week of data?</em><br/><br/>" +
    "These three snapshots come from the same metsa fixture, randomly " +
    "subsampled to 50 / 500 / 5,000 rows and loaded into separate Aito " +
    "DBs. <em>_evaluate</em> ran against each. The numbers are real, " +
    "captured offline; the script that produced them lives in " +
    "<code>scripts/capture_coldstart.py</code>.",
  query: `<span class="q-d">// Captured per snapshot:</span><br/>
<span class="q-k">POST</span> /api/v1/_evaluate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"testSource"</span>: { <span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>, <span class="q-k">"limit"</span>: <span class="q-n">200</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"evaluate"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"supplier"</span>: { <span class="q-k">"$get"</span>: <span class="q-v">"supplier"</span> }, … },<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"cost_center"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"select"</span>: [<span class="q-v">"accuracy"</span>, <span class="q-v">"baseAccuracy"</span>, <span class="q-v">"cases"</span>]<br/>
}`,
  links: [
    { label: "_evaluate API reference", url: "https://aito.ai/docs/api/evaluate" },
    { label: "Capture methodology", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/scripts/capture_coldstart.py", kind: "github" },
  ],
};

export default function ColdStartPage() {
  const [data, setData] = useState<ColdStartResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeIndex, setActiveIndex] = useState(2);  // start at the mature tenant

  useEffect(() => {
    apiFetch<ColdStartResponse>("/api/coldstart")
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const active = useMemo(() => data?.snapshots[activeIndex], [data, activeIndex]);

  return (
    <>
      <Nav />
      <main className="main">
        <TopBar
          breadcrumb="Quality"
          title="Cold Start"
          subtitle="Same data, three sizes, real _evaluate"
        />
        <div className="content-area">
          <div className="content">
            {loading && <p style={{ padding: 24, color: "var(--mid)" }}>Loading…</p>}
            {error && <ErrorState message={error} command="GET /api/coldstart" />}

            {data && (
              <>
                <div className="intro-banner">
                  <div className="intro-banner-text">
                    <strong>How does prediction quality grow with data?</strong>{" "}
                    The same metsa fixture, subsampled at three sizes, then
                    each loaded into its own Aito DB and evaluated.
                    <span className="intro-banner-freshness">
                      {data.captured_from} · captured {data.captured_at}.
                    </span>
                  </div>
                </div>

                {/* Slider — pick a snapshot to inspect */}
                <div className="cs-tabs">
                  {data.snapshots.map((s, i) => (
                    <button
                      key={s.size}
                      type="button"
                      className={`cs-tab${i === activeIndex ? " cs-tab--active" : ""}`}
                      onClick={() => setActiveIndex(i)}
                    >
                      <div className="cs-tab-size">{s.size.toLocaleString("fi-FI")} rows</div>
                      <div className="cs-tab-label">{s.label}</div>
                    </button>
                  ))}
                </div>

                {active && (
                  <div className="cs-snapshot">
                    <p className="cs-snapshot-blurb">{active.blurb}</p>

                    <div className="card">
                      <div className="card-head">
                        <span className="card-title">_evaluate at n = {active.size.toLocaleString("fi-FI")}</span>
                        <span className="card-meta">{active.fields.length} target fields</span>
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
                                <td className="mono" style={{ fontSize: 11, color: gain >= 0 ? "var(--green)" : "var(--red, #c54)" }}>
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
                        <strong>Reading this:</strong> the load-bearing number isn't the headline
                        accuracy — it's the <em>≥ 0.85 confidence band</em>. At 50 rows, Aito only
                        marks ~30% of cases as confident, but those predictions are right ~100% of
                        the time. At 5,000 rows the confident slice grows to ~85%, still right
                        ~95% of the time. The cold-start story isn't <em>"accuracy goes up with
                        data"</em>; it's <em>"the share of cases Aito will auto-approve grows,
                        while accuracy within that slice stays near-perfect."</em>
                      </div>
                    </div>
                  </div>
                )}

                {/* Side-by-side comparison */}
                <div className="card" style={{ marginTop: 16 }}>
                  <div className="card-head">
                    <span className="card-title">Curve at a glance</span>
                    <span className="card-meta">all snapshots, average across fields</span>
                  </div>
                  <div className="cs-curve">
                    {data.snapshots.map((s) => {
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

                <div style={{ marginTop: 14, fontSize: 11, color: "var(--mid)", lineHeight: 1.6 }}>
                  {data.note}
                </div>
              </>
            )}
          </div>
          <AitoPanel config={PANEL} />
        </div>
      </main>
    </>
  );
}

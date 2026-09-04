"use client";

import { useCallback, useEffect, useState } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import { apiFetch } from "@/lib/api";
import { useTenant } from "@/lib/tenant-context";
import type {
  AitoPanelConfig,
  MatchBatchResponse,
  MatchCandidate,
  MatchedLine,
} from "@/lib/types";

const DEFAULT_PANEL: AitoPanelConfig = {
  operation: "_predict",
  endpoints: ["_predict"],
  stats: [
    { label: "Table", value: "invoice_lines" },
    { label: "Target", value: "sku → products" },
    { label: "Training", value: "none" },
  ],
  description:
    "A purchase invoice arrives with one row per product and no product " +
    "id. The supplier wrote the line in their own words — their order, " +
    "their language, often their own article number — and somebody has " +
    "to say which catalogue row it means. <em>aito.._predict</em> on " +
    "<em>sku</em> asks the labelled history: given a line that reads " +
    "like this, from a supplier like this, at a price like this, which " +
    "catalogue row did people pick? <em>sku</em> is a link, so one call " +
    "returns the ranking <em>and</em> the matched product's own columns. " +
    "No mapping table, no model, no training step — the rows were " +
    "inserted and the prediction is a query.",
  query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"invoice_lines"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"description"</span>: <span class="q-v">"PESUAINE 5L PYYKKI"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"billing_supplier"</span>: <span class="q-v">"Uusi Kanava Oy"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"unit_of_measure"</span>: <span class="q-v">"L"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"unit_price_eur"</span>: <span class="q-n">47.55</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"sku"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"limit"</span>: <span class="q-n">5</span><br/>
}<br/>
<br/>
<span class="q-d">// sku links to products.sku, so each hit carries</span><br/>
<span class="q-d">// the catalogue row's name, category and price.</span>`,
  links: [
    { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
    {
      label: "Source code",
      url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/src/matching_service.py",
      kind: "github",
    },
  ],
};

/** Three outcomes, not two. A pick the catalogue calls the same thing
 *  as the right answer is not a miss anything could have avoided, and
 *  showing it as a red cross overstates the failure the same way
 *  counting it as a hit would overstate the success. */
function outcomeMark(line: MatchedLine): string {
  if (line.correct == null) return "";
  if (line.correct) return "✓";
  return line.same_name ? "≈" : "✗";
}

function outcomeClass(line: MatchedLine): string {
  if (line.correct) return "mt-ok";
  return line.same_name ? "mt-same" : "mt-bad";
}

function outcomeTitle(line: MatchedLine): string {
  if (line.correct == null) return "";
  if (line.correct) return `Exactly right: ${line.truth}`;
  if (line.same_name) {
    return `A different SKU (${line.truth}) that the catalogue also calls ` +
      `"${line.truth_name}". Nothing in the data separates the two.`;
  }
  return `The right answer was ${line.truth}${line.truth_name ? ` — ${line.truth_name}` : ""}`;
}

function pct(p: number | null | undefined, digits = 0): string {
  if (p == null) return "—";
  return `${(p * 100).toFixed(digits)}%`;
}

/** Chips carry provenance. Aito's own evidence, evidence it weighed
 *  AGAINST the row, and facts computed here that the database never
 *  argued — painting the three alike would credit Aito with reasoning
 *  it did not do. */
function chipClass(kind: string): string {
  if (kind === "aito") return "pl-chip pl-chip-aito";
  if (kind === "against") return "pl-chip pl-chip-warn";
  return "pl-chip pl-chip-match";
}

function Candidate({ c, rank, truth }: {
  c: MatchCandidate; rank: number; truth: string | null;
}) {
  const isTruth = truth != null && c.sku === truth;
  return (
    <div className={`mt-cand${isTruth ? " mt-cand-truth" : ""}`}>
      <div className="mt-cand-top">
        <span className="mt-cand-rank">{rank}</span>
        <span className="mt-cand-name">{c.name || c.sku}</span>
        <span className="mono mt-cand-sku">{c.sku}</span>
        <span className="mt-cand-p">{pct(c.p, 1)}</span>
      </div>
      <div className="pl-chips">
        {c.reasons.map((r, i) => (
          <span key={`${r.field}-${i}`} className={chipClass(r.kind)}
                title={r.lift != null ? `lift ×${r.lift.toFixed(1)}` : "computed here, not by Aito"}>
            {r.kind === "against" ? "− " : ""}{r.text}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function MatchingPage() {
  const { tenantId } = useTenant();
  const [data, setData] = useState<MatchBatchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(true);
  const [size, setSize] = useState(30);
  const [workers, setWorkers] = useState(8);
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [panel, setPanel] = useState<AitoPanelConfig>(DEFAULT_PANEL);

  const run = useCallback((nextOffset: number) => {
    setRunning(true);
    setError(null);
    apiFetch<MatchBatchResponse>(
      `/api/matching/batch?size=${size}&workers=${workers}&offset=${nextOffset}`,
    )
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setRunning(false));
  }, [size, workers]);

  useEffect(() => { run(0); }, [tenantId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!data?.batch) return;
    const b = data.batch;
    setPanel({
      ...DEFAULT_PANEL,
      stats: [
        { label: "Batch", value: `${b.n} lines` },
        { label: "Throughput", value: `${b.rows_per_s}/s` },
        { label: "Aito median", value: `${b.server_ms_median} ms` },
      ],
    });
  }, [data]);

  const onRow = (line: MatchedLine) => {
    setOpen(open === line.line_id ? null : line.line_id);
    const top = line.candidates[0];
    setPanel({
      ...DEFAULT_PANEL,
      stats: [
        { label: "Top candidate", value: top ? pct(top.p, 1) : "—" },
        { label: "Supplier", value: line.cold ? "never seen" : "in history" },
        { label: "Round trip", value: `${line.ms} ms` },
      ],
      description:
        `<em>${line.billing_supplier}</em> wrote this line as ` +
        `<em>${line.description}</em>. ` +
        (line.cold
          ? "This supplier appears <em>nowhere</em> in the loaded history, so " +
            "there is no identifier to look up and no past line of theirs to " +
            "copy. Everything below came from the text and the numbers " +
            "against the catalogue's own metadata. "
          : "Aito has seen this supplier's lines before, so their way of " +
            "writing a description is itself evidence. ") +
        `The shortlist is five catalogue rows ranked by ` +
        `<em>P(sku | line)</em>; the teal chips are the terms Aito's ` +
        `<em>$why</em> named as evidence, the gold ones are agreements ` +
        `computed here that the database never argued.`,
    });
  };

  const b = data?.batch;
  const m = data?.measured;

  return (
    <>
      <Nav />
      <div className="main">
        <TopBar title="Invoice Matching" breadcrumb="Product" />
        <div className="content-area">
          <div className="content">
            {error && (
              <ErrorState message={error} command="GET /api/matching/batch" />
            )}
            {!error && data && data.available === 0 && (
              <div className="card">
                <div className="card-head">
                  <div className="card-title">No invoice lines for this profile</div>
                  <div className="card-meta">
                    The matching case is built on Aurora Retail's 3200-SKU
                    catalogue. Switch profile in the top bar to see it.
                  </div>
                </div>
              </div>
            )}
            {!error && (!data || data.available > 0) && (
              <>
                <div className="kpi-row">
                  <div className="kpi">
                    <div className="kpi-label">Queue</div>
                    <div className="kpi-val">{data?.available ?? "—"}</div>
                    <div className="kpi-sub">lines waiting, none of them loaded</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">This run</div>
                    <div className="kpi-val">
                      {b ? `${b.rows_per_s}/s` : "—"}
                    </div>
                    <div className="kpi-sub">
                      {b ? `${b.n} lines in ${b.wall_s}s at ${b.workers} workers` : "…"}
                    </div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Aito server time</div>
                    <div className="kpi-val">
                      {b ? `${b.server_ms_median} ms` : "—"}
                    </div>
                    <div className="kpi-sub">median per line, shared instance</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Right on this batch</div>
                    <div className="kpi-val">
                      {b?.top1 != null ? pct(b.top1) : "—"}
                    </div>
                    <div className="kpi-sub">
                      top-1 · {b?.top5 != null ? pct(b.top5) : "—"} in the top five
                    </div>
                  </div>
                </div>

                <div className="card">
                  <div className="card-head">
                    <div className="card-title">The batch</div>
                    <div className="card-meta">
                      Invoice lines arrive as documents, overnight and in bulk.
                      The unit of work is the queue, not the line.
                    </div>
                  </div>
                  <div className="mt-controls">
                    <label className="mt-ctl">
                      <span>lines</span>
                      <select value={size} disabled={running}
                              onChange={(e) => setSize(Number(e.target.value))}>
                        {[10, 20, 30, 50].map((n) => (
                          <option key={n} value={n}>{n}</option>
                        ))}
                      </select>
                    </label>
                    <label className="mt-ctl">
                      <span>workers</span>
                      <select value={workers} disabled={running}
                              onChange={(e) => setWorkers(Number(e.target.value))}>
                        {[1, 2, 4, 8, 12].map((n) => (
                          <option key={n} value={n}>{n}</option>
                        ))}
                      </select>
                    </label>
                    <button className="btn btn-primary" disabled={running}
                            onClick={() => { const next = offset + size; setOffset(next); run(next); }}>
                      {running ? "Running…" : "Run next batch"}
                    </button>
                    {b && (
                      <span className="mt-rate">
                        {b.prefilled} pre-filled · {b.open} left open
                        {b.prefill_precision != null &&
                          ` · ${pct(b.prefill_precision)} of the pre-filled ones right`}
                      </span>
                    )}
                  </div>
                  {b && (
                    <div className="mt-note">
                      At this rate a single client would clear{" "}
                      <strong>{(b.rows_per_week / 1000).toFixed(0)}k lines a week</strong>.
                      That is a worker-count and instance-sizing figure, not an
                      algorithmic one — this demo runs against a shared
                      multi-tenant Aito from a laptop, so both the round trip and
                      the contention are worse here than they would be co-located.
                    </div>
                  )}
                </div>

                <div className="card card-overflow">
                  <div className="card-head">
                    <div className="card-title">Lines</div>
                    <div className="card-meta">
                      Click a line for the shortlist and the evidence.
                      <strong> ✓</strong> exact, <strong>≈</strong> a different
                      SKU the catalogue calls the same thing,{" "}
                      <strong>✗</strong> wrong — scored against the held-out
                      label. A real queue has no truth column, and a demo that
                      hides the one it has is asking to be trusted.
                    </div>
                  </div>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Billing supplier</th>
                        <th>Line as the supplier wrote it</th>
                        <th>Best catalogue match</th>
                        <th style={{ textAlign: "right" }}>P</th>
                        <th>Clerk sees</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {(data?.lines ?? []).map((line) => {
                        const top = line.candidates[0];
                        return [
                          <tr key={line.line_id} className="clickable"
                              onClick={() => onRow(line)}>
                            <td>
                              {line.billing_supplier}
                              {line.cold && (
                                <span className="badge b-purple mt-cold" title="This supplier appears nowhere in the loaded history">
                                  cold
                                </span>
                              )}
                            </td>
                            <td className="mono mt-desc">{line.description}</td>
                            <td>{top ? top.name || top.sku : <span className="pl-unknown">no candidate</span>}</td>
                            <td style={{ textAlign: "right" }}>{top ? pct(top.p, 1) : "—"}</td>
                            <td>
                              <span className={`badge ${line.decision === "prefilled" ? "b-green" : "b-gray"}`}>
                                {line.decision === "prefilled" ? "pre-filled" : "open"}
                              </span>
                            </td>
                            <td className={outcomeClass(line)} title={outcomeTitle(line)}>
                              {outcomeMark(line)}
                            </td>
                          </tr>,
                          open === line.line_id && (
                            <tr key={`${line.line_id}-open`} className="mt-open-row">
                              <td colSpan={6}>
                                <div className="mt-shortlist">
                                  {line.candidates.map((c, i) => (
                                    <Candidate key={c.sku} c={c} rank={i + 1}
                                               truth={line.truth} />
                                  ))}
                                  {line.truth &&
                                   !line.candidates.some((c) => c.sku === line.truth) && (
                                    <div className="mt-miss">
                                      The right answer ({line.truth}) is not in the
                                      top five. Where the description keeps almost
                                      nothing of the catalogue name — an article
                                      code and an HS number — there is nothing to
                                      match on, and the confidence says so rather
                                      than guessing.
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ),
                        ];
                      })}
                    </tbody>
                  </table>
                </div>

                {m && (
                  <div className="card">
                    <div className="card-head">
                      <div className="card-title">Measured before it was demoed</div>
                      <div className="card-meta">
                        {m.n} held-out lines, {m.measured_on}. Run it yourself
                        with <span className="mono">./do match-eval</span>.
                      </div>
                    </div>
                    <div className="mt-measured">
                      <div className="mt-measure">
                        <div className="mt-measure-val">{pct(m.overall_top1, 1)}</div>
                        <div className="mt-measure-label">top-1, overall</div>
                        <div className="mt-measure-sub">
                          {pct(m.overall_top5, 1)} in the top five ·{" "}
                          {pct(m.overall_top1_name, 1)} counting rows the
                          catalogue calls the same thing
                        </div>
                      </div>
                      <div className="mt-measure mt-measure-hero">
                        <div className="mt-measure-val">{pct(m.cold_top1, 1)}</div>
                        <div className="mt-measure-label">top-1, supplier never seen</div>
                        <div className="mt-measure-sub">
                          {pct(m.cold_top5, 1)} in the top five ·{" "}
                          {pct(m.cold_top1_name, 1)} counting identical names
                        </div>
                      </div>
                      <div className="mt-measure">
                        <div className="mt-measure-val">{pct(m.baseline, 2)}</div>
                        <div className="mt-measure-label">picking at random</div>
                        <div className="mt-measure-sub">
                          1 in {m.catalogue_skus} ·{" "}
                          {Math.round(m.overall_top1 / m.baseline)}× lift ·{" "}
                          {m.throughput_rows_per_s} rows/s at{" "}
                          {m.throughput_workers} workers
                        </div>
                      </div>
                    </div>
                    <div className="mt-note">
                      The cold-start figure is on its own because it is the
                      argument. Any matcher does well on a supplier whose lines
                      it has seen a thousand times; the question a finance team
                      actually asks is what happens the first time a new
                      supplier invoices, and an overall number that averages
                      that in is a number that flatters.
                    </div>
                    <table className="tbl mt-curve">
                      <thead>
                        <tr>
                          <th>Pre-fill above</th>
                          <th style={{ textAlign: "right" }}>Lines covered</th>
                          <th style={{ textAlign: "right" }}>Top pick right</th>
                        </tr>
                      </thead>
                      <tbody>
                        {m.curve.map((row) => (
                          <tr key={row.bar}
                              className={row.bar === b?.threshold ? "selected" : ""}>
                            <td className="mono">p ≥ {row.bar.toFixed(2)}</td>
                            <td className="mono" style={{ textAlign: "right" }}>
                              {pct(row.coverage, 1)}
                            </td>
                            <td className="mono" style={{ textAlign: "right" }}>
                              {pct(row.precision, 1)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="mt-note">
                      <strong>Nothing here posts unattended, and this table is
                      why.</strong> The obvious demo is an auto-post threshold:
                      above the bar, the line books itself. Tighten the bar as
                      far as it goes and the top pick is still only right{" "}
                      {pct(m.curve[m.curve.length - 1].precision, 1)} of the
                      time — no accounts-payable team signs off on four wrong
                      lines in ten, and a demo that implies otherwise is selling
                      something this would not do in production. So the claim is
                      the smaller, real one: the <em>search</em> goes away.
                      Instead of hunting {m.catalogue_skus} rows, a clerk gets
                      five ranked candidates with the evidence attached, and for
                      a supplier already in the history the right one is among
                      them {pct(m.warm_top5, 1)} of the time.
                      <br /><br />
                      <strong>Two things this does not claim.</strong>{" "}
                      {m.note} And {pct(m.shared_name_share, 1)} of catalogue
                      rows share a name with another row — where two SKUs are
                      called the same thing nothing can separate them, which is
                      both the ceiling on the numbers above and the reason the
                      honest output is a shortlist rather than an answer.
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
          <AitoPanel config={panel} />
        </div>
      </div>
    </>
  );
}

"use client";

/**
 * Smart Entry — predictive PO form following the "smart forms" guide.
 *
 * Core principle: ONE FIELD PER SEMANTIC CONCEPT. The cost center field
 * is the same input whether the value came from a prediction or from
 * the user — only its visual state differs.
 *
 * Three field states (see SmartField component):
 *   - empty:     no value yet
 *   - predicted: value from Aito; gold + italic; clears on Esc
 *   - user:      value typed/accepted by the user; normal styling
 *
 * Submitting tags each predicted field as either user-confirmed (the user
 * tabbed through) or untouched (predicted, still styled gold). Both paths
 * write the same value to the PO; the source label is logged for telemetry.
 */

import { useEffect, useState, useRef, useCallback } from "react";
import Nav from "@/components/shell/Nav";
import TopBar from "@/components/shell/TopBar";
import AitoPanel from "@/components/shell/AitoPanel";
import ErrorState from "@/components/shell/ErrorState";
import SmartField, { FieldSource } from "@/components/prediction/SmartField";
import { apiFetch } from "@/lib/api";
import type {
  SmartEntryResponse,
  SmartEntryField,
  AitoPanelConfig,
  WhyExplanation,
  Alternative,
} from "@/lib/types";

const PREDICTABLE_FIELDS = ["cost_center", "account_code", "project", "approver"] as const;
type PredictableField = (typeof PREDICTABLE_FIELDS)[number];

const FIELD_LABELS: Record<PredictableField, string> = {
  cost_center: "Cost Center",
  account_code: "Account Code",
  project: "Project",
  approver: "Approver",
};

interface FieldState {
  value: string;
  source: FieldSource;
  confidence: number;
  why?: WhyExplanation;
  alternatives?: Alternative[];
}

const emptyField: FieldState = { value: "", source: "empty", confidence: 0 };

const defaultPanel: AitoPanelConfig = {
  operation: "_predict (multi-field)",
  endpoints: ["_predict"],
  stats: [
    { label: "Fields", value: "4" },
    { label: "Avg latency", value: "18ms" },
    { label: "Pattern", value: "one-field" },
  ],
  description:
    "Smart Entry uses <em>aito.._predict</em> with the <em>$why</em> highlight option " +
    "to fill four fields and explain each prediction. Each field is a single semantic " +
    "concept — the predicted value lives in the input itself, styled gold-italic until " +
    "the user accepts it (Tab) or overrides it (typing).",
  query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"supplier"</span>: <span class="q-v">"$supplier"</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"cost_center"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"select"</span>: [<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-v">"$p"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-v">"feature"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;{ <span class="q-k">"$why"</span>: { <span class="q-k">"highlight"</span>: { <span class="q-k">"posPreTag"</span>: <span class="q-v">"«"</span>, <span class="q-k">"posPostTag"</span>: <span class="q-v">"»"</span> } } }<br/>
&nbsp;&nbsp;]<br/>
}`,
  links: [
    { label: "_predict reference", url: "https://aito.ai/docs/api/predict" },
    { label: "$why factors", url: "https://aito.ai/docs/api/predict#why" },
  ],
};

export default function SmartEntryPage() {
  const [suppliers, setSuppliers] = useState<string[]>([]);
  const [supplier, setSupplier] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");

  // One state object per predictable field — the single source of truth.
  const [fields, setFields] = useState<Record<PredictableField, FieldState>>({
    cost_center: emptyField,
    account_code: emptyField,
    project: emptyField,
    approver: emptyField,
  });

  const [predicting, setPredicting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, setLoading] = useState(true);
  const [panel, setPanel] = useState<AitoPanelConfig>(defaultPanel);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState<{ purchase_id: string } | null>(null);

  // Cross-highlight: which input fields contributed to the open explanation?
  const [highlightedInputs, setHighlightedInputs] = useState<Set<string>>(new Set());

  // Compare-to-traditional toggle. Off mode skips the prediction
  // round-trip; the user has to type all four PO fields by hand —
  // the way every other ERP does it. Stopwatch + per-mode best-time
  // panel let visitors *see* the time difference, not just hear about it.
  const [predictionsEnabled, setPredictionsEnabled] = useState(true);
  const [stopwatchStart, setStopwatchStart] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);  // seconds, frozen at completion
  const [bestTimes, setBestTimes] = useState<{ withPredictions?: number; traditional?: number }>({});

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    apiFetch<{ suppliers: string[] }>("/api/smartentry/suppliers")
      .then((res) => setSuppliers(res.suppliers))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  /**
   * Fetch predictions and merge them into field state.
   *
   * Critical rule: never overwrite a field whose source is "user". The user
   * has committed; we only fill empty fields and refresh predicted ones.
   */
  const fetchPredictions = useCallback(
    (sup: string, desc: string, amt: string) => {
      if (!sup) return;
      setPredicting(true);

      apiFetch<SmartEntryResponse>("/api/smartentry/predict", {
        method: "POST",
        body: JSON.stringify({
          supplier: sup,
          description: desc,
          amount: parseFloat(amt) || 0,
        }),
      })
        .then((res) => {
          setFields((prev) => {
            const next = { ...prev };
            for (const f of res.fields) {
              const fieldName = f.field as PredictableField;
              if (!PREDICTABLE_FIELDS.includes(fieldName)) continue;
              const existing = next[fieldName];
              // Don't overwrite user-confirmed values
              if (existing.source === "user") continue;
              next[fieldName] = {
                value: f.value,
                source: f.value ? "predicted" : "empty",
                confidence: f.confidence,
                why: f.why,
                alternatives: f.alternatives,
              };
            }
            return next;
          });

          // Update Aito panel with summary
          const fieldSummaries = res.fields.map((f) => {
            const lifts = f.why?.lifts?.length ?? 0;
            return `<em>${f.field}</em>: <strong>${f.value}</strong> (${Math.round(f.confidence * 100)}%, ${lifts} pattern${lifts === 1 ? "" : "s"})`;
          }).join("<br/>");
          setPanel({
            ...defaultPanel,
            stats: [
              { label: "Predicted", value: `${res.predicted_count}` },
              { label: "Avg conf.", value: `${Math.round(res.avg_confidence * 100)}%` },
              { label: "Pattern", value: "one-field" },
            ],
            description:
              `Predictions for <em>${sup}</em>:<br/>${fieldSummaries}<br/><br/>` +
              `Click the <strong>?</strong> on any field to see the full $why decomposition.`,
          });
        })
        .catch((e) => setError(e.message))
        .finally(() => setPredicting(false));
    },
    [],
  );

  // Debounced refetch on context change
  const scheduleRefetch = useCallback(
    (sup: string, desc: string, amt: string) => {
      if (!predictionsEnabled) return;
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => fetchPredictions(sup, desc, amt), 300);
    },
    [fetchPredictions, predictionsEnabled],
  );

  const handleSupplierChange = (value: string) => {
    setSupplier(value);
    // Stopwatch starts on supplier pick (the first non-trivial action).
    if (value && stopwatchStart === null) setStopwatchStart(Date.now());
    if (value) scheduleRefetch(value, description, amount);
  };
  const handleDescriptionChange = (value: string) => {
    setDescription(value);
    if (supplier) scheduleRefetch(supplier, value, amount);
  };
  const handleAmountChange = (value: string) => {
    setAmount(value);
    if (supplier) scheduleRefetch(supplier, description, value);
  };

  /** Toggle prediction mode. Clears all field values (otherwise
   *  switching off would leave the gold-styled predictions stuck on
   *  screen, defeating the comparison) and resets the stopwatch so
   *  the next attempt is timed fresh. */
  const togglePredictions = () => {
    setPredictionsEnabled((v) => !v);
    setFields({
      cost_center: emptyField,
      account_code: emptyField,
      project: emptyField,
      approver: emptyField,
    });
    setStopwatchStart(null);
    setElapsed(null);
    setSubmitted(null);
  };

  /** Field-level handlers. Each accepts (newValue, source) — we always
   * trust what SmartField tells us about the source transition. */
  const setField = (name: PredictableField, value: string, source: "user") => {
    setFields((prev) => ({
      ...prev,
      [name]: {
        ...prev[name],
        value,
        source,
        // Clear confidence on user override — they own it now.
        confidence: source === "user" ? 1.0 : prev[name].confidence,
      },
    }));
  };

  const rejectField = (name: PredictableField) => {
    setFields((prev) => ({ ...prev, [name]: emptyField }));
  };

  const canSubmit =
    !!supplier && !!description && !!amount &&
    PREDICTABLE_FIELDS.every((f) => !!fields[f].value);

  // Stop the stopwatch the moment the form first becomes complete —
  // this is the comparable "time to ready-to-submit" number for both
  // modes. Don't restart on subsequent edits; the demo's claim is
  // about how long it took to *get here*, not how long the user
  // dawdles before clicking submit.
  useEffect(() => {
    if (canSubmit && stopwatchStart !== null && elapsed === null) {
      const taken = (Date.now() - stopwatchStart) / 1000;
      setElapsed(taken);
      setBestTimes((prev) => {
        const key = predictionsEnabled ? "withPredictions" : "traditional";
        // Keep the *best* time per mode so a slow user doesn't
        // overwrite a faster reading from a previous attempt.
        if (prev[key] !== undefined && prev[key]! < taken) return prev;
        return { ...prev, [key]: taken };
      });
    }
  }, [canSubmit, stopwatchStart, elapsed, predictionsEnabled]);

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitted(null);
    try {
      const body: Record<string, unknown> = {
        supplier,
        description,
        amount_eur: parseFloat(amount) || 0,
        source: "smart_entry",
        // Per-field source tracking for telemetry — what the user confirmed
        // vs what was accepted as predicted.
        _field_sources: Object.fromEntries(
          PREDICTABLE_FIELDS.map((f) => [f, fields[f].source]),
        ),
      };
      for (const f of PREDICTABLE_FIELDS) {
        body[f] = fields[f].value;
      }
      const res = await apiFetch<{ purchase_id: string }>("/api/po/submit", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setSubmitted({ purchase_id: res.purchase_id });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleClear = () => {
    setSupplier("");
    setDescription("");
    setAmount("");
    setDate("");
    setFields({
      cost_center: emptyField,
      account_code: emptyField,
      project: emptyField,
      approver: emptyField,
    });
    setHighlightedInputs(new Set());
    setSubmitted(null);
    setPanel(defaultPanel);
    setStopwatchStart(null);
    setElapsed(null);
  };

  const haveBoth = bestTimes.withPredictions !== undefined && bestTimes.traditional !== undefined;
  const speedupX = haveBoth
    ? (bestTimes.traditional! / bestTimes.withPredictions!).toFixed(1)
    : null;

  // Cross-highlight: when SmartField's popover opens, it tells us which
  // $context fields contributed. We outline those input fields.
  const handleContextFields = (fields: Set<string>) => {
    setHighlightedInputs(fields);
  };

  return (
    <>
      <Nav />
      <main className="main">
        <TopBar
          breadcrumb="Procurement"
          title="Smart Entry"
          subtitle="One field per concept · Tab to accept · Esc to reject"
        />
        <div className="content-area">
          <div className="content">
            {error && <ErrorState message={error} command="POST /api/smartentry/predict" />}

            <div className="intro-banner">
              <div className="intro-banner-text">
                <strong>One field per concept.</strong> Predictions appear in the field itself
                — gold + italic until you accept (Tab) or override (type). Click <strong>?</strong>
                on any field to see why, with the contributing input fields outlined in purple.
                <span className="intro-banner-freshness">
                  Submit anything below — the next prediction reflects it on the spot. No retrain.
                </span>
              </div>
            </div>

            {/* Compare-to-traditional toggle + per-attempt timer.
                Off mode disables the prediction round-trip so visitors
                can feel how long the form takes without Aito. The
                stopwatch + side-by-side panel land the value-prop in
                a single demo cycle. */}
            <div className="se-mode-bar">
              <div className="se-mode-toggle">
                <span className={`se-mode-label${predictionsEnabled ? " se-mode-label--active" : ""}`}>
                  ✨ With aito.. predictions
                </span>
                <button
                  type="button"
                  className={`se-mode-switch${predictionsEnabled ? " se-mode-switch--on" : ""}`}
                  onClick={togglePredictions}
                  role="switch"
                  aria-checked={predictionsEnabled}
                  aria-label="Toggle predictions"
                >
                  <span className="se-mode-thumb" />
                </button>
                <span className={`se-mode-label${!predictionsEnabled ? " se-mode-label--active" : ""}`}>
                  Traditional (type each field)
                </span>
              </div>

              <div className="se-mode-times">
                {elapsed !== null && (
                  <span className="se-mode-elapsed">
                    {predictionsEnabled ? "✨ With" : "Traditional"}: <strong>{elapsed.toFixed(1)}s</strong>
                  </span>
                )}
                {bestTimes.withPredictions !== undefined && (
                  <span className="se-mode-best">
                    ✨ best: <strong>{bestTimes.withPredictions.toFixed(1)}s</strong>
                  </span>
                )}
                {bestTimes.traditional !== undefined && (
                  <span className="se-mode-best">
                    Traditional best: <strong>{bestTimes.traditional.toFixed(1)}s</strong>
                  </span>
                )}
                {haveBoth && speedupX && (
                  <span className="se-mode-speedup">
                    aito.. is <strong>{speedupX}× faster</strong>
                  </span>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card-head">
                <span className="card-title">New Purchase Order</span>
                <span className="card-meta">
                  {!predictionsEnabled
                    ? "Predictions OFF — type all four fields manually"
                    : predicting
                      ? "Predicting…"
                      : supplier ? "Live predictions" : "Awaiting supplier"}
                </span>
              </div>
              <div style={{ padding: 16 }}>
                {/* Context inputs — drive the predictions */}
                <div className="form-grid fg-2" style={{ marginBottom: 18 }}>
                  <div
                    className={`form-group${highlightedInputs.has("supplier") ? " sf-highlighted" : ""}`}
                    style={{ padding: 4, margin: -4, borderRadius: 5 }}
                  >
                    <label className="form-label">Supplier</label>
                    <select
                      className="form-select"
                      value={supplier}
                      onChange={(e) => handleSupplierChange(e.target.value)}
                    >
                      <option value="">Select supplier…</option>
                      {suppliers.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                  <div
                    className={`form-group${highlightedInputs.has("description") ? " sf-highlighted" : ""}`}
                    style={{ padding: 4, margin: -4, borderRadius: 5 }}
                  >
                    <label className="form-label">Description</label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="Enter PO description…"
                      value={description}
                      onChange={(e) => handleDescriptionChange(e.target.value)}
                    />
                  </div>
                  <div
                    className={`form-group${highlightedInputs.has("amount_eur") ? " sf-highlighted" : ""}`}
                    style={{ padding: 4, margin: -4, borderRadius: 5 }}
                  >
                    <label className="form-label">Amount (€)</label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="0.00"
                      value={amount}
                      onChange={(e) => handleAmountChange(e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Date</label>
                    <input
                      type="date"
                      className="form-input"
                      value={date}
                      onChange={(e) => setDate(e.target.value)}
                    />
                  </div>
                </div>

                {/* Predicted fields — same input, three states */}
                <div className="form-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
                  {PREDICTABLE_FIELDS.map((f) => (
                    <SmartField
                      key={f}
                      label={FIELD_LABELS[f]}
                      fieldName={f}
                      value={fields[f].value}
                      source={fields[f].source}
                      confidence={fields[f].confidence}
                      why={fields[f].why}
                      alternatives={fields[f].alternatives}
                      onChange={(v, src) => setField(f, v, src)}
                      onReject={() => rejectField(f)}
                      onContextFieldsChange={handleContextFields}
                      placeholder={supplier ? "—" : "select supplier first"}
                    />
                  ))}
                </div>

                {/* Submit / clear */}
                <div style={{ display: "flex", gap: 10, marginTop: 22, alignItems: "center" }}>
                  <button
                    className="btn btn-primary"
                    onClick={handleSubmit}
                    disabled={!canSubmit || submitting}
                    style={{ minWidth: 200 }}
                  >
                    {submitting ? "Submitting…" : "Submit for approval →"}
                  </button>
                  <button
                    className="btn btn-ghost"
                    onClick={handleClear}
                    disabled={submitting}
                  >
                    Clear
                  </button>
                  {submitted && (
                    <div className="relearn-banner" style={{ marginBottom: 0 }}>
                      <span className="relearn-pulse" />
                      <div className="relearn-text">
                        <strong>Saved as {submitted.purchase_id}.</strong>{" "}
                        aito.. just learned from this — next prediction for{" "}
                        <em>{supplier}</em> reflects what you submitted, no batch retrain.
                        It also appears in <a href="/po-queue">PO Queue</a> and{" "}
                        <a href="/approval">Approval Routing</a>.
                      </div>
                    </div>
                  )}
                  {!canSubmit && !submitted && (
                    <div style={{ fontSize: 11, color: "var(--mid)" }}>
                      Fill all four predicted fields (or accept the suggestions) to enable submit
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
          <AitoPanel config={panel} />
        </div>
      </main>
    </>
  );
}

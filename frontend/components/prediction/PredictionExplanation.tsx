"use client";

import { Alternative, WhyExplanation } from "@/lib/types";
import { HighlightedText } from "./HighlightedText";

/** Pure component — no fetching, no popover wrapper. Renders:
 *   1. Prediction value + confidence bar
 *   2. Base probability
 *   3. Top 3-5 pattern matches with token highlighting + lift
 *   4. The multiplicative chain
 *   5. Top alternatives
 *
 * Lives inside Pattern A (inline panel), B (side panel), or C (popover) —
 * the wrapper decides positioning, this component just renders content.
 */
export interface PredictionExplanationProps {
  value: string;
  confidence: number;
  why?: WhyExplanation;
  alternatives?: Alternative[];
  onSelectAlternative?: (alt: Alternative) => void;
}

function fmtP(p: number): string {
  if (p >= 0.001) return `${(p * 100).toFixed(1)}%`;
  return `${(p * 100).toFixed(2)}%`;
}

function fmtLift(lift: number): string {
  if (lift >= 1) return `× ${lift.toFixed(1)}`;
  return `× ${lift.toFixed(2)}`;
}

function liftClass(lift: number): string {
  if (lift > 1.5) return "lift-strong";
  if (lift < 0.7) return "lift-down";
  return "lift-mid";
}

function confColor(p: number): string {
  if (p >= 0.85) return "var(--green)";
  if (p >= 0.50) return "var(--gold)";
  return "var(--red)";
}

export default function PredictionExplanation({
  value,
  confidence,
  why,
  alternatives,
  onSelectAlternative,
}: PredictionExplanationProps) {
  const lifts = why?.lifts ?? [];
  const baseP = why?.base_p ?? 0;
  const normalizer = why?.normalizer;

  const isLow = confidence < 0.5;

  return (
    <div className="why-explanation">
      {/* 1. Prediction + confidence */}
      <div className="why-prediction-row">
        <div>
          <div style={{ fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--mid)" }}>
            Predicted value
          </div>
          <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 22, lineHeight: 1.1, marginTop: 2 }}>
            {value || "—"}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 16, fontWeight: 600, color: confColor(confidence) }}>
            {fmtP(confidence)}
          </div>
          <div style={{ fontSize: 9.5, color: "var(--mid)", marginTop: 1 }}>confidence</div>
        </div>
      </div>
      <div className="conf-track" style={{ marginTop: 8, marginBottom: 14 }}>
        <div className="conf-fill" style={{ width: `${Math.round(confidence * 100)}%`, background: confColor(confidence) }} />
      </div>

      {/* P3 #18: low-confidence case — explain the situation and what to do */}
      {isLow && (
        <div style={{
          padding: "8px 10px",
          background: "var(--red-light)",
          borderRadius: 4,
          fontSize: 11,
          color: "var(--red)",
          marginBottom: 12,
          lineHeight: 1.5,
        }}>
          <strong>Low confidence — review needed.</strong>{" "}
          {lifts.length === 0
            ? "There's little similar history to learn from. Your decision becomes a training signal — future predictions will improve."
            : "The model has signal but it's split across alternatives. Pick from the list below or override; either way, the system learns."}
        </div>
      )}

      {/* 2. Base probability */}
      {baseP > 0 && (
        <div className="why-section">
          <div className="why-section-label">Base rate</div>
          <div className="why-section-body">
            <span className="mono" style={{ color: "var(--mid)" }}>{fmtP(baseP)}</span>{" "}
            <span style={{ fontSize: 11, color: "var(--mid)" }}>
              — historical share of <strong>{value}</strong> across all transactions
            </span>
          </div>
        </div>
      )}

      {/* 3. Pattern matches */}
      {lifts.length > 0 && (
        <div className="why-section">
          <div className="why-section-label">Pattern matches ({lifts.length})</div>
          <div className="why-section-body">
            {lifts.map((l, i) => (
              <div key={i} className="why-lift-row">
                <div className="why-lift-tokens">
                  {l.highlights.length > 0 ? (
                    l.highlights.map((h, j) => (
                      <span key={j} className="why-token">
                        <span className="why-token-field">{h.field}:</span>{" "}
                        <HighlightedText text={h.html} />
                      </span>
                    ))
                  ) : (
                    <span className="why-token-fallback">{l.proposition_str}</span>
                  )}
                </div>
                <div className={`why-lift-value ${liftClass(l.lift)}`}>{fmtLift(l.lift)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4. Multiplicative chain */}
      {(baseP > 0 && lifts.length > 0) && (
        <div className="why-section">
          <div className="why-section-label">Math</div>
          <div className="why-math">
            <span className="mono">{fmtP(baseP)}</span>
            {lifts.map((l, i) => (
              <span key={i}>
                {" "}<span style={{ color: "var(--mid)" }}>×</span>{" "}
                <span className={`mono ${liftClass(l.lift)}`}>{l.lift.toFixed(2)}</span>
              </span>
            ))}
            {normalizer != null && (
              <span>
                {" "}<span style={{ color: "var(--mid)" }}>×</span>{" "}
                <span className="mono" style={{ color: "var(--mid)" }} title="Normalizer (correction)">
                  {normalizer.toFixed(2)}
                </span>
              </span>
            )}
            {" "}<span style={{ color: "var(--mid)" }}>=</span>{" "}
            <span className="mono" style={{ color: confColor(confidence), fontWeight: 600 }}>
              {fmtP(confidence)}
            </span>
          </div>
        </div>
      )}

      {/* 5. Alternatives */}
      {alternatives && alternatives.length > 0 && (
        <div className="why-section">
          <div className="why-section-label">Alternatives</div>
          <div className="why-section-body">
            {alternatives.map((alt, i) => (
              <button
                key={i}
                className="why-alt-row"
                onClick={() => onSelectAlternative?.(alt)}
                disabled={!onSelectAlternative}
              >
                <span style={{ flex: 1, textAlign: "left" }}>{alt.value || "—"}</span>
                <span className="conf-track" style={{ width: 60 }}>
                  <span className="conf-fill" style={{ width: `${Math.round(alt.confidence * 100)}%`, background: confColor(alt.confidence) }} />
                </span>
                <span className="mono" style={{ width: 48, textAlign: "right", fontSize: 10.5 }}>
                  {fmtP(alt.confidence)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {(!why || (baseP === 0 && lifts.length === 0)) && (
        <div style={{ fontSize: 11, color: "var(--mid)", fontStyle: "italic", padding: 8 }}>
          No detailed explanation available — this prediction was made with insufficient context for factor decomposition.
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { AITO_CALLS_EVENT, type AitoCall, type AitoCallsEvent } from "@/lib/api";

const WINDOW = 30;

interface Sample {
  ms: number;        // total ms across every Aito call in the request
  calls: AitoCall[]; // per-call breakdown — drives the popover detail list
  path: string;
  at: number;
}

function fmtMs(ms: number): string {
  if (ms < 10) return ms.toFixed(1) + "ms";
  if (ms < 1000) return Math.round(ms) + "ms";
  return (ms / 1000).toFixed(2) + "s";
}

function pct(samples: number[], q: number): number {
  if (samples.length === 0) return 0;
  const sorted = [...samples].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * q));
  return sorted[idx];
}

function endpointColor(op: string): string {
  // Cluster colours per Aito operation so the same op is recognisable
  // at a glance. Matches the accounting-demo palette.
  if (op.startsWith("_predict"))   return "#6ab87a";
  if (op.startsWith("_relate"))    return "#9870d8";
  if (op.startsWith("_recommend")) return "#5a9ad8";
  if (op.startsWith("_search"))    return "#d4a030";
  if (op.startsWith("_evaluate"))  return "#d06060";
  if (op.startsWith("_match"))     return "#12B5AD";
  return "#a89848";
}

/**
 * Persistent topbar badge: live Aito round-trip latency. Subscribes
 * to the `aito:calls` event, sums per-call ms into a per-request
 * sample, keeps a rolling 30-sample window.
 *
 * Visible label: the most recent request's total ms.
 * Hover popover: min / p50 / p95 / avg across the window, plus the
 * full per-call breakdown of the most recent request — colour-coded
 * by op (`_predict` green, `_relate` purple, `_search` gold, …).
 *
 * This is the only latency surface in the demo: a single topbar pill
 * with all the detail in its hover, mirroring the accounting demo's
 * `LatencyBadge`. Cache hits are skipped on purpose — the badge
 * tracks real Aito work, not warmups.
 */
export default function LatencyBadge() {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [hover, setHover] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<AitoCallsEvent>).detail;
      if (detail.cached || detail.calls.length === 0) return;
      const ms = detail.calls.reduce((s, c) => s + c.ms, 0);
      setSamples((prev) => {
        const next = [...prev, {
          ms,
          calls: detail.calls,
          path: detail.path,
          at: Date.now(),
        }];
        if (next.length > WINDOW) next.splice(0, next.length - WINDOW);
        return next;
      });
    };
    window.addEventListener(AITO_CALLS_EVENT, handler);
    return () => window.removeEventListener(AITO_CALLS_EVENT, handler);
  }, []);

  if (samples.length === 0) return null;

  const last = samples[samples.length - 1];
  const ms = samples.map((s) => s.ms);
  const min = Math.min(...ms);
  const p50 = pct(ms, 0.5);
  const p95 = pct(ms, 0.95);
  const avg = ms.reduce((a, b) => a + b, 0) / ms.length;

  return (
    <span
      ref={ref}
      className="latency-badge"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title="Live Aito round-trip latency"
    >
      <span className="latency-badge-dot" aria-hidden="true" />
      <span>aito {fmtMs(last.ms)}</span>
      {last.calls.length > 1 && (
        <span className="latency-badge-count">×{last.calls.length}</span>
      )}
      {hover && (
        <span className="latency-badge-tooltip" role="tooltip">
          <span className="latency-badge-tooltip-title">
            Last {samples.length} Aito requests
          </span>
          <span className="latency-badge-stats">
            <span className="latency-badge-stat-label">min</span>
            <span className="latency-badge-stat-val">{fmtMs(min)}</span>
            <span className="latency-badge-stat-label">p50</span>
            <span className="latency-badge-stat-val">{fmtMs(p50)}</span>
            <span className="latency-badge-stat-label">p95</span>
            <span className="latency-badge-stat-val">{fmtMs(p95)}</span>
            <span className="latency-badge-stat-label">avg</span>
            <span className="latency-badge-stat-val">{fmtMs(avg)}</span>
            <span className="latency-badge-stat-label">last</span>
            <span className="latency-badge-stat-val">
              {fmtMs(last.ms)}
              {last.calls.length > 1 && (
                <span className="latency-badge-stat-aside">
                  ({last.calls.length} calls)
                </span>
              )}
            </span>
          </span>

          {/* Per-call breakdown for the most-recent request — what the
              bottom-left ticker used to show, now lives inside the
              topbar's hover popover. Cap at 12 entries so a generated
              project plan (~140 calls) doesn't unfurl forever. */}
          {last.calls.length > 0 && (
            <>
              <span className="latency-badge-divider" aria-hidden="true" />
              <span className="latency-badge-subtitle">
                Last request — {last.path}
              </span>
              <span className="latency-badge-calls">
                {last.calls.slice(0, 12).map((c, i) => (
                  <span key={i} className="latency-badge-call">
                    <span
                      className="latency-badge-call-dot"
                      style={{ background: endpointColor(c.endpoint) }}
                    />
                    <span
                      className="latency-badge-call-op"
                      style={{ color: endpointColor(c.endpoint) }}
                    >
                      {c.endpoint}
                    </span>
                    <span className="latency-badge-call-ms">{fmtMs(c.ms)}</span>
                  </span>
                ))}
                {last.calls.length > 12 && (
                  <span className="latency-badge-call-more">
                    +{last.calls.length - 12} more
                  </span>
                )}
              </span>
            </>
          )}

          <span className="latency-badge-tooltip-foot">
            Round-trip ms server→Aito→server, recorded by httpx and
            shipped via the <code>X-Aito-Calls</code> response header.
            Excludes Next.js render and wire transit.
          </span>
        </span>
      )}
    </span>
  );
}

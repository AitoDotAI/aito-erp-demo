"use client";

import { useEffect, useRef, useState } from "react";
import { AITO_CALLS_EVENT, type AitoCallsEvent } from "@/lib/api";

const WINDOW = 30;

interface Sample {
  ms: number;        // total ms across every Aito call in the request
  calls: number;     // number of Aito calls
  path: string;
  cached: boolean;
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

/**
 * Persistent topbar badge: live Aito round-trip latency. Subscribes
 * to the same `aito:calls` event the bottom-left ticker uses, sums
 * per-call ms into a per-request sample, keeps a rolling 30-sample
 * window. The visible label is the most recent request's total ms;
 * hovering reveals min / p50 / p95 / avg over the window.
 *
 * Why both this and the ticker: the ticker proves "calls fly past
 * sub-50ms" as visitors click. The badge is the always-on summary
 * — open a page, glance at the topbar, see "aito 28ms" and know
 * the demo is hitting a real Aito instance, not faked.
 */
export default function LatencyBadge() {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [hover, setHover] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<AitoCallsEvent>).detail;
      // Skip cache hits — the badge tracks Aito work, not warmups.
      if (detail.cached || detail.calls.length === 0) return;
      const ms = detail.calls.reduce((s, c) => s + c.ms, 0);
      setSamples((prev) => {
        const next = [...prev, {
          ms,
          calls: detail.calls.length,
          path: detail.path,
          cached: false,
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
              {last.calls > 1 && (
                <span className="latency-badge-stat-aside">
                  ({last.calls} calls)
                </span>
              )}
            </span>
          </span>
          <span className="latency-badge-tooltip-foot">
            Round-trip ms server→Aito→server, summed across all
            Aito calls in the request. Excludes Next.js render and
            wire transit.
          </span>
        </span>
      )}
    </span>
  );
}

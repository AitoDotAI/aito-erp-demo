"use client";

import { useEffect, useState } from "react";
import { AITO_CALLS_EVENT, type AitoCallsEvent } from "@/lib/api";

/** Live ticker of recent Aito calls, pinned to the bottom-LEFT corner.
 *
 * Each API response's `X-Aito-Calls` header lists every Aito HTTP call
 * the backend made on that request along with the wall time it took
 * (recorded via `httpx`). We surface them as one pill per call, in
 * call order, color-coded by operation:
 *
 *     _predict 28ms   _relate 142ms   _search 11ms
 *
 * Why bottom-LEFT, not bottom-right: the right edge is occupied by
 * the persistent Aito side panel. A `right: 16px` pill landed on top
 * of it. Bottom-left keeps the latency feedback visible without
 * fighting the explanation panel for the same pixels.
 *
 * Why a ticker, not a single summed pill: visitors absorb "this is a
 * predictive *database*, not a model server" faster when they see
 * multiple sub-50ms calls fly than when they see one rounded total.
 * Cached responses still produce one transient "cached" entry so a
 * repeat click doesn't go silent.
 */

interface Entry {
  id: number;
  op: string;       // "_predict", "_relate", … or "cached"
  ms: number;       // 0 for cache entries
  at: number;       // Date.now() at arrival
  cached: boolean;
}

const VISIBLE = 5;            // most recent N entries on screen
const FADE_AT_MS = 4000;      // start fading
const DROP_AT_MS = 6000;      // gone

function fmtMs(ms: number): string {
  if (ms < 10) return ms.toFixed(1) + "ms";
  if (ms < 1000) return Math.round(ms) + "ms";
  return (ms / 1000).toFixed(2) + "s";
}

function colorFor(op: string): string {
  // Cluster colors per Aito operation so the same call looks the
  // same across pages. Hues match the accounting-demo ticker.
  if (op.startsWith("_predict")) return "#6ab87a";
  if (op.startsWith("_relate")) return "#9870d8";
  if (op.startsWith("_recommend")) return "#5a9ad8";
  if (op.startsWith("_search")) return "#d4a030";
  if (op.startsWith("_evaluate")) return "#d06060";
  if (op.startsWith("_match")) return "#12B5AD";
  return "#a89848";
}

export default function LatencyPill() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [, setTick] = useState(0); // re-render to advance fade

  useEffect(() => {
    let nextId = 1;
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<AitoCallsEvent>).detail;
      const at = Date.now();
      const newEntries: Entry[] = detail.cached
        ? [{ id: nextId++, op: "cached", ms: 0, at, cached: true }]
        : detail.calls.map((c) => ({
            id: nextId++,
            op: c.endpoint,
            ms: c.ms,
            at,
            cached: false,
          }));
      if (newEntries.length === 0) return;
      setEntries((prev) => [...prev, ...newEntries].slice(-VISIBLE));
    };
    window.addEventListener(AITO_CALLS_EVENT, handler);
    // Re-render once a second so age-based fades apply even when
    // no new calls arrive.
    const interval = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => {
      window.removeEventListener(AITO_CALLS_EVENT, handler);
      window.clearInterval(interval);
    };
  }, []);

  const now = Date.now();
  const visible = entries.filter((e) => now - e.at < DROP_AT_MS);
  if (visible.length === 0) return null;

  return (
    <div className="latency-pill" aria-hidden="true">
      {visible.map((e) => {
        const age = now - e.at;
        const opacity = age > FADE_AT_MS
          ? Math.max(0, 1 - (age - FADE_AT_MS) / (DROP_AT_MS - FADE_AT_MS))
          : 1;
        const c = e.cached ? "rgba(255,255,255,0.35)" : colorFor(e.op);
        return (
          <span
            key={e.id}
            className={`latency-entry${e.cached ? " latency-entry--cached" : ""}`}
            style={{ opacity, borderColor: `${c}66` }}
          >
            <span className="latency-dot" style={{ background: c }} />
            <span className="latency-endpoint" style={{ color: e.cached ? undefined : c }}>
              {e.op}
            </span>
            {!e.cached && <span className="latency-ms">{fmtMs(e.ms)}</span>}
          </span>
        );
      })}
    </div>
  );
}

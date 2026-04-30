"use client";

import { useEffect, useState } from "react";
import { AITO_CALLS_EVENT, type AitoCallsEvent } from "@/lib/api";

/** Corner pill that shows the *most recent* API request's Aito timings.
 *
 * The pill is the demo's fastest way to communicate "Aito is a
 * predictive *database*, not a model server" — visitors see real
 * sub-50ms `_predict` calls happening as they click. Every `apiFetch`
 * dispatches an `aito:calls` event with the parsed `X-Aito-Calls`
 * header; this component subscribes and renders the latest event.
 *
 * UX choices:
 *   - Auto-fades after 4s of idle so it doesn't compete with the
 *     primary content. Re-armed on every new event.
 *   - Cache hits show "cached" rather than 0ms — explains why a
 *     repeat click was instant without lying about timings.
 *   - Multiple Aito calls in one request (e.g. cross-sell does
 *     `_recommend`) collapse into a sum on the pill, with the call
 *     breakdown visible on hover via `title`.
 */
export default function LatencyPill() {
  const [event, setEvent] = useState<AitoCallsEvent | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let timeoutId: number | undefined;
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<AitoCallsEvent>).detail;
      setEvent(detail);
      setVisible(true);
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      timeoutId = window.setTimeout(() => setVisible(false), 4000);
    };
    window.addEventListener(AITO_CALLS_EVENT, handler);
    return () => {
      window.removeEventListener(AITO_CALLS_EVENT, handler);
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, []);

  if (!event) return null;

  const total = event.calls.reduce((s, c) => s + c.ms, 0);
  const breakdown = event.calls.map((c) => `${c.endpoint} ${Math.round(c.ms)}ms`).join("  ·  ");

  return (
    <div
      className={`latency-pill${visible ? " visible" : ""}`}
      title={breakdown || "Served from cache — no Aito call this round"}
    >
      {event.cached ? (
        <>
          <span className="latency-dot latency-dot--cached" />
          <span className="latency-label">cached</span>
        </>
      ) : (
        <>
          <span className="latency-dot" />
          <span className="latency-endpoint">
            {event.calls.length === 1
              ? event.calls[0].endpoint
              : `${event.calls.length} calls`}
          </span>
          <span className="latency-ms">{Math.round(total)}ms</span>
        </>
      )}
    </div>
  );
}

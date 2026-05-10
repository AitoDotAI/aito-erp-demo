/**
 * Segment analytics for the Predictive ERP demo.
 *
 * Mirrors aito-demo's `src/analytics.js` and aito-accounting-demo's
 * `frontend/lib/analytics.ts` so events from this demo land in the
 * same Segment workspace as every other Aito web property — the
 * comment in those files calls out "the same Segment write key as
 * other Aito properties for unified tracking."
 *
 * Differences from the accounting-demo source: only the SURFACE tag
 * below changes — events emitted from this demo show up tagged
 * `surface: "predictive-erp"` so analytics can split funnels by
 * which demo a visitor was on. The Segment loader and runtime
 * shape are intentionally identical so future updates to Aito's
 * standard analytics.js can be ported without diff drift.
 */

const SEGMENT_WRITE_KEY = "xSGtwFjgKl3m5ZMGaVB3SENT0oUHPwJq";
const SURFACE = "predictive-erp";

type AnalyticsCall =
  | [method: "page", name?: string, properties?: Record<string, unknown>]
  | [method: "track", event: string, properties?: Record<string, unknown>]
  | [method: "identify", userId: string, traits?: Record<string, unknown>]
  | [method: string, ...args: unknown[]];

interface SegmentAnalytics {
  invoked?: boolean;
  initialize?: boolean;
  methods?: string[];
  factory?: (method: string) => (...args: unknown[]) => SegmentAnalytics;
  load?: (key: string, options?: Record<string, unknown>) => void;
  push: (call: AnalyticsCall) => void;
  page?: (name?: string, properties?: Record<string, unknown>) => void;
  track?: (event: string, properties?: Record<string, unknown>) => void;
  identify?: (userId: string, traits?: Record<string, unknown>) => void;
  _writeKey?: string;
  SNIPPET_VERSION?: string;
  _loadOptions?: unknown;
}

declare global {
  interface Window {
    analytics?: SegmentAnalytics;
  }
}

function isProductionHost(): boolean {
  if (typeof window === "undefined") return false;
  const host = window.location.hostname;
  return host !== "localhost" && host !== "127.0.0.1" && !host.endsWith(".local");
}

/** Initialize Segment. Idempotent — safe to call from multiple
 *  components or React strict-mode double effects. */
export function initAnalytics(): void {
  if (typeof window === "undefined") return;
  if (window.analytics?.invoked) return;
  if (!isProductionHost()) return;

  // The Segment analytics.js snippet, ported from aito-demo verbatim
  // (only typing changes). Keeping the snippet shape identical so
  // updates to Aito's standard analytics.js version can be ported
  // across all three demos without intricate diffs.
  const analytics: SegmentAnalytics = (window.analytics =
    window.analytics || ({ push: () => {} } as SegmentAnalytics));
  if (analytics.initialize) return;
  if (analytics.invoked) {
    console.error("Segment snippet included twice.");
    return;
  }
  analytics.invoked = true;
  analytics.methods = [
    "trackSubmit",
    "trackClick",
    "trackLink",
    "trackForm",
    "pageview",
    "identify",
    "reset",
    "group",
    "track",
    "ready",
    "alias",
    "debug",
    "page",
    "once",
    "off",
    "on",
    "addSourceMiddleware",
    "addIntegrationMiddleware",
    "setAnonymousId",
    "addDestinationMiddleware",
  ];
  analytics.factory = (method) => {
    return function (...args: unknown[]) {
      args.unshift(method);
      analytics.push(args as AnalyticsCall);
      return analytics;
    };
  };
  for (const method of analytics.methods) {
    (analytics as unknown as Record<string, unknown>)[method] = analytics.factory(method);
  }
  analytics.load = function (key, options) {
    const script = document.createElement("script");
    script.type = "text/javascript";
    script.async = true;
    script.src = `https://cdn.segment.com/analytics.js/v1/${key}/analytics.min.js`;
    const first = document.getElementsByTagName("script")[0];
    first.parentNode?.insertBefore(script, first);
    analytics._loadOptions = options;
  };
  analytics._writeKey = SEGMENT_WRITE_KEY;
  analytics.SNIPPET_VERSION = "4.15.3";
  analytics.load(SEGMENT_WRITE_KEY, {
    cookie: { domain: ".aito.ai", secure: true, sameSite: "Lax" },
  });
}

export function trackPage(pageName: string, properties: Record<string, unknown> = {}): void {
  if (typeof window === "undefined" || !window.analytics?.page) return;
  window.analytics.page(pageName, { ...properties, surface: SURFACE });
}

export function trackEvent(event: string, properties: Record<string, unknown> = {}): void {
  if (typeof window === "undefined" || !window.analytics?.track) return;
  window.analytics.track(event, { ...properties, surface: SURFACE });
}

export function identifyUser(userId: string, traits: Record<string, unknown> = {}): void {
  if (typeof window === "undefined" || !window.analytics?.identify) return;
  window.analytics.identify(userId, { ...traits, surface: SURFACE });
}

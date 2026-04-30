import { DEFAULT_TENANT_ID, TenantId } from "./tenants";

const API_BASE = typeof window !== "undefined"
  ? `${window.location.protocol}//${window.location.host}`
  : "";

const TENANT_STORAGE_KEY = "demoTenant";

/** Read the active tenant from localStorage so apiFetch can stamp the
 * X-Tenant header without each call having to thread context through. */
function activeTenant(): TenantId {
  if (typeof window === "undefined") return DEFAULT_TENANT_ID;
  const stored = window.localStorage.getItem(TENANT_STORAGE_KEY);
  return (stored as TenantId | null) ?? DEFAULT_TENANT_ID;
}

/** One Aito API call's wall time, parsed from `X-Aito-Calls`. */
export interface AitoCall {
  endpoint: string;     // "_predict", "_relate", ...
  ms: number;
}

/** Event payload broadcast on every API response that included Aito work.
 *  The latency pill subscribes via `window.addEventListener("aito:calls", ...)`. */
export interface AitoCallsEvent {
  path: string;         // backend route (e.g. "/api/po/pending")
  calls: AitoCall[];    // empty for cache-hit responses (no header)
  cached: boolean;      // true when no X-Aito-Calls header present
}

export const AITO_CALLS_EVENT = "aito:calls";

function parseAitoCalls(header: string | null): AitoCall[] {
  if (!header) return [];
  return header
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((token) => {
      const [endpoint, ms] = token.split(":");
      return { endpoint, ms: Number(ms) || 0 };
    });
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  // Multi-tenant routing — backend reads this and selects the right
  // AitoClient (falls back to the default tenant when missing).
  if (!headers.has("X-Tenant")) {
    headers.set("X-Tenant", activeTenant());
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  // Broadcast every successful response's Aito-call timings (or empty
  // list for cache hits). The latency pill listens; pages that don't
  // care can ignore. Done before .json() so the pill updates as soon
  // as the headers land, not after the body parses.
  if (typeof window !== "undefined" && res.ok) {
    const detail: AitoCallsEvent = {
      path,
      calls: parseAitoCalls(res.headers.get("X-Aito-Calls")),
      cached: !res.headers.has("X-Aito-Calls"),
    };
    window.dispatchEvent(new CustomEvent(AITO_CALLS_EVENT, { detail }));
  }
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

export function fmtAmount(n: number): string {
  return "€ " + n.toLocaleString("fi-FI", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

export function confClass(p: number): string {
  if (p >= 0.80) return "conf-high";
  if (p >= 0.50) return "conf-mid";
  return "conf-low";
}

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

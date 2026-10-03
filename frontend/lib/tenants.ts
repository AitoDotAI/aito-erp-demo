/* Multi-tenant demo profiles.
 *
 * Same backend data, different presentation: each profile hides views
 * that don't fit the audience and tones the brand strip. Lets us drive
 * one demo deployment from three different sales conversations
 * (Lemonsoft / Oscar / a generic services SaaS).
 *
 * Adding a profile = add an entry here. Visibility is driven by route
 * paths so Nav and any per-page logic agree on the same source of truth.
 */

/** Must match `TENANT_IDS` in src/config.py — both the frontend and
 *  backend agree on the same identifier so the X-Tenant header routes
 *  to the correct AitoClient. */
export type TenantId = "metsa" | "aurora" | "studio";

export interface TenantProfile {
  id: TenantId;
  /** Display name shown in the TopBar */
  name: string;
  /** Short tagline / industry label */
  tagline: string;
  /** Audience hint used by sales conversations */
  audience: string;
  /** Accent colour for the TopBar brand chip */
  accent: string;
  /** Routes that should be hidden in the side nav. Use bare paths
   *  (e.g. "/catalog"), not hrefs with trailing slashes. */
  hideRoutes: string[];
  /** Default landing route when this tenant is selected. */
  defaultRoute: string;
}

export const TENANTS: TenantProfile[] = [
  {
    id: "metsa",
    name: "Metsä Machinery Oy",
    tagline: "Industrial maintenance · 180 staff",
    audience: "Logistics & construction (Lemonsoft-style)",
    accent: "#6b4f0e",
    // Hide commerce-flavoured views (incl. recommendations) and
    // services-only views (utilization).
    hideRoutes: ["/catalog", "/pricing", "/demand", "/recommendations", "/utilization", "/matching"],
    defaultRoute: "/po-queue",
  },
  {
    id: "aurora",
    name: "Aurora Retail Oy",
    tagline: "Multi-channel retail · 24 stores",
    audience: "Commerce (Oscar / ERPly-style)",
    accent: "#1a4a7a",
    // Hide projects + heavy approval routing — retail leans on stock + price.
    hideRoutes: ["/projects", "/project-plan", "/approval", "/utilization", "/forecast", "/planner"],
    defaultRoute: "/inventory",
  },
  {
    id: "studio",
    name: "Vire Consulting Oy",
    tagline: "Software consultancy · 42 consultants",
    audience: "Software consultancies (Futurice / Reaktor / Solita-style)",
    accent: "#2d7a4f",
    // Services don't carry physical inventory; pricing data is too
    // thin (80 SKUs, 200 price rows) to make Pricing credible. The
    // construction-phased Project Plan view is Metsä-only too.
    hideRoutes: ["/catalog", "/demand", "/inventory", "/pricing", "/recommendations", "/project-plan", "/matching"],
    defaultRoute: "/projects",
  },
];

export const DEFAULT_TENANT_ID: TenantId = "metsa";

export function getTenant(id: TenantId): TenantProfile {
  return TENANTS.find((t) => t.id === id) ?? TENANTS[0];
}

export function isTenantId(value: unknown): value is TenantId {
  return TENANTS.some((t) => t.id === value);
}

/** Does `tenant` hide the view at `pathname`? `/matching` and
 *  `/matching/` (static export adds the slash) both match. */
export function hidesRoute(tenant: TenantProfile, pathname: string): boolean {
  return tenant.hideRoutes.some((r) => pathname === r || pathname.startsWith(`${r}/`));
}

/** The tenant a page load starts in.
 *
 *  1. `?tenant=<id>` in the URL, so a link can open a view for a given
 *     tenant (catalog deep links);
 *  2. otherwise the choice persisted in localStorage;
 *  3. otherwise the default.
 *
 *  Then, if that tenant hides the page being opened, the first tenant
 *  that shows it. The nav already hides such views, but a direct link
 *  bypasses the nav: a cold visit to /matching/ rendered EMPTY under the
 *  default tenant, and /recommendations/ errored, because only Aurora
 *  has a product catalogue. */
export function resolveInitialTenant(
  pathname: string,
  search: string,
  stored: string | null,
): TenantId {
  const fromUrl = new URLSearchParams(search).get("tenant");
  const chosen: TenantId = isTenantId(fromUrl)
    ? fromUrl
    : isTenantId(stored) ? stored : DEFAULT_TENANT_ID;
  if (!hidesRoute(getTenant(chosen), pathname)) return chosen;
  return TENANTS.find((t) => !hidesRoute(t, pathname))?.id ?? chosen;
}

/** `search` with `key` set to `value` (or removed when null), every other
 *  param kept in place. Used for the tenant and for a view's selection,
 *  so a copied address bar reopens the same thing for someone else. */
export function searchWithParam(search: string, key: string, value: string | null): string {
  const params = new URLSearchParams(search);
  if (value === null) params.delete(key);
  else params.set(key, value);
  const out = params.toString();
  return out ? `?${out}` : "";
}

/** `search` carrying `?tenant=<id>`. The tenant lives in the URL, not only
 *  in localStorage: a link without it opened under the RECIPIENT's stored
 *  tenant, which is how "send this view" sent the wrong company. */
export function searchWithTenant(search: string, id: TenantId): string {
  return searchWithParam(search, "tenant", id);
}

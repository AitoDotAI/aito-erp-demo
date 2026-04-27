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
    hideRoutes: ["/catalog", "/pricing", "/demand", "/recommendations", "/utilization"],
    defaultRoute: "/po-queue",
  },
  {
    id: "aurora",
    name: "Aurora Retail Oy",
    tagline: "Multi-channel retail · 24 stores",
    audience: "Commerce (Oscar / ERPly-style)",
    accent: "#1a4a7a",
    // Hide projects + heavy approval routing — retail leans on stock + price.
    hideRoutes: ["/projects", "/approval", "/utilization"],
    defaultRoute: "/inventory",
  },
  {
    id: "studio",
    name: "Helsinki Studio",
    tagline: "Professional services · 42 consultants",
    audience: "Services / professional (horizontal SaaS)",
    accent: "#2d7a4f",
    // Services don't carry physical inventory; pricing data is too
    // thin (80 SKUs, 200 price rows) to make Pricing credible.
    hideRoutes: ["/catalog", "/demand", "/inventory", "/pricing", "/recommendations"],
    defaultRoute: "/projects",
  },
];

export const DEFAULT_TENANT_ID: TenantId = "metsa";

export function getTenant(id: TenantId): TenantProfile {
  return TENANTS.find((t) => t.id === id) ?? TENANTS[0];
}

/* Per-tenant Aito-panel content.
 *
 * The right-rail panel is the single highest-leverage piece of
 * marketing copy in the demo: it's where a CTO reads the actual
 * Aito query that's driving what they see on the page. Generic
 * copy ("$supplier", "$description") reads as boilerplate; copy
 * with their *industry's* names (Wärtsilä, Valio, Adobe) reads as
 * authentic.
 *
 * Pages call `panelFor(<page>, tenant)` to get a tailored config.
 * Click handlers within a page may override on selection — that
 * stays per-page.
 *
 * Add a new tenant: extend `CONTEXT`. Add a new page-flavoured
 * panel: add a builder function.
 */

import type { TenantId } from "./tenants";
import type { AitoPanelConfig } from "./types";

interface PersonaContext {
  /** Industry term used in description copy. */
  industry: string;
  /** Concrete supplier example for query templates. */
  supplier: string;
  /** Concrete cost-centre example. */
  costCenter: string;
  /** GL account this supplier typically codes to. */
  account: string;
  /** Approver who'd sign this off. */
  approver: string;
  /** A human-readable example description for a typical PO. */
  poDescription: string;
  /** A category that's interesting for anomaly examples. */
  anomalyCategory: string;
  /** A supplier that sees occasional late deliveries. */
  riskySupplier: string;
}

const CONTEXT: Record<TenantId, PersonaContext> = {
  metsa: {
    industry: "industrial maintenance",
    supplier: "Wärtsilä Components",
    costCenter: "Production",
    account: "4220",
    approver: "T. Virtanen",
    poDescription: "Hydraulic seals #WS-442",
    anomalyCategory: "production",
    riskySupplier: "NCC Suomi",
  },
  aurora: {
    industry: "multi-channel retail",
    supplier: "Valio Oy",
    costCenter: "Warehouse-Vantaa",
    account: "4010",
    approver: "M. Eronen",
    poDescription: "Weekly delivery — dairy",
    anomalyCategory: "groceries",
    riskySupplier: "Posti",
  },
  studio: {
    industry: "professional services",
    supplier: "Adobe Systems",
    costCenter: "Design",
    account: "5530",
    approver: "A. Lahti",
    poDescription: "Adobe CC team licenses",
    anomalyCategory: "software",
    riskySupplier: "RecruitFinland",
  },
};


// ── Page-specific panel builders ────────────────────────────────────


export function poQueuePanel(tenant: TenantId): AitoPanelConfig {
  const c = CONTEXT[tenant];
  return {
    operation: "_predict",
    stats: [
      { label: "Avg latency", value: "12ms" },
      { label: "Predict fields", value: "3" },
      { label: "Features", value: "supplier × desc × amount" },
    ],
    description:
      `Each incoming PO is scored with <em>aito.._predict</em>. For ${c.industry}, ` +
      `the model examines supplier, description, and amount to predict ` +
      `cost-centre, account code, and approver. Predictions for ${c.supplier} ` +
      `route to <em>${c.costCenter}</em> / account <em>${c.account}</em>; ` +
      `${c.approver} signs the typical case. High-confidence predictions ` +
      `auto-code; low-confidence ones queue for review.`,
    query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>: <span class="q-v">"${c.supplier}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"description"</span>: <span class="q-v">"${c.poDescription}"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"cost_center"</span><br/>
}<br/>
<br/>
<span class="q-d">// → cost_center: "${c.costCenter}" (p ≈ 0.94)</span>`,
    links: [
      { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      { label: "Confidence thresholds", url: "https://aito.ai/docs/guides/confidence" },
    ],
  };
}


export function supplierPanel(tenant: TenantId): AitoPanelConfig {
  const c = CONTEXT[tenant];
  return {
    operation: "_relate",
    stats: [
      { label: "Patterns", value: "spend × delivery" },
      { label: "Discovery", value: "lift threshold" },
      { label: "Scan freq.", value: "daily" },
    ],
    description:
      `Supplier intelligence uses <em>aito.._relate</em> to find statistical ` +
      `links between supplier attributes and delivery outcomes. For ${c.industry}, ` +
      `this surfaces patterns like &ldquo;<em>${c.riskySupplier}</em> orders ` +
      `correlate with late delivery&rdquo; — discovered, not configured. ` +
      `The lift score tells you how much more likely the bad outcome is, ` +
      `compared to baseline.`,
    query: `<span class="q-k">POST</span> /api/v1/_relate<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: { <span class="q-k">"delivery_late"</span>: <span class="q-n">true</span> },<br/>
&nbsp;&nbsp;<span class="q-k">"relate"</span>: [<span class="q-p">"supplier"</span>, <span class="q-p">"category"</span>]<br/>
}<br/>
<br/>
<span class="q-d">// → ${c.riskySupplier}: lift × 1.6 (high risk)</span>`,
    links: [
      { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
    ],
  };
}


export function anomaliesPanel(tenant: TenantId): AitoPanelConfig {
  const c = CONTEXT[tenant];
  return {
    operation: "_predict (inverse)",
    stats: [
      { label: "Patterns", value: "amount × code × CC" },
      { label: "Method", value: "low p = anomaly" },
      { label: "Coverage", value: "every PO" },
    ],
    description:
      `Anomaly detection inverts <em>aito.._predict</em>: instead of asking ` +
      `&ldquo;what's the most likely value?&rdquo; we ask &ldquo;how likely ` +
      `is the value that's actually there?&rdquo;. A PO from ${c.supplier} ` +
      `coded to a non-${c.costCenter} cost-centre, or a ${c.anomalyCategory} ` +
      `purchase posted to a wildly off-pattern account, returns a low ` +
      `probability — that's the anomaly score. No rules, no thresholds to ` +
      `maintain.`,
    query: `<span class="q-k">POST</span> /api/v1/_predict<br/>
{<br/>
&nbsp;&nbsp;<span class="q-k">"from"</span>: <span class="q-v">"purchases"</span>,<br/>
&nbsp;&nbsp;<span class="q-k">"where"</span>: {<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"supplier"</span>: <span class="q-v">"${c.supplier}"</span>,<br/>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="q-k">"category"</span>: <span class="q-v">"${c.anomalyCategory}"</span><br/>
&nbsp;&nbsp;},<br/>
&nbsp;&nbsp;<span class="q-k">"predict"</span>: <span class="q-p">"cost_center"</span><br/>
}<br/>
<br/>
<span class="q-d">// p(actual) = 0.04 → flagged</span>`,
    links: [
      { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
    ],
  };
}

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

import { referenceLinks } from "./references";
import type { TenantId } from "./tenants";
import type { AitoPanelConfig } from "./types";
import { findQuery, type RecordedQuery } from "./query";

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
    riskySupplier: "NCC Suomi",
  },
  aurora: {
    industry: "multi-channel retail",
    supplier: "Valio Oy",
    costCenter: "Warehouse-Vantaa",
    account: "4010",
    approver: "M. Eronen",
    poDescription: "Weekly delivery — dairy",
    riskySupplier: "Posti",
  },
  studio: {
    industry: "professional services",
    supplier: "Adobe Systems",
    costCenter: "Design",
    account: "5530",
    approver: "A. Lahti",
    poDescription: "Adobe CC team licenses",
    riskySupplier: "RecruitFinland",
  },
};


// ── Page-specific panel builders ────────────────────────────────────


/** `queries`: what the backend recorded for the queue (`_queries`). The
 *  default pane shows the first cost-centre prediction it sent. */
export function poQueuePanel(tenant: TenantId, recorded?: RecordedQuery[]): AitoPanelConfig {
  const c = CONTEXT[tenant];
  const first = findQuery(recorded, { endpoint: "_predict", from: "purchases", target: "cost_center" });
  const queries = first ? [first] : [];
  return {
    operation: "_predict",
    endpoints: ["_predict"],
    stats: [
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
    queries,
    links: [
      { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/01-po-queue.md", kind: "doc" },
      { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      { label: "Confidence thresholds", url: "https://aito.ai/docs/guides/confidence" },
      ...referenceLinks({ useCase: "01-po-queue", source: "src/po_service.py" }),
    ],
  };
}


/** The supplier row the panel quotes. Taken from the SAME payload the
 *  header counts, so the panel can never say "high risk" over a header
 *  that says 0 high risk — which it did, from a hardcoded line. */
export interface SupplierRiskExample {
  supplier: string;
  lift: number;
  late_rate: number;
  risk_level: string;
}

/** `recorded`: what the backend sent for the overview (`_queries`). The
 *  pane shows the one `_relate` behind the delivery-risk list. */
export function supplierPanel(
  tenant: TenantId,
  top?: SupplierRiskExample,
  recorded?: RecordedQuery[],
): AitoPanelConfig {
  const c = CONTEXT[tenant];
  const example = top?.supplier ?? c.riskySupplier;
  const relate = findQuery(recorded, {
    endpoint: "_relate", from: "purchases", target: "supplier", where: { delivery_late: true },
  });
  return {
    operation: "_relate",
    endpoints: ["_relate"],
    stats: [
      { label: "Patterns", value: "supplier × late delivery" },
      { label: "Ranked by", value: "lift" },
    ],
    description:
      `Supplier intelligence uses <em>aito.._relate</em> to find statistical ` +
      `links between suppliers and late delivery. For ${c.industry}, ` +
      `this surfaces patterns like &ldquo;<em>${example}</em> orders ` +
      `correlate with late delivery&rdquo; — discovered, not configured. ` +
      `The lift score tells you how much more likely the bad outcome is, ` +
      `compared to baseline.`,
    queries: relate ? [relate] : [],
    links: [
      { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/05-supplier-intel.md", kind: "doc" },
      { label: "Relate API reference", url: "https://aito.ai/docs/api/relate" },
      ...referenceLinks({ useCase: "05-supplier-intel", source: "src/supplier_service.py" }),
    ],
  };
}


/** `recorded`: what the backend sent for the scan (`_queries`). The
 *  default pane shows the one Aito prediction in it — the account code
 *  the mis-coded row is checked against. The other two rows are
 *  `_search` reads, shown when their row is selected. */
export function anomaliesPanel(tenant: TenantId, recorded?: RecordedQuery[]): AitoPanelConfig {
  const c = CONTEXT[tenant];
  const predict = findQuery(recorded, { endpoint: "_predict", from: "purchases", target: "account_code" });
  return {
    operation: "_predict (inverse)",
    endpoints: ["_predict", "_search"],
    stats: [
      { label: "Checks", value: "account × amount × vendor" },
      { label: "Method", value: "low p = anomaly" },
    ],
    description:
      `Anomaly detection inverts <em>aito.._predict</em>: instead of asking ` +
      `&ldquo;what's the most likely value?&rdquo; we ask &ldquo;how likely ` +
      `is the value that's actually there?&rdquo;. For a PO from ${c.supplier}, ` +
      `Aito predicts the account code from the supplier alone; an account ` +
      `it gives little probability to scores high, as (1 − p) × 100. ` +
      `Amount spikes and first-time vendors use the same score, with p ` +
      `counted from a <em>_search</em> over the purchase history. ` +
      `No rules, no thresholds to maintain.`,
    queries: predict ? [predict] : [],
    links: [
      { label: "Use case overview", url: "https://github.com/AitoDotAI/aito-erp-demo/blob/main/docs/use-cases/04-anomaly-detection.md", kind: "doc" },
      { label: "Predict API reference", url: "https://aito.ai/docs/api/predict" },
      ...referenceLinks({ useCase: "04-anomaly-detection", source: "src/anomaly_service.py" }),
    ],
  };
}

import type { RecordedQuery, WithQueries } from "./query";

/* ─── PO Queue ─── */
export interface POPrediction {
  purchase_id: string;
  supplier: string;
  description: string;
  amount: number;
  cost_center: string | null;
  cost_center_confidence: number;
  account_code: string | null;
  account_code_confidence: number;
  approver: string | null;
  approver_confidence: number;
  source: "rule" | "aito" | "review";
  confidence: number;
  cost_center_alternatives?: Alternative[];
  account_code_alternatives?: Alternative[];
  approver_alternatives?: Alternative[];
  cost_center_why?: WhyExplanation;
  account_code_why?: WhyExplanation;
  approver_why?: WhyExplanation;
  /** Fields a rule decided, each with "rule …: right on M of T POs". */
  rule_fields: Partial<Record<"cost_center" | "account_code" | "approver", string>>;
  /** "Rule", "Rule, check approver", "Aito" or "Review". */
  status_label: string;
}

export interface POMetrics {
  automation_rate: number;
  avg_confidence: number;
  total: number;
  rule_count: number;
  aito_count: number;
  review_count: number;
}

export interface RecentSubmission {
  purchase_id: string;
  supplier: string;
  submitted_at: string | null;
}

export interface POQueueResponse extends WithQueries {
  pos: POPrediction[];
  metrics: POMetrics;
  /** User-submitted POs from the in-memory store. Drives the
   *  "Aito just learned from these" relearn banner. */
  recent_submissions?: RecentSubmission[];
}

/* ─── Smart Entry ─── */
export interface SmartEntryField {
  field: string;
  label: string;
  value: string;
  raw_value: string;
  confidence: number;
  predicted: boolean;
  alternatives?: Alternative[];
  why?: WhyExplanation;
}

export interface SmartEntryResponse extends WithQueries {
  where: Record<string, string>;
  fields: SmartEntryField[];
  predicted_count: number;
  avg_confidence: number;
}

/* ─── Approval Routing ─── */
export interface ApprovalPrediction {
  purchase_id: string;
  supplier: string;
  amount: number;
  escalation_reason: string;
  predicted_approver: string;
  confidence: number;
  predicted_level: string;
  alternatives?: Alternative[];
  why?: WhyExplanation;
}

export interface ApprovalResponse extends WithQueries {
  approvals: ApprovalPrediction[];
}

/* ─── Anomaly Detection ─── */
export interface AnomalyFlag {
  purchase_id: string;
  supplier: string;
  amount: number;
  anomaly_score: number;
  severity: "high" | "medium" | "low";
  flagged_field: string;
  expected_value: string;
  actual_value: string;
  explanation?: string;
}

export interface AnomalyResponse extends WithQueries {
  anomalies: AnomalyFlag[];
}

/* ─── Supplier Intel ─── */
export interface SupplierSpend {
  supplier: string;
  total_amount: number;
  po_count: number;
  avg_amount: number;
  categories: string[];
}

export interface DeliveryRisk {
  supplier: string;
  late_rate: number;
  base_late_rate: number;   // across every supplier — what lift compares to
  lift: number;             // Aito's, shrunk toward 1 on few deliveries
  total_orders: number;
  late_orders: number;
  risk_level: string;
}

export interface SupplierResponse extends WithQueries {
  top_suppliers: SupplierSpend[];
  /** @deprecated Renamed to `top_suppliers`; will be dropped after migration. */
  spend_overview?: SupplierSpend[];
  delivery_risks: DeliveryRisk[];
}

/* ─── Rule Mining ─── */
export interface RuleCandidate {
  condition_field: string;
  condition_value: string;
  predicted_field: string;
  predicted_value: string;
  confidence: number;
  support: number;
  lift: number;
  strength: "strong" | "review" | "weak";
}

export interface RulesResponse extends WithQueries {
  candidates: RuleCandidate[];
  summary: {
    total: number;
    strong: number;
    review: number;
    weak: number;
    min_support: number;
  };
}

/* ─── Catalog Intelligence ─── */
export interface IncompleteProduct {
  sku: string;
  name: string;
  supplier: string | null;
  category: string | null;
  unit_price: number | null;
  hs_code: string | null;
  unit_of_measure: string | null;
  missing_fields: string[];
  missing_count: number;
  completeness: number;
}

export interface CatalogResponse extends WithQueries {
  products: IncompleteProduct[];
  total: number;
}

/* ─── Price Intelligence ─── */
/** Every figure below comes from a query or a measurement; see
 *  src/pricing_service.py, src/demand_service.py, src/inventory_service.py. */
export interface PricedQuote {
  price_id: string;
  supplier: string;
  volume: number;
  order_date: string;
  quoted: number;
  aito: number;               // `_estimate unit_price` over earlier prices only
  median: number | null;      // the product's own earlier median
  deviation_pct: number;      // quoted vs aito
  flagged: boolean;           // deviation above flag_margin
  neighbours: number;         // earlier price rows the estimate weighted
}

export interface PricingProduct {
  sku: string;
  name: string;
  category: string | null;
  list_price: number | null;
  earlier_prices: number;
  quotes: PricedQuote[];
}

export interface PricingMeasured {
  measured_on: string;
  overcharge_over_list: number;    // what the eval counts as an overcharge
  engine_build: string;
  n: number;
  aito_error: number;
  median_error: number;
  overcharges: number;
  aito_caught: number;
  aito_flagged: number;
  median_caught: number;
  median_flagged: number;
}

export interface PricingResponse extends WithQueries {
  cutoff: string;
  flag_margin: number;
  features: string[];
  products: PricingProduct[];
  measured: PricingMeasured;
}

/* ─── Demand Forecast ─── */
export interface DemandHorizonMonth {
  month: string;
  where: Record<string, string>;   // the exact `where` sent to `_estimate`
  aito: number;         // `_estimate units_sold`
  last_year: number;    // same month last year
  trailing: number;     // the ERP reorder rule's trailing 3-month mean
  actual: number;       // held out from the estimate
  neighbours: number;
}

export interface DemandProduct {
  sku: string;
  name: string;
  category: string;
  supplier: string;
  history: Array<{ month: string; units: number }>;
  horizon: DemandHorizonMonth[];
}

export interface DemandMeasured {
  measured_on: string;
  engine_build: string;
  metric: string;
  n: number;
  aito: number;
  last_year: number;
  trailing: number;
}

export interface DemandResponse extends WithQueries {
  cutoff: string;
  products: DemandProduct[];
  features: string[];
  measured: DemandMeasured;
}

/* ─── Inventory Intelligence ─── */
export interface StockCheck {
  sku: string;
  name: string;
  category: string;
  supplier: string;
  unit_price: number | null;
  on_hand: number;
  on_order: number;
  next_delivery_month: string | null;
  arriving_in_time: number;
  lead_time_days: number;
  reorder_point: number;
  aito_daily: number;
  trailing_daily: number;
  actual_daily: number;
  days_of_cover: number | null;   // null: no demand forecast, cover unbounded
  status: "critical" | "low" | "ok" | "overstock";
  aito_short: boolean;
  rule_short: boolean;
  actually_short: boolean;
  neighbours: number;
  where: Record<string, string>;   // the exact `where` of the forecast
}

export interface WarningScore {
  raised: number;
  right: number;
  real_shortfalls: number;
  caught: number;
}

export interface InventoryResponse extends WithQueries {
  as_of: string;
  items_checked: number;
  counts: Record<"critical" | "low" | "ok" | "overstock", number>;
  warnings: { aito: WarningScore; trailing_rule: WarningScore };
  synthetic_stock: boolean;
  items: StockCheck[];
}

/* ─── Automation Overview ─── */
export interface AutomationBreakdown {
  total_purchases: number;
  rules_count: number;
  rules_pct: number;
  aito_high_count: number;
  aito_high_pct: number;
  aito_reviewed_count: number;
  aito_reviewed_pct: number;
  manual_count: number;
  manual_pct: number;
}

export interface ConfidenceBand {
  label: string;
  min_p: number;
  count: number;
  accuracy: number | null;   // null when the band is empty
  mean_p: number | null;     // what Aito claimed, to judge accuracy against
  thin: boolean;             // too few cases for the accuracy to mean much
}

export interface PredictionQuality {
  field_name: string;
  accuracy: number;
  base_accuracy: number;
  accuracy_gain: number;
  avg_confidence: number;
  sample_size: number;
  bands: ConfidenceBand[];
}

export interface OverviewMetrics extends WithQueries {
  automation: AutomationBreakdown;
  prediction_quality: PredictionQuality[];
  learning_curve: Array<{
    month?: string;
    week: number;
    automation_pct: number;
    avg_confidence: number;
    manual_pct: number;
    total?: number;
  }>;
  summary: {
    automation_rate: number;
    total_automated: number;
    needs_review: number;
    fully_manual: number;
    avg_prediction_confidence: number;
    model_accuracy?: number;
    baseline_accuracy?: number;
    accuracy_gain?: number;
  };
  /** Which figures describe the demo data generator rather than Aito. */
  provenance: { routed_by: string };
}

/* ─── Cold-start snapshot ─── */
export interface ColdStartFieldSnapshot {
  name: string;
  accuracy: number;
  base_accuracy: number;
  high_confidence_share: number;     // share of test cases at $p ≥ 0.85
  high_confidence_accuracy: number;  // accuracy *within* that band
}

export interface ColdStartSnapshot {
  size: number;
  label: string;     // "Brand-new tenant", "Two months in", "Mature tenant"
  blurb: string;
  fields: ColdStartFieldSnapshot[];
}

export interface ColdStartResponse {
  captured_at: string;
  captured_from: string;
  method: string;
  fields: string[];
  snapshots: ColdStartSnapshot[];
  note: string;
}

/** Live cold-start: slider-driven `_evaluate` queries against the
 *  current tenant's purchases table, with `order_month <= cutoff`
 *  filtering Aito's conditional probabilities. */
export interface ColdStartCutoff {
  cutoff: string;
  label: string;
  approx_rows: number;
}

export interface ColdStartLiveResponse extends WithQueries {
  cutoff: string;
  fields: Array<ColdStartFieldSnapshot & { total_cases: number }>;
}

/* ─── Recommendations (Aurora retail) ─── */
export interface RecommendationProduct {
  sku: string;
  name: string;
  category: string | null;
  supplier: string | null;
  unit_price: number | null;
}

export interface TrendingItem {
  sku: string;
  name: string;
  category: string | null;
  baskets: number;       // baskets containing it, last six months
  months: number;
}

export interface CrossSellItem {
  sku: string;
  name: string;
  category: string | null;
  supplier: string | null;
  unit_price: number | null;
  /** How many times more often than in baskets at large (`_relate` lift). */
  lift: number;
  /** Baskets containing both, of `anchor_baskets` containing the anchor. */
  together: number;
  anchor_baskets: number;
}

export interface SimilarItem {
  sku: string;
  name: string;
  category: string | null;
  supplier: string | null;
  unit_price: number | null;
  score: number;
}

export interface RecommendationOverview extends WithQueries {
  products: RecommendationProduct[];
  trending: TrendingItem[];
}

/* ─── Utilization (Studio services) ─── */
export interface UtilizationRow {
  person: string;
  primary_role: string;
  current_allocation_pct: number;
  target_pct: number;
  gap_pct: number;
  historical_avg_pct: number;
  at_risk_pct: number;
  active_projects: number;
  completed_projects: number;
  status: "overloaded" | "available" | "balanced" | "at_risk";
}

export interface UtilizationSummary {
  total_people: number;
  avg_utilization: number;
  overloaded_count: number;
  available_count: number;
  at_risk_count: number;
  balanced_count: number;
}

export interface UtilizationOverview extends WithQueries {
  rows: UtilizationRow[];
  summary: UtilizationSummary;
  project_types: string[];
}

export interface CapacityForecast extends WithQueries {
  person: string;
  project_type: string;
  predicted_role: string | null;
  role_confidence: number;
  role_alternatives: Alternative[];
  predicted_allocation: number | null;
  allocation_confidence: number;
  historical_count: number;
}

/* ─── Projects / Operations ─── */
export interface ProjectKPIs {
  total: number;
  completed: number;
  active: number;
  success_rate: number;
  on_time_rate: number;
  on_budget_rate: number;
  at_risk_count: number;
}

export interface ProjectRow {
  project_id: string;
  name: string;
  project_type: string;
  customer: string;
  manager: string;
  team_lead: string;
  team_size: number;
  team_members: string;
  budget_eur: number;
  duration_days: number;
  priority: string;
  status: string;
  start_month: string;
  on_time: boolean | null;
  on_budget: boolean | null;
  success: boolean | null;
  success_p: number | null;
  success_alternatives: Alternative[];
  success_why: WhyExplanation | Record<string, never>;
}

export interface SuccessFactor {
  /** Discriminator: "person" comes from assignments.person; the rest
   *  come from projects.<field>. */
  kind: "person" | "manager" | "project_type" | "priority";
  label: string;             // human-readable group label, e.g. "Manager"
  field: string;             // source — "assignments.person", "projects.manager", …
  value: string;             // concrete value
  role_in_pattern: "boost" | "drag";
  lift: number;
  coverage: number;
  success_rate_with: number;
  success_rate_without: number;
}

export interface PortfolioResponse extends WithQueries {
  kpis: ProjectKPIs;
  projects: ProjectRow[];
  success_factors: SuccessFactor[];
}

/* ─── Project Plan (Metsä — generative + matchmaking) ─── */
export interface PlanTaskCandidate {
  phase: string;
  task_name: string;
  assignee_kind: "subcontractor" | "employee";
  assignee: string;
  assignee_confidence: number;
  planned_days: number;
  planned_cost_eur: number;
  success_p: number;
  materials: MaterialSuggestion[];
}

export interface PurchaseSuggestion {
  phase: string;
  category: string;
  supplier: string;
  supplier_confidence: number;
  typical_amount_eur: number | null;
  coverage: number;
}

/** One material line beneath a task — predicted product line, predicted
 * supplier, predicted amount. `supplier_source` mirrors SupplierOption
 * so the UI can badge portal entrants the same way in both views. */
export interface MaterialSuggestion {
  description: string;            // product line, e.g. "Steel erection batch"
  category: string;
  supplier: string;
  supplier_source: "history" | "portal";
  supplier_confidence: number;
  supplier_why: WhyExplanation | null;
  estimated_amount_eur: number | null;
  amount_confidence: number;
  coverage: number;
}
export interface TaskMaterialsResponse extends WithQueries { materials: MaterialSuggestion[] }

export interface GeneratedPlanResponse {
  project_type: string;
  region: string;
  season: string;
  estimated_budget_eur: number | null;
  phases: string[];
  tasks: PlanTaskCandidate[];
  purchases: PurchaseSuggestion[];
  total_planned_days: number;
  total_planned_cost_eur: number;
  total_purchases_eur: number;
  avg_success_p: number;
}

export interface AlternativeAssignee {
  name: string;
  success_p: number;
  coverage: number;
  avg_days: number | null;
  avg_cost_eur: number | null;
}

export interface RerankResponse {
  candidates: AlternativeAssignee[];
}

/* ─── Project Plan: step-by-step walker ─── */
export interface PhaseOption {
  phase: string;
  p: number;
  typical_task_count: number;
}
export interface TaskOption {
  task_name: string;
  p: number;
  typical_days: number;
  typical_cost_eur: number;
}
export interface AssigneeOption {
  assignee_kind: "subcontractor" | "employee";
  name: string;
  p: number;          // confidence from `_predict assignee`
  success_p: number;  // P(success) given this assignment
}
export interface NextPhaseResponse extends WithQueries { options: PhaseOption[] }
export interface NextTasksResponse extends WithQueries { options: TaskOption[] }
export interface NextAssigneeResponse extends WithQueries { options: AssigneeOption[] }
export interface PhasePurchasesResponse { purchases: PurchaseSuggestion[] }

/** One candidate supplier in the editable material-PO dropdown.
 *  History candidates carry a processed $why for the popover;
 *  supplier-portal candidates carry none (no purchase history yet). */
export interface SupplierOption {
  supplier: string;
  source: "history" | "portal";
  confidence: number;          // _predict $p (history) or 0 (portal)
  coverage: number;
  avg_amount_eur: number | null;
  why: WhyExplanation | null;
}
export interface SwapSupplierResponse extends WithQueries { options: SupplierOption[] }

/* ─── Aito Panel ─── */
export interface AitoPanelConfig {
  operation: string;
  stats?: Array<{ label: string; value: string }>;
  description: string;
  /** Queries the backend recorded while producing what is on screen
   *  (`findQuery` over a response's `_queries`). Never written by hand;
   *  empty when nothing on screen came from a query. */
  queries: RecordedQuery[];
  links?: Array<{ label: string; url: string; kind?: "doc" | "github" | "external" }>;
  /** Aito endpoints used on this page — rendered as purple-tinted pills,
   * matches aito-demo's ContextPanel. */
  endpoints?: string[];
}

/* ─── Shared ─── */

/** Per-pattern lift extracted from Aito $why.factors. Each represents one
 * matched proposition (e.g. "supplier has Telia") and its multiplicative
 * effect on the prediction. */
export interface WhyLift {
  lift: number;
  proposition_str: string;
  highlights: Array<{
    field: string;       // stripped of $context. / table. prefix
    raw_field: string;   // original — keeps $context. for cross-highlight
    html: string;        // text with « / » sentinel tags around matched tokens
  }>;
}

/** Processed explanation payload for one prediction. Computed server-side
 * by why_processor.py from the raw $why response. */
export interface WhyExplanation {
  base_p: number;
  lifts: WhyLift[];
  final_p: number;
  normalizer: number | null;   // null when within ±10% of 1.0
  context_fields: string[];    // input field names that contributed
}

/** Legacy shape kept for backwards compatibility — older endpoints still
 * return this. New code should prefer WhyExplanation. */
export interface WhyFactor {
  field: string;
  value: string;
  lift: number;
}

export interface Alternative {
  value: string;
  confidence: number;
  why?: WhyExplanation | WhyFactor[];
}

/* ─── Revenue Outlook (forecast_service) ─── */
export interface ForecastMonth {
  month: string;
  scheduled_eur: number;
  expected_eur: number;
  slipped_eur: number;
}

export interface ProjectOutlook {
  project_id: string;
  name: string;
  customer: string;
  project_type: string;
  manager: string;
  status: string;
  budget_eur: number;
  start_month: string;
  scheduled_end_month: string;
  months_total: number;
  months_remaining: number;
  remaining_eur: number;
  overdue: boolean;
  on_time_p: number | null;
  on_budget_p: number | null;
  at_risk_eur: number;
  on_time_why: WhyExplanation | Record<string, never>;
  on_budget_why: WhyExplanation | Record<string, never>;
}

export interface OutlookKPIs {
  active_count: number;
  order_book_eur: number;
  next_quarter_eur: number;
  at_risk_eur: number;
  overdue_count: number;
  overdue_eur: number;
}

export interface OutlookResponse extends WithQueries {
  as_of: string;
  kpis: OutlookKPIs;
  months: ForecastMonth[];
  projects: ProjectOutlook[];
}

/* ─── Engagement Planner (planner_service) ─── */
/** A reason shown next to a candidate, tagged with what KIND of claim
 *  it is: `aito` = Aito's `$why` named this field as evidence,
 *  `match` = it coincides with the proposal (client-side), `fact` =
 *  context that argued nothing, `warn` = something to look at. */
export interface PlannerChip {
  label: string;
  kind: "aito" | "match" | "fact" | "warn";
  field: string;
}

export interface PlannerCandidate {
  person: string;
  fit: number;
  current_load_pct: number;
  status: string;
  title: string;
  discipline: string;
  skills: string[];
  certifications: string;
  site: string;
  seniority: string;
  domains: string[];
  years_experience: number;
  matches: PlannerChip[];
  booked_pct: number;
  free_pct: number;
  available: boolean;
  absent_months: string[];
  absence_kind: string;
  contention: number;
  contention_pct: number;
  quality_p: number | null;
  quality_why: WhyExplanation | Record<string, never>;
  history_count: number;
  why: WhyExplanation | Record<string, never>;
}

export interface PlannerRoleSlot {
  role: string;
  count: number;
  share: number;
  skills: string;
  unknown_skills: string[];
  seniority: string;
  from_month: string;
  to_month: string;
  candidates: PlannerCandidate[];
  assignees: string[];
}

export interface PlannerLeverDelta {
  field: string;
  label: string;
  before: number;
  after: number;
  delta: number;
}

export interface PlannerLever {
  label: string;
  detail: string;
  deltas: PlannerLeverDelta[];
}

export interface PlannerOutcome {
  field: string;
  label: string;
  p: number | null;
  why: WhyExplanation | Record<string, never>;
}

export interface PlannerDeliveryRisk {
  success_p: number | null;
  core: PlannerOutcome[];
  qualifying: PlannerOutcome[];
  success_why: WhyExplanation | Record<string, never>;
}

export interface PlannerPriceCheck {
  comparable_count: number;
  median_eur: number;
  low_eur: number;
  high_eur: number;
  quoted_eur: number;
  ratio: number;
  band: string;
}

export interface PlannerObjection {
  reason: string;
  p: number;
}

export interface PlannerSalesRisk {
  win_p: number | null;
  win_why: WhyExplanation | Record<string, never>;
  objections: PlannerObjection[];
  quote_history: number;
}

export interface EngagementPlan extends WithQueries {
  customer: string;
  scope: string;
  project_type: string;
  quoted_eur: number;
  duration_days: number;
  team_size: number;
  priority: string;
  site: string;
  technology: string;
  domain: string;
  contract_type: string;
  scope_clarity: string;
  novelty: string;
  customer_size: string;
  team_seniority: string;
  required_skills: string;
  seniority: string;
  local_only: boolean;
  start_month: string;
  window_months: number;
  shape: { suggested_size: number | null; size_p: number | null };
  levers: PlannerLever[];
  roles: PlannerRoleSlot[];
  delivery: PlannerDeliveryRisk;
  price: PlannerPriceCheck | null;
  sales: PlannerSalesRisk | null;
}

export interface PlannerOptions extends WithQueries {
  project_types: string[];
  customers_by_type: Record<string, string[]>;
  sites: string[];
  site_by_customer: Record<string, string>;
  roles: string[];
  seniorities: string[];
  technologies_by_type: Record<string, string[]>;
  drivers: Record<string, string[]>;
  domain_by_customer: Record<string, string>;
  domains: string[];
}

/* ── Invoice line matching ───────────────────────────────────── */

/** One claim about a candidate, with who made it. `aito` came out of
 *  the `$why` tree, `against` came out of it as evidence AGAINST,
 *  `match` was computed in the service and argued by nobody. */
/** First line of the project-plan stream: enough to draw the phase
 *  skeleton (~2s in) before any task has been predicted. */
export interface PlanMeta {
  project_type: string;
  region: string;
  season: string;
  estimated_budget_eur: number | null;
  phases: string[];
  expected_tasks: number;
}

export interface MatchReason {
  kind: "aito" | "against" | "match";
  text: string;
  field: string;
  lift: number | null;
  /** What Aito fell back on when this candidate's own history was too
   *  thin to judge the factor — present only where a fallback actually
   *  fired and actually moved the number. Nested, not a sibling: the
   *  generalisation is only meaningful next to the factor it rescued. */
  priors: MatchPrior[];
}

/** One generalisation: "I have not seen this SKU invoiced this way,
 *  but I have seen rows from this supplier". */
export interface MatchPrior {
  text: string;
  lift: number;
}

export interface MatchCandidate {
  sku: string;
  name: string;
  category: string | null;
  supplier: string | null;
  unit_price: number | null;
  unit_of_measure: string | null;
  p: number;
  reasons: MatchReason[];
}

export interface MatchedLine {
  line_id: string;
  invoice_id: string;
  billing_supplier: string;
  description: string;
  quantity: number;
  unit_of_measure: string | null;
  unit_price_eur: number | null;
  line_amount_eur: number | null;
  candidates: MatchCandidate[];
  decision: "prefilled" | "open";
  ms: number;
  cold: boolean;
  /** Held-out label. Present because these lines were never loaded —
   *  a production queue has no truth column and a demo that hides it
   *  is asking to be trusted. */
  truth: string | null;
  truth_name: string | null;
  correct: boolean | null;
  /** The pick is a different SKU the catalogue calls the same thing.
   *  Not a miss the ranker could have avoided — nothing in the data
   *  separates the two rows. Its own outcome, never counted correct. */
  same_name: boolean;
}

export interface MatchBatchStats {
  n: number;
  wall_s: number;
  workers: number;
  rows_per_s: number;
  rows_per_week: number;
  server_ms_median: number;
  prefilled: number;
  open: number;
  threshold: number;
  top1: number | null;
  top5: number | null;
  prefill_precision: number | null;
}

/** One row of the coverage/precision curve: what pre-filling at this
 *  confidence bar would cover, and how often it would be right. */
export interface MatchCurvePoint {
  bar: number;
  coverage: number;
  precision: number;
}

/** Accuracy in one matching regime, and how much of the corpus it is.
 *  Published together on purpose: a blended figure over a corpus whose
 *  composition we chose is meaningless without the shares. */
export interface MatchRegime {
  overlap: string;
  share: number;
  aito: number;
  tfidf: number;
}

export interface MatchMeasured {
  /** Which engine these numbers describe — rep1 and rep2 differ. */
  engine: string;
  ceiling_top1: number;
  ceiling_top5: number;
  floor_top1: number;
  floor_top5: number;
  regimes: MatchRegime[];
  measured_on: string;
  n: number;
  catalogue_skus: number;
  labelled_lines_loaded: number;
  note: string;
  overall_top1: number;
  overall_top5: number;
  warm_top1: number;
  warm_top5: number;
  cold_top1: number;
  cold_top5: number;
  baseline: number;
  overall_top1_name: number;
  warm_top1_name: number;
  cold_top1_name: number;
  throughput_rows_per_s: number;
  throughput_workers: number;
  shared_name_share: number;
  curve: MatchCurvePoint[];
}

export interface MatchBatchResponse extends WithQueries {
  lines: MatchedLine[];
  batch: MatchBatchStats | null;
  measured: MatchMeasured;
  available: number;
  cold_suppliers: string[];
}

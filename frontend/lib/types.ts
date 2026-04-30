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
}

export interface POMetrics {
  automation_rate: number;
  avg_confidence: number;
  total: number;
  rule_count: number;
  aito_count: number;
  review_count: number;
}

export interface POQueueResponse {
  pos: POPrediction[];
  metrics: POMetrics;
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

export interface SmartEntryResponse {
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

export interface ApprovalResponse {
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

export interface AnomalyResponse {
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
  lift: number;
  total_orders: number;
  late_orders: number;
  risk_level: string;
}

export interface SupplierResponse {
  top_suppliers: SupplierSpend[];
  /** @deprecated Renamed to `top_suppliers`; will be dropped after migration. */
  spend_overview?: SupplierSpend[];
  delivery_risks: DeliveryRisk[];
}

/* ─── Rule Mining ─── */
export interface RuleCandidate {
  condition_field: string;
  condition_value: string;
  target_field: string;
  target_value: string;
  target_label: string;
  support_match: number;
  support_total: number;
  coverage: number;
  lift: number;
  strength: "strong" | "review" | "weak";
}

export interface RulesResponse {
  candidates: RuleCandidate[];
  summary: {
    total: number;
    strong: number;
    review: number;
    weak: number;
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

export interface CatalogResponse {
  products: IncompleteProduct[];
  total: number;
}

/* ─── Price Intelligence ─── */
export interface PriceEstimate {
  product_id: string;
  supplier: string;
  volume: number | null;
  estimated_price: number;
  price_min: number;
  price_max: number;
  range_low: number;
  range_high: number;
  confidence?: number;
  sample_size?: number;
}

export interface QuoteScore {
  supplier: string;
  quoted_price: number;
  estimated_price: number;
  deviation_pct: number;
  flagged: boolean;
  verdict: string;
}

export interface PricingProduct {
  product_id: string;
  name: string;
  supplier: string;
  estimate: PriceEstimate;
  quotes: QuoteScore[];
}

export interface PricingPPV {
  overall_pct: number;
  by_product: Record<string, number>;
  flagged_quotes: number;
  total_quotes: number;
  total_overpayment_eur: number;
  total_savings_eur: number;
  annualized_overpayment_eur: number;
}

export interface PricingResponse {
  products: Record<string, PricingProduct>;
  ppv?: PricingPPV;
}

/* ─── Demand Forecast ─── */
export interface DemandForecast {
  product_id: string;
  product_name: string;
  month: string;
  baseline: number;
  forecast: number;
  trend: "up" | "down" | "stable";
  confidence: number;
  history?: Array<{ month: string; units: number }>;
}

export interface DemandImpact {
  spikes_predicted: number;
  drops_predicted: number;
  high_confidence_count: number;
  stockouts_prevented_eur: number;
  excess_prevented_eur: number;
  total_impact_eur: number;
}

export interface DemandResponse {
  forecasts: DemandForecast[];
  month: string;
  impact?: DemandImpact;
}

/* ─── Inventory Intelligence ─── */
export interface InventoryItem {
  product_id: string;
  product_name: string;
  stock_on_hand: number;
  daily_demand: number;
  days_of_supply: number;
  lead_time_days: number;
  reorder_point: number;
  status: "critical" | "low" | "ok" | "overstock";
  forecast_units: number;
  unit_price?: number;
  excess_units?: number;
  tied_capital_eur?: number;
  stockout_risk_eur?: number;
  substitutions?: Array<{ product_id: string; name: string; similarity: number }>;
}

export interface InventoryResponse {
  items: InventoryItem[];
  critical_count: number;
  low_count: number;
  overstock_count: number;
  ok_count: number;
  total_tied_capital_eur?: number;
  total_stockout_risk_eur?: number;
  target_freed_eur?: number;
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
  accuracy: number;
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

export interface OverviewMetrics {
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
    labor_savings_eur?: number;
    miscode_savings_eur?: number;
    hours_saved?: number;
    total_savings_eur?: number;
  };
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
  units_sold: number;
  months: number;
}

export interface CrossSellItem {
  sku: string;
  name: string;
  category: string | null;
  supplier: string | null;
  unit_price: number | null;
  /** P(clicked | prev_product = anchor) from Aito _recommend. */
  p_click: number;
  /** Same value as p_click — kept for back-compat with prior UI. */
  score: number;
}

export interface SimilarItem {
  sku: string;
  name: string;
  category: string | null;
  supplier: string | null;
  unit_price: number | null;
  score: number;
}

export interface RecommendationOverview {
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

export interface UtilizationOverview {
  rows: UtilizationRow[];
  summary: UtilizationSummary;
  project_types: string[];
}

export interface CapacityForecast {
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

export interface StaffingFactor {
  person: string;
  role_in_pattern: "boost" | "drag";
  lift: number;
  coverage: number;
  success_rate_with: number;
  success_rate_without: number;
}

export interface PortfolioResponse {
  kpis: ProjectKPIs;
  projects: ProjectRow[];
  staffing_factors: StaffingFactor[];
}

/* ─── Aito Panel ─── */
export interface AitoPanelConfig {
  operation: string;
  stats?: Array<{ label: string; value: string }>;
  description: string;
  query: string;
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

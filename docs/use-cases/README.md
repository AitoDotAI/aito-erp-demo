# Use case guides

Per-feature implementation guides for the Predictive ERP demo. Each
guide pairs a hero screenshot, the actual Aito query shape, the
service-side Python code, the relevant data schema, and honest notes
on tradeoffs and gotchas.

| # | Guide | Aito features used |
|---|-------|--------------------|
| 1 | [PO Queue](01-po-queue.md) | `_predict` × 3 (cost_center, account_code, approver) + hybrid rules |
| 2 | [Smart Entry](02-smart-entry.md) | Multi-field `_predict` in parallel, three-state `SmartField` |
| 3 | [Approval Routing](03-approval-routing.md) | `_predict` (approver, approval_level) + governance escalation rules |
| 4 | [Anomaly Detection](04-anomaly-detection.md) | Inverse `_predict` (low p = anomaly), three flag types |
| 5 | [Supplier Intel](05-supplier-intel.md) | `_relate` for delivery-risk discovery |
| 6 | [Rule Mining](06-rule-mining.md) | `_relate` with strength thresholds, governance promote/dismiss |
| 7 | [Catalog Intelligence](07-catalog-intelligence.md) | Multi-field `_predict`, workflow-blocking-only filter, bulk apply |
| 8 | [Price Intelligence](08-price-intelligence.md) | `_search` + statistics, quote scoring, PPV |
| 9 | [Demand Forecast](09-demand-forecast.md) | `_predict` blended with seasonal aggregation |
| 10 | [Inventory Intelligence](10-inventory-intelligence.md) | Demand × stock arithmetic, cash impact in € |
| 11 | [Automation Overview](11-automation-overview.md) | `_search` aggregation, learning curve from `routed_by × order_month` |
| 12 | [Project Portfolio](12-project-portfolio.md) | `_predict` success + `_relate` over `assignments.person` for staffing factors |
| 13 | [Utilization & Capacity](13-utilization.md) *(Studio-only)* | `_predict` role + allocation_pct on assignments (single-table after denormalising project_type) |
| 14 | [Recommendations](14-recommendations.md) *(Aurora-only)* | `_search` co-occurrence + attribute scoring (cross-sell + similar) |

Each guide is self-contained; read in any order. Prerequisites
(running demo, loaded data) are listed in the project [README](../../README.md).

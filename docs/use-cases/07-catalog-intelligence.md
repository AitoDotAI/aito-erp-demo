# Catalog Intelligence — Multi-field gap-filling

![Catalog Intelligence](../../screenshots/07-catalog.png)

*1,500 products in the catalog; 69 are workflow-incomplete (services
exempt from shipping fields); one click bulk-applies high-confidence
predictions across the lot*

## Overview

Catalog data rots in two directions: new products arrive
half-coded, and old products carry historical nulls in fields that
matter today (HS codes after a customs re-classification, tax
classes after a VAT rate change). The traditional fix is a
multi-month data-cleansing project.

Catalog Intelligence treats each missing field as a `_predict`
problem. For every product flagged as "workflow-incomplete", we
identify which of the 7 predictable fields are null, and run a
`_predict` per field using the remaining fields as context. Strong
predictions (≥ 85% confidence) are bulk-applicable across the
catalog with one click.

The "workflow-incomplete" filter is the interesting bit: a product
is incomplete only if it's missing a field that **blocks a real
downstream workflow**. Services don't ship, so a service product
with null `hs_code` and null `weight_kg` is fine.

## How it works

### Traditional vs. AI-powered catalog cleanup

**Traditional:**
- Manual data project: assign team, build spreadsheet, fill cells
- Burns weeks of labour on cells that the data already implies
- Same fields rot again in 18 months
- No confidence signal — bulk paste-and-pray

**With Aito:**
- One `_predict` per missing field per product
- Each prediction has its own confidence
- Bulk-apply gated at 85% — only the safe ones
- Audit trail per applied prediction

### Implementation

The catalog service in `src/catalog_service.py` filters to
workflow-blockers, then predicts each missing field:

```python
WORKFLOW_BLOCKING_FIELDS = [
    "category",        # → can't be searched / categorized
    "unit_price",      # → can't be quoted
    "account_code",    # → can't be invoiced
    "tax_class",       # → can't be billed
    "unit_of_measure", # → can't be ordered
]

def _is_workflow_incomplete(product: dict) -> bool:
    for f in WORKFLOW_BLOCKING_FIELDS:
        if product.get(f) is None or product.get(f) == "":
            return True
    cat = product.get("category", "") or ""
    if "Service" not in cat:
        # Physical goods need shipping data
        if not product.get("hs_code"): return True
        if product.get("weight_kg") is None: return True
    return False


def predict_attributes(client: AitoClient, sku: str) -> CatalogEnrichment:
    """Predict missing attributes for a specific product."""
    result = client.search("products", {"sku": sku}, limit=1)
    product = (result.get("hits") or [{}])[0]
    name = product.get("name", "")

    # Build context from known fields
    where = {}
    for f in ["sku", "name", "supplier"] + PREDICTABLE_FIELDS:
        val = product.get(f)
        if val is not None and val != "":
            where[f] = val

    # Predict each missing field independently
    predictions: list[AttributePrediction] = []
    for f in PREDICTABLE_FIELDS:
        if product.get(f) is not None and product.get(f) != "":
            continue
        predict_where = {k: v for k, v in where.items() if k != f}

        from src.why_processor import process_factors, extract_alternatives
        pred_result = client.predict("products", predict_where, f, limit=10)
        pred_hits = pred_result.get("hits", [])
        top = pred_hits[0] if pred_hits else {}
        conf = top.get("$p", 0.0) if top else 0.0

        predictions.append(AttributePrediction(
            field_name=f,
            predicted_value=str(top.get("feature", "")),
            confidence=conf,
            alternatives=extract_alternatives(pred_hits, skip_top=True, limit=3),
            why_factors=process_factors(top.get("$why"), conf) if top else {},
        ))

    return CatalogEnrichment(sku=sku, name=name,
                            predictions=predictions,
                            overall_confidence=min(p.confidence for p in predictions))
```

The query for one missing field:

```json
{
  "from": "products",
  "where": {
    "sku": "SKU-9901",
    "name": "Cable Gland M20",
    "supplier": "Caverion Suomi",
    "category": "electrical"
  },
  "predict": "hs_code",
  "select": [
    "$p",
    "feature",
    { "$why": { "highlight": { "posPreTag": "«", "posPostTag": "»" } } }
  ],
  "limit": 10
}
```

## Key features

### 1. Workflow-blocking filter, not "any null"
A naive "find any product with a null field" reports thousands of
non-issues. The `_is_workflow_incomplete` predicate codifies the
business rule: services don't ship, so null shipping fields don't
count. The 1,500-product catalog has 69 actual blockers.

### 2. Bulk-apply gated at 85%
The Apply All button only applies predictions where the *minimum*
confidence across that product's predicted fields is ≥ 85%. Lower
products go to a Review queue. Same gating logic as Smart Entry
(min, not avg).

### 3. Same SmartField popover as Smart Entry
The catalog page reuses `SmartField` and `WhyPopover` from Smart
Entry — gold italic + 🤖 for predicted values, click `?` for the
$why decomposition. One component, two surfaces.

### 4. Predictable-but-not-blocking fields still get predicted
`hs_code` and `weight_kg` are predictable but only block goods,
not services. The service still predicts them — the user might
want to fill them in even when not blocking. Only the
incomplete-list filter cares about workflow status.

## Data schema

```json
{
  "products": {
    "type": "table",
    "columns": {
      "sku":             { "type": "String" },
      "name":            { "type": "Text"   },
      "supplier":        { "type": "String" },
      "category":        { "type": "String" },
      "unit_price":      { "type": "Decimal"},
      "hs_code":         { "type": "String" },
      "unit_of_measure": { "type": "String" },
      "weight_kg":       { "type": "Decimal"},
      "account_code":    { "type": "String" },
      "tax_class":       { "type": "String" }
    }
  }
}
```

`name` is `Text` (tokenized) so Aito can match on word-level
patterns ("Cable Gland" → electrical). Categorical fields like
`category` and `tax_class` are `String` for exact match.

## Tradeoffs and gotchas

- **One `_predict` per missing field**: a product missing 5 fields
  triggers 5 calls. Sequential in the service; parallelize at the
  frontend level for the bulk-apply path. The cache table catches
  the per-field predictions.
- **Aliased keys in `to_dict`**: `AttributePrediction.to_dict`
  returns both `field_name` and `field`, both `predicted_value`
  and `value`, both `why_factors` and `why`. The frontend's
  `SmartField` came from Smart Entry and uses the shorter aliases;
  we preserved the originals for the catalog-specific UI. Worth
  consolidating eventually.
- **`unit_price` predictions are noisy**: prices are numeric and
  spread across history. `_predict` returns the most-frequent
  exact value, not a band. For low-volume SKUs this works; for
  high-volume the price tag shows "varies" — better handled in
  Price Intelligence (view 8) which uses `_search` + statistics.
- **Workflow filter is hardcoded**: `WORKFLOW_BLOCKING_FIELDS`
  lives in the service. A real ERP would let admins configure
  which fields block which workflows. The pattern is the same;
  the storage isn't.
- **No two-stage commit**: clicking Apply writes the predicted
  value back to the products table. There's no preview / staging
  area. For a real catalog you'd want a draft state.

## What this demo abstracts away

- **Two-stage commit (preview → apply) with rollback**. Bulk Apply
  here writes directly to `products`. Production wants a draft
  state: predictions land in a `products_pending` table, an
  approver reviews them in batch, only then does the merge happen
  — with a rollback path if a regression is spotted post-apply.
- **Master-data governance**. Some attributes (HS code, tax class)
  are *policy* per customer, not predictable. The demo treats
  every missing field as fair game; production reads a per-tenant
  `predictable_fields` list so policy attributes are surfaced for
  manual entry rather than predicted.
- **Image / OCR ingestion**. Real catalog gaps come from
  spec-sheet PDFs that suppliers email. Production runs OCR over
  the PDF, extracts candidate values, runs `_predict` to validate
  them against history. The demo skips ingestion entirely and
  starts from "the field is null in the DB".

## Try it live

[**Open Catalog Intelligence**](http://localhost:8400/catalog/) and
click into any incomplete product to see the per-field
explanations, or hit Apply All to bulk-fill high-confidence rows.

```bash
./do dev   # starts backend + frontend
```

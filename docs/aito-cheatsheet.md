# Aito Query Cheatsheet — ERP Demo

Verified query patterns and response shapes used in this project.

## _predict — Resolve a missing field

```json
POST /api/v1/_predict
{
  "from": "purchases",
  "where": {
    "supplier": "Elenia Oy",
    "description": "Electricity"
  },
  "predict": "account_code",
  "select": ["$p", "feature", "$why"]
}
```

**Response:**
```json
{
  "hits": [
    {
      "$p": 0.94,
      "feature": "6110",
      "$why": { "type": "relatedPropositionLift", ... }
    },
    { "$p": 0.04, "feature": "6120", ... },
    { "$p": 0.02, "feature": "5510", ... }
  ]
}
```

**Key points:**
- Predicted value is in `"feature"`, not in a key named after the field
- `$p` is the probability (0–1)
- `$why` is a recursive tree of `relatedPropositionLift` nodes
- Used in: PO Queue, Smart Entry, Approval, Catalog, Demand

## _relate — Discover feature relationships

```json
POST /api/v1/_relate
{
  "from": "purchases",
  "where": { "delivery_late": true },
  "relate": "supplier"
}
```

**Response:**
```json
{
  "hits": [
    {
      "related": { "supplier": { "$has": "Neste Oyj" } },
      "lift": 2.4,
      "fs": {
        "f": 48,
        "fCondition": 12,
        "fOnCondition": 8,
        "n": 200
      },
      "ps": {
        "p": 0.24,
        "pCondition": 0.06,
        "pOnCondition": 0.67
      }
    }
  ]
}
```

**Key fields:**
- `related` — the field value this hit is about
- `lift` — how much more likely given the condition
- `fs.fOnCondition` — count matching both condition and related value
- `fs.fCondition` — total matching the condition
- `fs.n` — total records in table
- Used in: Supplier Intel, Rule Mining

## _search — Retrieve matching records

```json
POST /api/v1/_search
{
  "from": "purchases",
  "where": { "supplier": "Neste Oyj" },
  "limit": 100
}
```

**Response:**
```json
{
  "offset": 0,
  "total": 48,
  "hits": [
    { "purchase_id": "PO-0001", "supplier": "Neste Oyj", ... },
    ...
  ]
}
```

**Key points:**
- `total` is the count matching the where clause
- `hits` contains the actual records (up to `limit`)
- Used in: Supplier Intel (spend grouping), Demand (history), Overview (counts)

## Schema operations

```
PUT  /api/v1/schema/{table}     — Create/replace table schema
GET  /api/v1/schema             — Get all table definitions
DELETE /api/v1/schema/{table}   — Drop table
POST /api/v1/data/{table}/batch — Upload records (100 per batch)
```

## $why tree structure

The `$why` response is a recursive tree:

```json
{
  "type": "relatedPropositionLift",
  "proposition": {
    "supplier": { "$has": "Elenia Oy" }
  },
  "value": 4.2,
  "factors": [
    {
      "type": "relatedPropositionLift",
      "proposition": { "description": { "$has": "Electricity" } },
      "value": 3.8,
      "factors": []
    }
  ]
}
```

Walk recursively, extract `proposition` field/value + `value` (lift score).

## Tables in this demo

| Table | Records | Purpose |
|-------|---------|---------|
| purchases | 200 | PO history — drives predictions |
| products | 50 | Product catalog — attribute enrichment |
| orders | 390 | Order history — demand forecasting |
| price_history | 200 | Pricing data — price estimation |
| prediction_cache | dynamic | Cache layer in Aito itself |

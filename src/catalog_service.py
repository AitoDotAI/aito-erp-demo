"""Product catalog enrichment — predict missing product attributes.

Searches the products table for items with incomplete data, then uses
Aito's _predict to fill in missing fields based on known attributes.
Useful for onboarding new products or cleaning up legacy catalog data.
"""

from dataclasses import dataclass, field
from typing import Any

from src.aito_client import AitoClient


# All product fields used for completeness calculation
ALL_PRODUCT_FIELDS = [
    "supplier", "category", "unit_price", "hs_code",
    "unit_of_measure", "weight_kg", "account_code", "tax_class",
]

# Fields whose absence blocks a real workflow. Services don't ship, so
# null hs_code / weight_kg on them is fine — those don't count.
WORKFLOW_BLOCKING_FIELDS = [
    "category",       # → can't be searched/categorized
    "unit_price",     # → can't be quoted
    "account_code",   # → can't be invoiced
    "tax_class",      # → can't be billed
    "unit_of_measure",# → can't be ordered
]

# Fields that can be predicted when missing
PREDICTABLE_FIELDS = [
    "category",
    "unit_price",
    "hs_code",
    "unit_of_measure",
    "weight_kg",
    "account_code",
    "tax_class",
]


def _is_workflow_incomplete(product: dict) -> bool:
    """A product is workflow-incomplete only if it's missing fields that
    actually block downstream use. Services lacking shipping fields are OK.
    Goods (non-services) lacking hs_code or weight are blocked."""
    for f in WORKFLOW_BLOCKING_FIELDS:
        if product.get(f) is None or product.get(f) == "":
            return True
    cat = product.get("category", "") or ""
    if "Service" not in cat:
        # Physical goods need shipping data
        if not product.get("hs_code"):
            return True
        if product.get("weight_kg") is None:
            return True
    return False


@dataclass
class AttributePrediction:
    field_name: str
    predicted_value: str
    confidence: float
    alternatives: list[dict] = field(default_factory=list)
    why_factors: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "field": self.field_name,                 # alias for frontend consistency
            "predicted_value": self.predicted_value,
            "value": self.predicted_value,            # alias
            "confidence": self.confidence,
            "alternatives": self.alternatives,
            "why_factors": self.why_factors,
            "why": self.why_factors,                  # alias to match SmartEntryField
        }


@dataclass
class IncompleteProduct:
    sku: str
    name: str
    known_fields: dict
    missing_fields: list[str]

    def to_dict(self) -> dict:
        total_fields = len(ALL_PRODUCT_FIELDS)
        missing_count = len(self.missing_fields)
        completeness = round((total_fields - missing_count) / total_fields, 2) if total_fields > 0 else 1.0
        result = {
            "sku": self.sku,
            "name": self.name,
            "missing_fields": self.missing_fields,
            "missing_count": missing_count,
            "completeness": completeness,
        }
        # Include known field values for display
        for field_name in ALL_PRODUCT_FIELDS:
            result[field_name] = self.known_fields.get(field_name)
        return result


@dataclass
class CatalogEnrichment:
    sku: str
    name: str
    predictions: list[AttributePrediction]
    overall_confidence: float

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "predictions": [p.to_dict() for p in self.predictions],
            "overall_confidence": self.overall_confidence,
        }


def _extract_why(hit: dict) -> list[dict]:
    """Extract human-readable $why factors from an Aito prediction hit."""
    why_data = hit.get("$why", {})
    factors: list[dict] = []
    _walk_why(why_data, factors)
    factors.sort(key=lambda f: abs(f.get("lift", 1.0)), reverse=True)
    return factors[:5]


def _walk_why(node: Any, factors: list[dict]) -> None:
    """Recursively walk the $why tree to extract factors."""
    if not isinstance(node, dict):
        return
    if node.get("type") == "relatedPropositionLift":
        prop = node.get("proposition", {})
        if isinstance(prop, dict):
            for field_name, field_val in prop.items():
                if isinstance(field_val, dict) and "$has" in field_val:
                    factors.append({
                        "field": field_name,
                        "value": str(field_val["$has"]),
                        "lift": node.get("value", 1.0),
                    })
        for child in node.get("factors", []):
            _walk_why(child, factors)
    elif "factors" in node:
        for child in node["factors"]:
            _walk_why(child, factors)


def _extract_alternatives(hits: list[dict]) -> list[dict]:
    """Extract top-3 alternatives from Aito prediction hits."""
    alts = []
    for hit in hits[:3]:
        alts.append({
            "value": str(hit.get("feature", "")),
            "confidence": hit.get("$p", 0.0),
        })
    return alts


def get_incomplete(client: AitoClient) -> tuple[list["IncompleteProduct"], int]:
    """Search the products table and find rows that block downstream workflows.

    A product is "incomplete" only when it's missing a field that actually
    prevents quoting / invoicing / customs export. Services with null
    weight/HS-code are considered complete (they don't ship).

    Returns (incomplete_list, total_products_in_catalog).
    """
    result = client.search("products", {}, limit=2000)
    hits = result.get("hits", [])
    total = result.get("total", len(hits))

    incomplete = []
    for product in hits:
        sku = product.get("sku", "")
        name = product.get("name", "")

        # Skip products that are workflow-complete even if they have nulls
        # in non-blocking fields (services without weight/HS).
        if not _is_workflow_incomplete(product):
            continue

        missing = []
        known = {}
        for f in PREDICTABLE_FIELDS:
            val = product.get(f)
            if val is None or val == "":
                missing.append(f)
            else:
                known[f] = val

        # Also include non-predictable known fields as context
        for f in ["sku", "name", "supplier"]:
            if product.get(f):
                known[f] = product[f]

        if missing:
            incomplete.append(IncompleteProduct(
                sku=sku,
                name=name,
                known_fields=known,
                missing_fields=missing,
            ))

    return incomplete, total


def predict_attributes(client: AitoClient, sku: str) -> CatalogEnrichment:
    """Predict missing attributes for a specific product.

    Fetches the product by SKU, identifies null fields, and predicts
    each one using the known fields as context.

    Args:
        client: Aito API client.
        sku: Product SKU to enrich.

    Returns:
        CatalogEnrichment with predictions for each missing field.
    """
    # Fetch the product
    result = client.search("products", {"sku": sku}, limit=1)
    hits = result.get("hits", [])
    if not hits:
        return CatalogEnrichment(sku=sku, name="", predictions=[], overall_confidence=0.0)

    product = hits[0]
    name = product.get("name", "")

    # Build context from known fields
    where = {}
    for f in ["sku", "name", "supplier"] + PREDICTABLE_FIELDS:
        val = product.get(f)
        if val is not None and val != "":
            where[f] = val

    # Find missing fields and predict each one
    predictions: list[AttributePrediction] = []
    for f in PREDICTABLE_FIELDS:
        val = product.get(f)
        if val is not None and val != "":
            continue  # Field already has a value

        # Remove the target field from context if present
        predict_where = {k: v for k, v in where.items() if k != f}

        from src.why_processor import process_factors, extract_alternatives as wp_extract_alternatives

        pred_result = client.predict("products", predict_where, f, limit=10)
        pred_hits = pred_result.get("hits", [])
        top = pred_hits[0] if pred_hits else {}
        conf = top.get("$p", 0.0) if top else 0.0

        predictions.append(AttributePrediction(
            field_name=f,
            predicted_value=str(top.get("feature", "")),
            confidence=conf,
            alternatives=wp_extract_alternatives(pred_hits, skip_top=True, limit=3),
            why_factors=process_factors(top.get("$why"), conf) if top else {},
        ))

    confidences = [p.confidence for p in predictions]
    overall = min(confidences) if confidences else 0.0

    return CatalogEnrichment(
        sku=sku,
        name=name,
        predictions=predictions,
        overall_confidence=overall,
    )

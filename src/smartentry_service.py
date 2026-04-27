"""Smart Entry — multi-field prediction from partial supplier context.

Given a subset of known fields (e.g. just the supplier name), predict
all remaining fields using Aito's _predict endpoint. Each field is
predicted independently so the user sees per-field confidence scores
and can accept or override each one.

Mirrors the "form fill" pattern from the accounting demo.
"""

from dataclasses import dataclass, field
from typing import Any

from src.aito_client import AitoClient


KNOWN_SUPPLIERS = [
    "Lindström Oy",
    "Caverion Suomi",
    "Elisa Oyj",
    "Fazer Food Services",
    "Neste Oyj",
]

# Fields that can be provided as input context
INPUT_FIELDS = {"supplier", "category", "description", "cost_center", "account_code"}

# Fields to predict when not already provided
PREDICT_FIELDS = [
    "cost_center",
    "account_code",
    "project",
    "approver",
]


@dataclass
class FieldPrediction:
    field_name: str
    predicted_value: str
    confidence: float
    alternatives: list[dict] = field(default_factory=list)
    why_factors: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "field": self.field_name,
            "label": self.field_name.replace("_", " ").title(),
            "value": self.predicted_value,
            "raw_value": self.predicted_value,
            "confidence": self.confidence,
            "predicted": True,
            "alternatives": self.alternatives,
            "why": self.why_factors,
        }


@dataclass
class SmartEntryResult:
    input_fields: dict
    predictions: list[FieldPrediction]
    overall_confidence: float

    def to_dict(self) -> dict:
        return {
            "where": self.input_fields,
            "fields": [p.to_dict() for p in self.predictions],
            "predicted_count": len(self.predictions),
            "avg_confidence": self.overall_confidence,
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


def predict_fields(client: AitoClient, known: dict) -> SmartEntryResult:
    """Predict all missing fields given a subset of known fields.

    Args:
        client: Aito API client.
        known: Dict of known field values, e.g. {"supplier": "Lindström Oy"}.

    Returns:
        SmartEntryResult with per-field predictions and overall confidence.
    """
    from src.why_processor import process_factors, extract_alternatives

    where = {k: v for k, v in known.items() if k in INPUT_FIELDS and v}
    fields_to_predict = [f for f in PREDICT_FIELDS if f not in known]

    predictions: list[FieldPrediction] = []

    for field_name in fields_to_predict:
        result = client.predict("purchases", where, field_name, limit=10)
        hits = result.get("hits", [])
        top = hits[0] if hits else {}

        top_p = top.get("$p", 0.0) if top else 0.0
        why = process_factors(top.get("$why"), top_p) if top else None
        alts = extract_alternatives(hits, skip_top=True, limit=3)

        predictions.append(FieldPrediction(
            field_name=field_name,
            predicted_value=str(top.get("feature", "")),
            confidence=top_p,
            alternatives=alts,
            why_factors=why or {},
        ))

    confidences = [p.confidence for p in predictions]
    overall = min(confidences) if confidences else 0.0

    return SmartEntryResult(
        input_fields=where,
        predictions=predictions,
        overall_confidence=overall,
    )


def get_supplier_suggestions(client: AitoClient) -> list[str]:
    """Return known supplier names for autocomplete."""
    return list(KNOWN_SUPPLIERS)

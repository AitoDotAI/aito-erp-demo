"""Approval routing predictions — who should approve each purchase order.

Combines Aito's _predict endpoint with business rules for escalation.
High-value or sensitive purchases are escalated to CFO or Board level
based on amount thresholds and category.
"""

from dataclasses import dataclass, field
from typing import Any

from src.aito_client import AitoClient


# Escalation rules — checked after Aito prediction
ESCALATION_RULES = [
    {
        "name": "Security > 5K → CFO",
        "match": lambda item: item["amount"] > 5000 and item.get("category") == "security",
        "level": "CFO",
        "reason": "Security spend over €5,000 requires CFO approval",
    },
    {
        "name": "Capex > 20K → Board",
        "match": lambda item: item["amount"] > 20000 and item.get("category") == "capex",
        "level": "Board",
        "reason": "Capital expenditure over €20,000 requires Board approval",
    },
    {
        "name": "Any > 50K → Board",
        "match": lambda item: item["amount"] > 50000,
        "level": "Board",
        "reason": "Any purchase over €50,000 requires Board approval",
    },
]


@dataclass
class ApprovalPrediction:
    purchase_id: str
    supplier: str
    amount: float
    escalation_reason: str | None
    predicted_approver: str
    confidence: float
    alternatives: list[dict] = field(default_factory=list)
    predicted_level: str = ""
    why: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "purchase_id": self.purchase_id,
            "supplier": self.supplier,
            "amount": self.amount,
            "escalation_reason": self.escalation_reason,
            "predicted_approver": self.predicted_approver,
            "confidence": self.confidence,
            "alternatives": self.alternatives,
            "predicted_level": self.predicted_level,
            "why": self.why,
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


def predict_approval(client: AitoClient, item: dict) -> ApprovalPrediction:
    """Predict approval routing for a single purchase order.

    Args:
        client: Aito API client.
        item: Dict with keys: purchase_id, supplier, amount, category.

    Returns:
        ApprovalPrediction with predicted approver and escalation info.
    """
    from src.why_processor import process_factors, extract_alternatives

    where = {"supplier": item["supplier"]}
    if item.get("category"):
        where["category"] = item["category"]

    # Predict approval level
    level_result = client.predict("purchases", where, "approval_level", limit=10)
    level_hits = level_result.get("hits", [])
    level_top = level_hits[0] if level_hits else {}

    # Predict approver
    approver_result = client.predict("purchases", where, "approver", limit=10)
    approver_hits = approver_result.get("hits", [])
    approver_top = approver_hits[0] if approver_hits else {}

    predicted_approver = str(approver_top.get("feature", ""))
    predicted_level = str(level_top.get("feature", ""))
    confidence = approver_top.get("$p", 0.0)

    # Check escalation rules — override Aito prediction if triggered
    escalation_reason = None
    for rule in ESCALATION_RULES:
        if rule["match"](item):
            escalation_reason = rule["reason"]
            predicted_level = rule["level"]
            confidence = 0.99  # Rule-based = high confidence
            break

    return ApprovalPrediction(
        purchase_id=item["purchase_id"],
        supplier=item["supplier"],
        amount=item["amount"],
        escalation_reason=escalation_reason,
        predicted_approver=predicted_approver,
        confidence=confidence,
        alternatives=extract_alternatives(approver_hits, skip_top=True, limit=3),
        predicted_level=predicted_level,
        why=process_factors(approver_top.get("$why"), confidence) if approver_top else {},
    )


def predict_batch(client: AitoClient, items: list[dict]) -> list[ApprovalPrediction]:
    """Predict approval routing for a batch of purchase orders."""
    return [predict_approval(client, item) for item in items]


# Per-tenant approval queue items. Each set has one CFO-threshold row
# (>€5K) and one board-threshold row (>€20K capex) so the predicted
# `approval_level` and escalation reason exercise both paths.
DEMO_APPROVAL_QUEUE_BY_TENANT: dict[str, list[dict]] = {
    "metsa": [
        {"purchase_id": "PO-7845", "supplier": "Abloy Oy",            "amount": 6100.00,  "category": "security",   "description": "Security upgrade — door locks"},
        {"purchase_id": "PO-7831", "supplier": "Siemens Finland",     "amount": 24500.00, "category": "capex",      "description": "PLC controller upgrade — Line 3"},
        {"purchase_id": "PO-7838", "supplier": "Harjula Consulting",  "amount": 8900.00,  "category": "consulting", "description": "ERP integration consulting"},
    ],
    "aurora": [
        {"purchase_id": "PO-7845", "supplier": "L'Oréal Finland",     "amount": 9800.00,  "category": "beauty",     "description": "Premium fragrance launch — flagship store"},
        {"purchase_id": "PO-7831", "supplier": "Verkkokauppa.com",    "amount": 26500.00, "category": "electronics","description": "TV restock — winter campaign"},
        {"purchase_id": "PO-7838", "supplier": "Adobe Systems",       "amount": 7200.00,  "category": "software",   "description": "Marketing tools — campaign Q2"},
    ],
    "studio": [
        {"purchase_id": "PO-7845", "supplier": "Amazon Web Services", "amount": 12800.00, "category": "software",   "description": "AWS overage — production env"},
        {"purchase_id": "PO-7831", "supplier": "RecruitFinland",      "amount": 22500.00, "category": "recruitment","description": "Engineering team hire — 3 placements"},
        {"purchase_id": "PO-7838", "supplier": "Eficode Training",    "amount": 8400.00,  "category": "training",   "description": "Engineering bootcamp cohort"},
    ],
}


def demo_approval_queue_for(tenant: str | None) -> list[dict]:
    return DEMO_APPROVAL_QUEUE_BY_TENANT.get(tenant or "metsa",
                                              DEMO_APPROVAL_QUEUE_BY_TENANT["metsa"])


# Backward-compat alias.
DEMO_APPROVAL_QUEUE = DEMO_APPROVAL_QUEUE_BY_TENANT["metsa"]

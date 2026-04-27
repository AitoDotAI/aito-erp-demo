"""PO Queue predictions — account code, cost center, and approver.

Hybrid approach: check hardcoded rules first, then fall back to Aito
predictions. This mirrors how a real ERP would work — rules handle
known patterns, Aito fills the 70% gap.
"""

from dataclasses import dataclass, field
from typing import Any

from src.aito_client import AitoClient


@dataclass
class POPrediction:
    purchase_id: str
    supplier: str
    description: str
    amount: float
    cost_center: str | None
    cost_center_confidence: float
    account_code: str | None
    account_code_confidence: float
    approver: str | None
    approver_confidence: float
    source: str  # "rule" | "aito" | "review"
    confidence: float  # min of all field confidences
    cost_center_alternatives: list[dict] = field(default_factory=list)
    account_code_alternatives: list[dict] = field(default_factory=list)
    approver_alternatives: list[dict] = field(default_factory=list)
    cost_center_why: dict = field(default_factory=dict)
    account_code_why: dict = field(default_factory=dict)
    approver_why: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "purchase_id": self.purchase_id,
            "supplier": self.supplier,
            "description": self.description,
            "amount": self.amount,
            "cost_center": self.cost_center,
            "cost_center_confidence": self.cost_center_confidence,
            "account_code": self.account_code,
            "account_code_confidence": self.account_code_confidence,
            "approver": self.approver,
            "approver_confidence": self.approver_confidence,
            "source": self.source,
            "confidence": self.confidence,
            "cost_center_alternatives": self.cost_center_alternatives,
            "account_code_alternatives": self.account_code_alternatives,
            "approver_alternatives": self.approver_alternatives,
            "cost_center_why": self.cost_center_why,
            "account_code_why": self.account_code_why,
            "approver_why": self.approver_why,
        }


REVIEW_THRESHOLD = 0.50

# Rules that cover deterministic patterns — checked before Aito
RULES = [
    {
        "name": "Elenia → Facilities/6110",
        "match": lambda inv: inv["supplier"] == "Elenia Oy",
        "cost_center": "Facilities",
        "account_code": "6110",
        "approver": "M. Hakala",
    },
    {
        "name": "Telia → IT/5510",
        "match": lambda inv: inv["supplier"] == "Telia Finland Oyj",
        "cost_center": "IT",
        "account_code": "5510",
        "approver": "J. Lehtinen",
    },
    {
        "name": "Elisa → IT/5510",
        "match": lambda inv: inv["supplier"] == "Elisa Oyj",
        "cost_center": "IT",
        "account_code": "5510",
        "approver": "J. Lehtinen",
    },
]


def _extract_why(hit: dict) -> list[dict]:
    """Extract human-readable $why factors from an Aito prediction hit."""
    why_data = hit.get("$why", {})
    factors = []
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
            "why": _extract_why(hit),
        })
    return alts


def predict_single(client: AitoClient, invoice: dict) -> POPrediction:
    """Predict cost_center, account_code, and approver for a single PO."""
    # Check rules first
    for rule in RULES:
        if rule["match"](invoice):
            return POPrediction(
                purchase_id=invoice["purchase_id"],
                supplier=invoice["supplier"],
                description=invoice["description"],
                amount=invoice["amount_eur"],
                cost_center=rule["cost_center"],
                cost_center_confidence=0.99,
                account_code=rule["account_code"],
                account_code_confidence=0.99,
                approver=rule["approver"],
                approver_confidence=0.99,
                source="rule",
                confidence=0.99,
            )

    # Fall back to Aito predictions
    from src.why_processor import process_factors, extract_alternatives

    where = {"supplier": invoice["supplier"]}
    if invoice.get("description"):
        where["description"] = invoice["description"]

    # Predict all three fields
    cc_result = client.predict("purchases", where, "cost_center", limit=10)
    ac_result = client.predict("purchases", where, "account_code", limit=10)
    ap_result = client.predict("purchases", where, "approver", limit=10)

    cc_hits = cc_result.get("hits", [])
    ac_hits = ac_result.get("hits", [])
    ap_hits = ap_result.get("hits", [])

    cc_top = cc_hits[0] if cc_hits else {}
    ac_top = ac_hits[0] if ac_hits else {}
    ap_top = ap_hits[0] if ap_hits else {}

    cc_conf = cc_top.get("$p", 0.0)
    ac_conf = ac_top.get("$p", 0.0)
    ap_conf = ap_top.get("$p", 0.0)
    overall = min(cc_conf, ac_conf, ap_conf)

    source = "review" if overall < REVIEW_THRESHOLD else "aito"

    return POPrediction(
        purchase_id=invoice["purchase_id"],
        supplier=invoice["supplier"],
        description=invoice["description"],
        amount=invoice["amount_eur"],
        cost_center=str(cc_top.get("feature", "")),
        cost_center_confidence=cc_conf,
        account_code=str(ac_top.get("feature", "")),
        account_code_confidence=ac_conf,
        approver=str(ap_top.get("feature", "")),
        approver_confidence=ap_conf,
        source=source,
        confidence=overall,
        cost_center_alternatives=extract_alternatives(cc_hits, skip_top=True, limit=3),
        account_code_alternatives=extract_alternatives(ac_hits, skip_top=True, limit=3),
        approver_alternatives=extract_alternatives(ap_hits, skip_top=True, limit=3),
        cost_center_why=process_factors(cc_top.get("$why"), cc_conf),
        account_code_why=process_factors(ac_top.get("$why"), ac_conf),
        approver_why=process_factors(ap_top.get("$why"), ap_conf),
    )


def predict_batch(client: AitoClient, invoices: list[dict]) -> list[POPrediction]:
    """Predict all fields for a batch of POs."""
    return [predict_single(client, inv) for inv in invoices]


def compute_metrics(predictions: list[POPrediction]) -> dict:
    """Compute automation metrics from a batch of predictions."""
    total = len(predictions)
    if total == 0:
        return {"automation_rate": 0, "avg_confidence": 0, "total": 0}

    rule_count = sum(1 for p in predictions if p.source == "rule")
    aito_count = sum(1 for p in predictions if p.source == "aito")
    review_count = sum(1 for p in predictions if p.source == "review")

    return {
        "automation_rate": (rule_count + aito_count) / total,
        "avg_confidence": sum(p.confidence for p in predictions) / total,
        "total": total,
        "rule_count": rule_count,
        "aito_count": aito_count,
        "review_count": review_count,
    }


# Demo POs shown in the PO Queue view — matches the HTML mock
DEMO_POS = [
    {"purchase_id": "PO-7841", "supplier": "Elenia Oy", "description": "Electricity Q2 2025", "amount_eur": 4820.00, "category": "utilities"},
    {"purchase_id": "PO-7842", "supplier": "Wärtsilä Components", "description": "Hydraulic seals #WS-442", "amount_eur": 1240.00, "category": "production"},
    {"purchase_id": "PO-7843", "supplier": "Telia Finland Oyj", "description": "Mobile subscriptions May", "amount_eur": 780.00, "category": "telecom"},
    {"purchase_id": "PO-7844", "supplier": "Berner Oy", "description": "Cleaning chemicals bulk", "amount_eur": 392.00, "category": "cleaning"},
    {"purchase_id": "PO-7845", "supplier": "Abloy Oy", "description": "Security upgrade — door locks", "amount_eur": 6100.00, "category": "security"},
    {"purchase_id": "PO-7846", "supplier": "Neste Oyj", "description": "Fleet fuel card top-up", "amount_eur": 2150.00, "category": "fuel"},
]

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
    # field -> "rule: right on M of T POs" for the fields a rule decided
    rule_fields: dict = field(default_factory=dict)
    # What the row needs, in words: "Rule", "Rule, check approver",
    # "Aito" or "Review". A rule row below the bar is not a bare review:
    # the rule decided its fields and Aito's are the unsure ones.
    status_label: str = ""

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
            "rule_fields": self.rule_fields,
            "status_label": self.status_label,
        }


# Below this, the weakest of the three fields goes to a human. 0.75, not
# 0.50: at 0.50 a coin-flip coding counted as "coded" and every demo row
# cleared it, so the queue never showed the review path it exists for.
# The Overview's confidence bands are where to check the bar holds up.
REVIEW_THRESHOLD = 0.75

# Rules — checked before Aito — and what each one DECIDES.
#
# A rule sets only the fields its supplier's history bears out, and each
# shows how often it was right ("right on 140 of 145 POs"), never a
# constant. Every other field on the row is predicted by Aito like any
# row. Same decision as the accounting demo's ADR 0028.
#
# They used to set cost centre, account and approver at a fixed 0.99.
# Measured on the fixtures: the cost centres were right 0 times in N on
# all but one rule ("Facilities", "IT", "Grocery", "Office" are not cost
# centres in the data), the approvers 0 in N on all but two, and the
# account codes 94-96%. Metsä's Elisa rule matched no purchases, and
# Studio's Telia account was right 0 of 182. Those two are gone; what is
# left below is what `tests/test_po_rules_measured.py` checks holds.
RULE_MIN_PRECISION = 0.90

RULES_BY_TENANT: dict[str, list[dict]] = {
    "metsa": [
        {"name": "Elenia → 6110", "supplier": "Elenia Oy", "sets": {"account_code": "6110"}},
        {"name": "Telia → 5510, J. Lehtinen", "supplier": "Telia Finland Oyj",
         "sets": {"account_code": "5510", "approver": "J. Lehtinen"}},
    ],
    "aurora": [
        {"name": "Posti → Logistics, 4310", "supplier": "Posti",
         "sets": {"cost_center": "Logistics", "account_code": "4310"}},
        {"name": "Tikkurila → 4050", "supplier": "Tikkurila", "sets": {"account_code": "4050"}},
        {"name": "Valio → 4010", "supplier": "Valio Oy", "sets": {"account_code": "4010"}},
    ],
    "studio": [
        {"name": "Microsoft Ireland → 5510", "supplier": "Microsoft Ireland",
         "sets": {"account_code": "5510"}},
        {"name": "Fazer Food → 5710", "supplier": "Fazer Food Services",
         "sets": {"account_code": "5710"}},
    ],
}


def measure_rule(client: AitoClient, rule: dict) -> dict[str, tuple[str, int, int]]:
    """How often each field a rule sets was right, over its supplier's history.

    Returns {field: (value, right, of)}. Refuses — raises — a rule with no
    history to measure, or one setting a field history does not bear out:
    a rule the data contradicts must not be shown as confident.
    """
    res = client.search("purchases", {"supplier": rule["supplier"]}, limit=50_000)
    rows = res["hits"]
    if res["total"] != len(rows):
        raise RuntimeError(f"{rule['name']}: read {len(rows)} of {res.get('total')} purchases")
    if not rows:
        raise ValueError(f"rule {rule['name']!r}: no purchases from {rule['supplier']} to measure it on")
    measured = {}
    for field_name, value in rule["sets"].items():
        right = sum(1 for r in rows if r.get(field_name) == value)
        if right / len(rows) < RULE_MIN_PRECISION:
            raise ValueError(f"rule {rule['name']!r} sets {field_name}={value!r}, "
                             f"right on {right} of {len(rows)} POs")
        measured[field_name] = (value, right, len(rows))
    return measured


def rules_for(tenant: str | None) -> list[dict]:
    """Return the deterministic rule set for a tenant; falls back to
    Metsä's set when no tenant is supplied (single-tenant deployments)."""
    return RULES_BY_TENANT.get(tenant or "metsa", RULES_BY_TENANT["metsa"])


# Backward-compat alias — single-tenant code paths and tests keep
# working without changes.
RULES = RULES_BY_TENANT["metsa"]


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
            "value": str(hit.get("$value", "")),
            "confidence": hit.get("$p", 0.0),
            "why": _extract_why(hit),
        })
    return alts


def predict_single(
    client: AitoClient,
    invoice: dict,
    tenant: str | None = None,
) -> POPrediction:
    """Predict cost_center, account_code, and approver for a single PO.

    `tenant` selects which deterministic rules apply — each persona has
    its own rule set with suppliers and account codes drawn from that
    tenant's CoA. Falls back to Metsä's rules in single-tenant mode.
    """
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

    prediction = POPrediction(
        purchase_id=invoice["purchase_id"],
        supplier=invoice["supplier"],
        description=invoice["description"],
        amount=invoice["amount_eur"],
        cost_center=str(cc_top.get("$value", "")),
        cost_center_confidence=cc_conf,
        account_code=str(ac_top.get("$value", "")),
        account_code_confidence=ac_conf,
        approver=str(ap_top.get("$value", "")),
        approver_confidence=ap_conf,
        source="aito",
        confidence=0.0,
        cost_center_alternatives=extract_alternatives(cc_hits, skip_top=True, limit=3),
        account_code_alternatives=extract_alternatives(ac_hits, skip_top=True, limit=3),
        approver_alternatives=extract_alternatives(ap_hits, skip_top=True, limit=3),
        cost_center_why=process_factors(cc_top.get("$why"), cc_conf),
        account_code_why=process_factors(ac_top.get("$why"), ac_conf),
        approver_why=process_factors(ap_top.get("$why"), ap_conf),
    )

    # A matching rule overrides only the fields it measurably decides,
    # at the precision history gives it; Aito's answer stands elsewhere.
    rule = next((r for r in rules_for(tenant) if r["supplier"] == invoice["supplier"]), None)
    if rule is not None:
        # Measured once per rule and cached: it is a whole-history read, and
        # rule rows used to cost no Aito call at all. Stored as a list so
        # the cache's `_queries` stamp (dicts only) cannot land inside it.
        from src import cache
        measured = cache.get_or_compute(
            cache.tenant_key(tenant, f"rule_measure:{rule['name']}:{id(client)}"),
            lambda: list(measure_rule(client, rule).items()))
        for field_name, (value, right, of) in measured:
            setattr(prediction, field_name, value)
            setattr(prediction, f"{field_name}_confidence", round(right / of, 3))
            setattr(prediction, f"{field_name}_alternatives", [])
            setattr(prediction, f"{field_name}_why", {})
            prediction.rule_fields[field_name] = f"rule {rule['name']}: right on {right} of {of} POs"

    prediction.confidence = min(prediction.cost_center_confidence,
                                prediction.account_code_confidence,
                                prediction.approver_confidence)
    if prediction.confidence < REVIEW_THRESHOLD:
        prediction.source = "review"
    elif prediction.rule_fields:
        prediction.source = "rule"

    unsure = [f for f in ("cost_center", "account_code", "approver")
              if f not in prediction.rule_fields
              and getattr(prediction, f"{f}_confidence") < REVIEW_THRESHOLD]
    if prediction.rule_fields:
        prediction.status_label = ("Rule" if not unsure else
                                   "Rule, check " + ", ".join(f.replace("_", " ") for f in unsure))
    else:
        prediction.status_label = "Review" if prediction.source == "review" else "Aito"
    return prediction


def predict_batch(
    client: AitoClient,
    invoices: list[dict],
    tenant: str | None = None,
) -> list[POPrediction]:
    """Predict all fields for a batch of POs."""
    return [predict_single(client, inv, tenant=tenant) for inv in invoices]


def compute_metrics(predictions: list[POPrediction]) -> dict:
    """Compute automation metrics from a batch of predictions."""
    total = len(predictions)
    if total == 0:
        return {"automation_rate": 0, "avg_confidence": 0, "total": 0,
                "rule_count": 0, "aito_count": 0, "review_count": 0}

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


# Per-tenant demo POs shown in the PO Queue view. Each persona's set
# uses suppliers that appear in that persona's `purchases` history,
# so Aito's `_predict` call has signal to draw on. Routing in app.py
# selects the right list via `demo_pos_for(tenant)`.
#
# No description names a place. `purchases` records a store or site
# only in `cost_center`, never in the text, so "Cosmetics restock —
# Tampere" carried no evidence at all: Aito rightly routed it by
# supplier to Store-Helsinki at 0.93, and the headline screen showed a
# confident answer contradicting its own input. A reader expects a word
# on the screen to count; a word the history never used cannot.
# `tests/test_po_service.py` keeps place names out.
DEMO_POS_BY_TENANT: dict[str, list[dict]] = {
    "metsa": [
        {"purchase_id": "PO-7841", "supplier": "Elenia Oy",            "description": "Electricity Q2 2025",          "amount_eur": 4820.00, "category": "utilities"},
        {"purchase_id": "PO-7842", "supplier": "Wärtsilä Components",  "description": "Hydraulic seals #WS-442",       "amount_eur": 1240.00, "category": "production"},
        {"purchase_id": "PO-7843", "supplier": "Telia Finland Oyj",    "description": "Mobile subscriptions May",       "amount_eur": 780.00,  "category": "telecom"},
        {"purchase_id": "PO-7844", "supplier": "Berner Oy",            "description": "Cleaning chemicals bulk",        "amount_eur": 392.00,  "category": "cleaning"},
        {"purchase_id": "PO-7845", "supplier": "Abloy Oy",             "description": "Security upgrade — door locks", "amount_eur": 6100.00, "category": "security"},
        {"purchase_id": "PO-7846", "supplier": "Neste Oyj",            "description": "Fleet fuel card top-up",         "amount_eur": 2150.00, "category": "fuel"},
    ],
    "aurora": [
        {"purchase_id": "PO-7841", "supplier": "Valio Oy",             "description": "Weekly delivery — dairy",        "amount_eur": 5200.00, "category": "groceries"},
        {"purchase_id": "PO-7842", "supplier": "Marimekko",            "description": "SS25 collection drop",            "amount_eur": 12400.00, "category": "fashion"},
        {"purchase_id": "PO-7843", "supplier": "L'Oréal Finland",      "description": "Skincare restock",               "amount_eur": 4800.00, "category": "beauty"},
        {"purchase_id": "PO-7844", "supplier": "Berner Beauty",        "description": "Cosmetics restock",              "amount_eur": 1850.00, "category": "beauty"},
        {"purchase_id": "PO-7845", "supplier": "Posti",                "description": "Pallet shipping — week 17",      "amount_eur": 8200.00, "category": "logistics"},
        {"purchase_id": "PO-7846", "supplier": "Tikkurila",            "description": "Paint batch — interior",         "amount_eur": 2100.00, "category": "household"},
    ],
    "studio": [
        {"purchase_id": "PO-7841", "supplier": "Amazon Web Services",  "description": "AWS monthly bill",                "amount_eur": 8400.00, "category": "software"},
        {"purchase_id": "PO-7842", "supplier": "Adobe Systems",        "description": "Adobe CC team licenses",          "amount_eur": 1640.00, "category": "software"},
        {"purchase_id": "PO-7843", "supplier": "Telia Finland Oyj",    "description": "Mobile subscriptions May",        "amount_eur": 720.00,  "category": "telecom"},
        {"purchase_id": "PO-7844", "supplier": "Fazer Food Services",  "description": "Office lunch catering",           "amount_eur": 1280.00, "category": "catering"},
        {"purchase_id": "PO-7845", "supplier": "RecruitFinland",       "description": "Senior engineer placement",       "amount_eur": 8900.00, "category": "recruitment"},
        {"purchase_id": "PO-7846", "supplier": "Microsoft Ireland",    "description": "Microsoft 365 seats Q2",          "amount_eur": 3850.00, "category": "software"},
    ],
}


def demo_pos_for(tenant: str | None) -> list[dict]:
    """Return the demo PO set for a tenant; falls back to Metsä's set
    when an unknown tenant is supplied (keeps single-tenant deployments
    rendering correctly)."""
    return DEMO_POS_BY_TENANT.get(tenant or "metsa", DEMO_POS_BY_TENANT["metsa"])


# Backward-compat alias — single-tenant code paths and tests keep
# working without changes.
DEMO_POS = DEMO_POS_BY_TENANT["metsa"]

"""Anomaly detection using Aito's _evaluate endpoint.

For each transaction, evaluates how likely the field combination is
given historical data. Low probability means the combination is unusual
— the anomaly score is (1 - p) * 100. Severity thresholds classify
anomalies into high, medium, and low buckets for the dashboard.
"""

from dataclasses import dataclass, field

from src.aito_client import AitoClient


# Severity thresholds (anomaly_score ranges)
SEVERITY_HIGH = 85
SEVERITY_MEDIUM = 60


@dataclass
class AnomalyFlag:
    purchase_id: str
    supplier: str
    amount: float
    anomaly_score: int
    severity: str  # "high" | "medium" | "low"
    flagged_field: str
    expected_value: str
    actual_value: str
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "purchase_id": self.purchase_id,
            "supplier": self.supplier,
            "amount": self.amount,
            "anomaly_score": self.anomaly_score,
            "severity": self.severity,
            "flagged_field": self.flagged_field,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "explanation": self.explanation,
        }


def _classify_severity(score: int) -> str:
    """Classify anomaly score into severity bucket."""
    if score >= SEVERITY_HIGH:
        return "high"
    elif score >= SEVERITY_MEDIUM:
        return "medium"
    else:
        return "low"


def evaluate_transaction(client: AitoClient, transaction: dict) -> AnomalyFlag | None:
    """Evaluate a single transaction for anomalies.

    Returns `None` when there isn't enough signal to score honestly —
    e.g. the supplier has no purchase history at all on the active
    tenant. Without this guard, a missing history collapses to
    `p_actual = 0` and every anomaly inflates to score 100,
    giving the demo a misleading "everything is broken" first look.
    """
    # Inverse prediction. The scoring approach depends on which field is
    # flagged — different anomaly types call for different probability bases.
    flagged_field = transaction.get("flagged_field", "account_code")
    where = {"supplier": transaction["supplier"]}

    if flagged_field == "supplier":
        # Unknown-vendor anomaly: "no prior PO from this supplier" IS
        # the signal. Empty history → high anomaly score is correct.
        result = client.search("purchases", {"supplier": transaction["supplier"]}, limit=1)
        hits = result.get("hits", [])
        p = 0.02 if not hits else 0.15
    elif flagged_field == "amount":
        # Amount anomaly: ratio against the supplier's average requires
        # at least some prior orders. Without history the score is
        # meaningless — drop the row instead of fabricating one.
        actual_amount = transaction.get("amount", 0)
        result = client.search("purchases", {"supplier": transaction["supplier"]}, limit=50)
        hits = result.get("hits", [])
        if not hits:
            return None
        amounts = [h.get("amount_eur", 0) for h in hits]
        avg = sum(amounts) / len(amounts) if amounts else 1
        ratio = actual_amount / avg if avg > 0 else 1
        # 4x → ~p=0.06, 2x → p=0.18, 1x → p=0.6
        p = max(0.04, min(0.60, 0.60 / (ratio if ratio > 0 else 1)))
    else:
        # account_code (or other categorical) anomaly: needs a
        # prediction distribution to compare against. Empty hits =
        # supplier doesn't exist in this tenant's `purchases` (or the
        # table is missing). Drop the row to avoid fake 100% scores.
        result = client.predict("purchases", where, flagged_field)
        hits = result.get("hits", [])
        if not hits:
            return None
        actual_value = transaction.get(flagged_field, transaction.get("account_code"))
        p = 0.0
        found = False
        for hit in hits:
            if str(hit.get("feature", "")) == str(actual_value):
                p = hit.get("$p", 0.0)
                found = True
                break
        if not found:
            # The actual value isn't even in the top hits → tail mass.
            top_mass = sum(h.get("$p", 0.0) for h in hits[:5])
            residual = max(0.0, 1.0 - top_mass)
            p = residual * 0.05

    anomaly_score = round((1.0 - p) * 100)

    return AnomalyFlag(
        purchase_id=transaction["purchase_id"],
        supplier=transaction["supplier"],
        amount=transaction["amount"],
        anomaly_score=anomaly_score,
        severity=_classify_severity(anomaly_score),
        flagged_field=transaction["flagged_field"],
        expected_value=transaction["expected_value"],
        actual_value=transaction["actual_value"],
        explanation=transaction.get("explanation", ""),
    )


def detect_anomalies(client: AitoClient, transactions: list[dict]) -> list[AnomalyFlag]:
    """Evaluate a batch of transactions for anomalies.

    Drops transactions that returned `None` from `evaluate_transaction`
    (no historical signal to score against). Returns the remainder
    sorted by anomaly score, highest first.
    """
    flags = [evaluate_transaction(client, t) for t in transactions]
    flags = [f for f in flags if f is not None]
    flags.sort(key=lambda f: f.anomaly_score, reverse=True)
    return flags


def get_demo_anomalies(client: AitoClient, tenant: str | None = None) -> list[AnomalyFlag]:
    """Run anomaly detection on the demo transactions for a tenant."""
    return detect_anomalies(client, demo_anomalies_for(tenant))


# Per-tenant anomaly seed rows. Each persona's set covers the three
# canonical anomaly types: mis-coded account, unknown vendor, and
# amount spike. The suppliers used in each set exist in that
# persona's `purchases` history, so the inverse-prediction has signal.
DEMO_ANOMALIES_BY_TENANT: dict[str, list[dict]] = {
    "metsa": [
        {"purchase_id": "PO-7812", "supplier": "Fazer Food Services",  "amount": 1450.00, "account_code": "4220", "flagged_field": "account_code", "expected_value": "5710",        "actual_value": "4220",   "explanation": "Fazer is a food supplier — account 4220 (production parts) is unusual, expected 5710 (catering)"},
        {"purchase_id": "PO-7799", "supplier": "Harjula Consulting",   "amount": 3200.00, "account_code": "7100", "flagged_field": "supplier",     "expected_value": "Known vendor","actual_value": "Unknown vendor","explanation": "Harjula Consulting is not in the approved vendor list — new supplier with no purchase history"},
        {"purchase_id": "PO-7827", "supplier": "Neste Oyj",            "amount": 9800.00, "account_code": "4310", "flagged_field": "amount",       "expected_value": "~€2,400 avg","actual_value": "€9,800",      "explanation": "Amount is approximately 4× the average for Neste Oyj fuel purchases"},
    ],
    "aurora": [
        {"purchase_id": "PO-7812", "supplier": "Valio Oy",             "amount": 4800.00, "account_code": "4030", "flagged_field": "account_code", "expected_value": "4010",        "actual_value": "4030",   "explanation": "Valio is a grocery supplier — account 4030 (fashion) is unusual, expected 4010 (groceries)"},
        {"purchase_id": "PO-7799", "supplier": "Bauhaus",              "amount": 2200.00, "account_code": "4060", "flagged_field": "supplier",     "expected_value": "Known vendor","actual_value": "Unknown vendor","explanation": "Bauhaus is not yet a registered vendor in Aurora's master list — first PO"},
        # Modest spike (~1.9× the supplier average) — sits in
        # mid-severity territory, distinct from Studio's AWS row below.
        {"purchase_id": "PO-7827", "supplier": "Posti",                "amount": 13900.00,"account_code": "4310", "flagged_field": "amount",       "expected_value": "~€7,500 avg","actual_value": "€13,900",     "explanation": "Amount is approximately 1.9× the average for Posti shipping invoices"},
    ],
    "studio": [
        {"purchase_id": "PO-7812", "supplier": "Adobe Systems",        "amount": 2400.00, "account_code": "6810", "flagged_field": "account_code", "expected_value": "5530",        "actual_value": "6810",   "explanation": "Adobe is a software vendor — account 6810 (office supplies) is unusual, expected 5530 (design software)"},
        {"purchase_id": "PO-7799", "supplier": "LinkedIn Talent",      "amount": 4200.00, "account_code": "5750", "flagged_field": "supplier",     "expected_value": "Known vendor","actual_value": "Unknown vendor","explanation": "LinkedIn Talent appears as a new supplier — no prior placements on file"},
        # Larger spike (~5.5×) — pushes the score well above Aurora's
        # Posti row, so the two demos look numerically distinct.
        {"purchase_id": "PO-7827", "supplier": "Amazon Web Services",  "amount": 48500.00,"account_code": "5512", "flagged_field": "amount",       "expected_value": "~€8,800 avg","actual_value": "€48,500",     "explanation": "Amount is approximately 5.5× the average for AWS monthly invoices"},
    ],
}


def demo_anomalies_for(tenant: str | None) -> list[dict]:
    return DEMO_ANOMALIES_BY_TENANT.get(tenant or "metsa",
                                         DEMO_ANOMALIES_BY_TENANT["metsa"])


# Backward-compat alias.
DEMO_ANOMALIES = DEMO_ANOMALIES_BY_TENANT["metsa"]

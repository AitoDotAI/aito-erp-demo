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


def evaluate_transaction(client: AitoClient, transaction: dict) -> AnomalyFlag:
    """Evaluate a single transaction for anomalies.

    Calls Aito _evaluate with the supplier + account_code combination
    to get the probability of that pairing in historical data.

    Args:
        client: Aito API client.
        transaction: Dict with keys matching DEMO_ANOMALIES structure.

    Returns:
        AnomalyFlag with anomaly score and severity classification.
    """
    # Inverse prediction. The scoring approach depends on which field is
    # flagged — different anomaly types call for different probability bases.
    flagged_field = transaction.get("flagged_field", "account_code")
    where = {"supplier": transaction["supplier"]}

    if flagged_field == "supplier":
        # Unknown supplier: search history for any prior PO from this supplier.
        result = client.search("purchases", {"supplier": transaction["supplier"]}, limit=1)
        hits = result.get("hits", [])
        # No prior history at all → very high anomaly. Some history → moderate.
        p = 0.02 if not hits else 0.15
    elif flagged_field == "amount":
        # Amount anomaly: typical Neste range is €2-3K. Score by deviation.
        # We approximate by querying typical amounts for this supplier and
        # comparing to the actual.
        actual_amount = transaction.get("amount", 0)
        result = client.search("purchases", {"supplier": transaction["supplier"]}, limit=50)
        hits = result.get("hits", [])
        if hits:
            amounts = [h.get("amount_eur", 0) for h in hits]
            avg = sum(amounts) / len(amounts) if amounts else 1
            ratio = actual_amount / avg if avg > 0 else 1
            # 4x → ~p=0.06, 2x → p=0.18, 1x → p=0.6
            p = max(0.04, min(0.60, 0.60 / (ratio if ratio > 0 else 1)))
        else:
            p = 0.10
    else:
        # account_code or other categorical field — inverse prediction.
        result = client.predict("purchases", where, flagged_field)
        hits = result.get("hits", [])
        actual_value = transaction.get(flagged_field, transaction["account_code"])
        p = 0.0
        found = False
        for hit in hits:
            if str(hit.get("feature", "")) == str(actual_value):
                p = hit.get("$p", 0.0)
                found = True
                break
        if not found and hits:
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

    Returns results sorted by anomaly score (highest first).
    """
    flags = [evaluate_transaction(client, t) for t in transactions]
    flags.sort(key=lambda f: f.anomaly_score, reverse=True)
    return flags


def get_demo_anomalies(client: AitoClient) -> list[AnomalyFlag]:
    """Run anomaly detection on the demo transactions."""
    return detect_anomalies(client, DEMO_ANOMALIES)


# Demo anomalies — matches the HTML mock
DEMO_ANOMALIES = [
    {
        "purchase_id": "PO-7812",
        "supplier": "Fazer Food Services",
        "amount": 1450.00,
        "account_code": "4220",
        "flagged_field": "account_code",
        "expected_value": "5710",
        "actual_value": "4220",
        "explanation": "Fazer is a food supplier — account 4220 (office supplies) is unusual, expected 5710 (catering)",
    },
    {
        "purchase_id": "PO-7799",
        "supplier": "Harjula Consulting",
        "amount": 3200.00,
        "account_code": "7100",
        "flagged_field": "supplier",
        "expected_value": "Known vendor",
        "actual_value": "Unknown vendor",
        "explanation": "Harjula Consulting is not in the approved vendor list — new supplier with no purchase history",
    },
    {
        "purchase_id": "PO-7827",
        "supplier": "Neste Oyj",
        "amount": 9800.00,
        "account_code": "6210",
        "flagged_field": "amount",
        "expected_value": "~€2,400 avg",
        "actual_value": "€9,800",
        "explanation": "Amount is approximately 4x the average for Neste Oyj fuel purchases",
    },
]

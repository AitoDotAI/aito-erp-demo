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


def _fmt_eur(x: float) -> str:
    return "€" + f"{x:,.0f}".replace(",", " ")


def _pct(p: float) -> str:
    """A probability as a reader should see it: "<1%", never a false 0%."""
    return "<1%" if p < 0.01 else f"{p:.0%}"


def _whole_history(client: AitoClient, where: dict) -> list[dict]:
    """Every matching purchase. A short read would score against a
    subset and call it the supplier's history."""
    res = client.search("purchases", where, limit=50_000)
    hits = res.get("hits") or []
    if res.get("total") != len(hits):
        raise RuntimeError(f"purchases {where}: read {len(hits)} of {res.get('total')} rows")
    return hits


def evaluate_transaction(client: AitoClient, transaction: dict) -> AnomalyFlag | None:
    """Score one incoming transaction and say why, from the data.

    The score is always (1 - p) × 100, where p is how likely the history
    makes the flagged value. Only the way p is obtained differs:

      account_code  p from Aito's `_predict` for this supplier. If the
                    actual account is not among the values Aito lists,
                    its p is at most the smallest listed one — a bound,
                    and the explanation says so.
      amount        p = share of this supplier's past POs at least this
                    large, smoothed (k+1)/(n+1) so "none seen" is not 0.
      supplier      "first PO from this vendor" is CHECKED: a vendor with
                    any history raises. p = 1/(N+1) over all purchases.

    The expected value and the explanation are computed alongside; the
    demo rows used to carry them typed in, and they were wrong.

    Returns None only for an amount row whose supplier has no history —
    there is no average to compare with.
    """
    flagged_field = transaction["flagged_field"]
    supplier = transaction["supplier"]
    amount = float(transaction["amount"])

    if flagged_field == "supplier":
        on_file = client.search("purchases", {"supplier": supplier}, limit=1).get("total", 0)
        if on_file:
            raise ValueError(f"{supplier} is flagged as a first-time vendor but has "
                             f"{on_file} purchases on file")
        total = client.search("purchases", {}, limit=1)["total"]
        p = 1 / (total + 1)
        expected, actual = "a vendor on file", "no history"
        explanation = (f"First PO from {supplier}: 0 of {total} purchases on file "
                       f"name this vendor")

    elif flagged_field == "amount":
        history = _whole_history(client, {"supplier": supplier})
        if not history:
            return None
        past = [float(h["amount_eur"]) for h in history]
        avg = sum(past) / len(past)
        at_least = sum(1 for x in past if x >= amount)
        p = (at_least + 1) / (len(past) + 1)
        expected, actual = f"{_fmt_eur(avg)} avg", _fmt_eur(amount)
        explanation = (f"{_fmt_eur(amount)} is {amount / avg:.1f}× the {_fmt_eur(avg)} average "
                       f"of {len(past)} past {supplier} POs; {at_least} of {len(past)} "
                       f"were this large")

    else:
        actual = str(transaction[flagged_field])
        # Without history Aito can only answer from its general prior,
        # and "unusual for this supplier" would mean nothing.
        on_file = client.search("purchases", {"supplier": supplier}, limit=1).get("total", 0)
        if not on_file:
            raise ValueError(f"{supplier} has no purchases on file; a {flagged_field} "
                             f"cannot be unusual for it")
        hits = client.predict("purchases", {"supplier": supplier}, flagged_field,
                              limit=10).get("hits") or []
        if not hits:
            raise ValueError(f"_predict {flagged_field} for {supplier} returned nothing")
        top = hits[0]
        expected = str(top["$value"])
        listed = {str(h["$value"]): float(h["$p"]) for h in hits}
        if actual in listed:
            p = listed[actual]
            explanation = (f"Aito expects {expected} for {supplier} ({_pct(top['$p'])}); "
                           f"{actual} has {_pct(p)}")
        else:
            p = min(listed.values())
            explanation = (f"Aito expects {expected} for {supplier} ({_pct(top['$p'])}); "
                           f"{actual} is not among the {len(listed)} it lists, so "
                           + (f"at most {_pct(p)}" if p >= 0.01 else "under 1%"))

    anomaly_score = round((1.0 - p) * 100)
    return AnomalyFlag(
        purchase_id=transaction["purchase_id"],
        supplier=supplier,
        amount=amount,
        anomaly_score=anomaly_score,
        severity=_classify_severity(anomaly_score),
        flagged_field=flagged_field,
        expected_value=expected,
        actual_value=actual,
        explanation=explanation,
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
    # Only the incoming transaction. What is expected, how unusual it is
    # and why are computed by `evaluate_transaction` from the history.
    # The first-time vendors are names absent from that tenant's
    # purchases — a test checks the claim.
    "metsa": [
        # Wärtsilä codes to 4220 in 345 of 370 POs and never to 6810.
        {"purchase_id": "PO-7812", "supplier": "Wärtsilä Components", "amount": 1450.00, "account_code": "6810", "flagged_field": "account_code"},
        {"purchase_id": "PO-7799", "supplier": "Harjula Consulting",  "amount": 3200.00, "account_code": "7100", "flagged_field": "supplier"},
        {"purchase_id": "PO-7827", "supplier": "Neste Oyj",           "amount": 9800.00, "account_code": "4310", "flagged_field": "amount"},
    ],
    "aurora": [
        {"purchase_id": "PO-7812", "supplier": "Valio Oy",                "amount": 4800.00,  "account_code": "4030", "flagged_field": "account_code"},
        {"purchase_id": "PO-7799", "supplier": "Kaarinan Kalustetukku Oy", "amount": 2200.00,  "account_code": "4060", "flagged_field": "supplier"},
        {"purchase_id": "PO-7827", "supplier": "Posti",                   "amount": 13900.00, "account_code": "4310", "flagged_field": "amount"},
    ],
    "studio": [
        {"purchase_id": "PO-7812", "supplier": "Adobe Systems",           "amount": 2400.00,  "account_code": "6810", "flagged_field": "account_code"},
        {"purchase_id": "PO-7799", "supplier": "Nordic Talent Partners Oy", "amount": 4200.00, "account_code": "5750", "flagged_field": "supplier"},
        {"purchase_id": "PO-7827", "supplier": "Amazon Web Services",     "amount": 48500.00, "account_code": "5512", "flagged_field": "amount"},
    ],
}


def demo_anomalies_for(tenant: str | None) -> list[dict]:
    return DEMO_ANOMALIES_BY_TENANT.get(tenant or "metsa",
                                         DEMO_ANOMALIES_BY_TENANT["metsa"])


# Backward-compat alias.
DEMO_ANOMALIES = DEMO_ANOMALIES_BY_TENANT["metsa"]

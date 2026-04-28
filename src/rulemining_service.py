"""Rule mining — discover account code assignment patterns using _relate.

For each condition field (supplier, category), finds distinct values
via _search, then uses _relate to discover which account codes are
strongly associated. Rules with high confidence (lift) can be promoted
to automation rules, reducing manual coding work.

Same pattern as the accounting demo's rule mining.
"""

from dataclasses import dataclass

from src.aito_client import AitoClient


MIN_SUPPORT = 3  # Minimum number of observations to consider a rule

# Strength thresholds based on confidence (pOnCondition)
STRONG_THRESHOLD = 0.95
REVIEW_THRESHOLD = 0.75

CONDITION_FIELDS = ["supplier", "category"]


@dataclass
class RuleCandidate:
    condition_field: str
    condition_value: str
    predicted_field: str
    predicted_value: str
    confidence: float  # pOnCondition — how often this rule holds
    support: int  # fOnCondition — how many observations
    lift: float
    strength: str  # "strong" | "review" | "weak"

    def to_dict(self) -> dict:
        return {
            "condition_field": self.condition_field,
            "condition_value": self.condition_value,
            "predicted_field": self.predicted_field,
            "predicted_value": self.predicted_value,
            "confidence": self.confidence,
            "support": self.support,
            "lift": self.lift,
            "strength": self.strength,
        }


def _classify_strength(confidence: float) -> str:
    """Classify rule strength based on confidence."""
    if confidence >= STRONG_THRESHOLD:
        return "strong"
    elif confidence >= REVIEW_THRESHOLD:
        return "review"
    else:
        return "weak"


def _get_distinct_values(client: AitoClient, field_name: str) -> list[str]:
    """Get distinct values for a field by searching purchases."""
    result = client.search("purchases", {}, limit=2000)
    hits = result.get("hits", [])
    values = {row.get(field_name, "") for row in hits if row.get(field_name)}
    return sorted(values)


def mine_rules(client: AitoClient) -> list[RuleCandidate]:
    """Discover account code assignment rules from purchase history.

    For each condition field (supplier, category):
    1. Get distinct values via search.
    2. For each value, use _relate to find associated account codes.
    3. Extract confidence, support, and lift.
    4. Filter by minimum support and classify strength.

    Returns:
        List of RuleCandidate sorted by confidence (highest first).
    """
    candidates: list[RuleCandidate] = []

    for cond_field in CONDITION_FIELDS:
        distinct_values = _get_distinct_values(client, cond_field)

        for value in distinct_values:
            result = client.relate(
                "purchases",
                {cond_field: value},
                "account_code",
            )
            hits = result.get("hits", [])

            for hit in hits:
                related = hit.get("related", {})
                account_info = related.get("account_code", {})
                account_code = (
                    account_info.get("$has", "")
                    if isinstance(account_info, dict)
                    else str(account_info)
                )

                if not account_code:
                    continue

                fs = hit.get("fs", {})
                ps = hit.get("ps", {})
                lift = hit.get("lift", 1.0)

                support = fs.get("fOnCondition", 0)
                confidence = ps.get("pOnCondition", 0.0)

                if support < MIN_SUPPORT:
                    continue

                candidates.append(RuleCandidate(
                    condition_field=cond_field,
                    condition_value=value,
                    predicted_field="account_code",
                    predicted_value=account_code,
                    confidence=round(confidence, 3),
                    support=support,
                    lift=round(lift, 2),
                    strength=_classify_strength(confidence),
                ))

    candidates.sort(key=lambda r: r.confidence, reverse=True)
    return _dedupe_equivalent_rules(candidates)


# Mining `_relate` over single-value conditions yields algebraically
# equivalent rules whenever a supplier↔category mapping is 1:1: every
# Schneider PO is electrical, so "supplier=Schneider→4225" and
# "category=electrical→4225" both surface with identical (confidence,
# support, lift). Two rows; one operational outcome. Collapse them
# so the candidate list is read-as-distinct-patterns.
_FIELD_PRIORITY = {"supplier": 0, "description": 1, "category": 2}


def _dedupe_equivalent_rules(candidates: list[RuleCandidate]) -> list[RuleCandidate]:
    """Drop rules with identical (predicted_field, predicted_value,
    confidence, support, lift) — keep the most specific condition_field.

    Specificity ranking from `_FIELD_PRIORITY`: supplier > description
    > category > anything else. Ties broken alphabetically on
    condition_value for determinism.
    """
    by_signature: dict[tuple, list[RuleCandidate]] = {}
    for c in candidates:
        sig = (c.predicted_field, c.predicted_value, c.confidence, c.support, c.lift)
        by_signature.setdefault(sig, []).append(c)

    deduped: list[RuleCandidate] = []
    for group in by_signature.values():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        group.sort(key=lambda r: (
            _FIELD_PRIORITY.get(r.condition_field, 99),
            r.condition_value,
        ))
        deduped.append(group[0])

    deduped.sort(key=lambda r: r.confidence, reverse=True)
    return deduped


def get_rule_summary(candidates: list[RuleCandidate]) -> dict:
    """Summarize mined rules by strength category."""
    strong = [c for c in candidates if c.strength == "strong"]
    review = [c for c in candidates if c.strength == "review"]
    weak = [c for c in candidates if c.strength == "weak"]

    return {
        "total": len(candidates),
        "strong": len(strong),
        "review": len(review),
        "weak": len(weak),
        "automation_potential": round(len(strong) / len(candidates), 3) if candidates else 0,
        "rules": [c.to_dict() for c in candidates],
    }

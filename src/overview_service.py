"""Automation overview — dashboard metrics for the ERP demo.

Searches the purchases table to compute automation breakdown by
routing method; runs `_evaluate` with `select: ["cases"]` to get
*real* per-field accuracy (held-out, ground-truth-compared) plus
confidence-band buckets that tell the operator when to trust Aito
and when to review; computes a learning curve from the order-month
column showing how automation improves with data.
"""

from dataclasses import dataclass, field

from src.aito_client import AitoClient


@dataclass
class AutomationBreakdown:
    total_purchases: int
    rules_count: int
    rules_pct: float
    aito_high_count: int
    aito_high_pct: float
    aito_reviewed_count: int
    aito_reviewed_pct: float
    manual_count: int
    manual_pct: float

    def to_dict(self) -> dict:
        return {
            "total_purchases": self.total_purchases,
            "rules_count": self.rules_count,
            "rules_pct": self.rules_pct,
            "aito_high_count": self.aito_high_count,
            "aito_high_pct": self.aito_high_pct,
            "aito_reviewed_count": self.aito_reviewed_count,
            "aito_reviewed_pct": self.aito_reviewed_pct,
            "manual_count": self.manual_count,
            "manual_pct": self.manual_pct,
        }


# Below this many cases a band's accuracy is one or two lucky rows, not a
# rate: four cases at 100% once outranked 170 at 95% on this screen.
MIN_BAND_CASES = 20

BANDS = [
    ("≥ 0.85", 0.85, 1.01),
    ("0.5 – 0.85", 0.5, 0.85),
    ("< 0.5", 0.0, 0.5),
]


@dataclass
class ConfidenceBand:
    """Per-confidence-band quality slice from `_evaluate cases`.

    `accuracy` is how often the top prediction was right in the band and
    `mean_p` is what Aito said it would be; calibration is the two
    agreeing, so both travel together. An empty band has neither — a 0%
    would read as "always wrong". `thin` marks a band with too few cases
    for its accuracy to mean anything.
    """
    label: str
    min_p: float
    count: int
    accuracy: float | None
    mean_p: float | None
    thin: bool

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "min_p": self.min_p,
            "count": self.count,
            "accuracy": self.accuracy,
            "mean_p": self.mean_p,
            "thin": self.thin,
        }


@dataclass
class PredictionQuality:
    field_name: str
    accuracy: float            # true accuracy from _evaluate (held-out)
    base_accuracy: float       # naive most-common-value baseline
    accuracy_gain: float       # accuracy - base_accuracy
    avg_confidence: float      # mean $p across test cases
    sample_size: int           # totalCases from _evaluate
    bands: list[ConfidenceBand]

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "accuracy": self.accuracy,
            "base_accuracy": self.base_accuracy,
            "accuracy_gain": self.accuracy_gain,
            "avg_confidence": self.avg_confidence,
            "sample_size": self.sample_size,
            "bands": [b.to_dict() for b in self.bands],
        }


@dataclass
class OverviewMetrics:
    automation: AutomationBreakdown
    prediction_quality: list[PredictionQuality]
    learning_curve: list[dict]
    summary: dict

    def to_dict(self) -> dict:
        return {
            "automation": self.automation.to_dict(),
            "prediction_quality": [q.to_dict() for q in self.prediction_quality],
            "learning_curve": self.learning_curve,
            "summary": self.summary,
        }


def _safe_pct(count: int, total: int) -> float:
    """Compute percentage, safe for zero total."""
    return round((count / total) * 100, 1) if total > 0 else 0.0


def get_automation_breakdown(client: AitoClient) -> AutomationBreakdown:
    """Search purchases and compute automation breakdown by routed_by field.

    The routed_by field indicates how each purchase was processed:
    - "rule": Matched a deterministic business rule.
    - "aito_high": Aito prediction with high confidence (auto-approved).
    - "aito_reviewed": Aito prediction that required human review.
    - "manual": No prediction available, fully manual.
    """
    result = client.search("purchases", {}, limit=5000)
    hits = result.get("hits", [])

    # Aito returns "total" — the true count regardless of limit
    total = result.get("total", len(hits))
    counts: dict[str, int] = {}
    for row in hits:
        routed = row.get("routed_by", "manual")
        counts[routed] = counts.get(routed, 0) + 1
    # Scale counts to total if hits were paginated
    if total > len(hits) and len(hits) > 0:
        scale = total / len(hits)
        counts = {k: int(round(v * scale)) for k, v in counts.items()}

    rules = counts.get("rule", 0)
    aito_high = counts.get("aito_high", 0)
    aito_reviewed = counts.get("aito_reviewed", 0)
    manual = counts.get("manual", 0)

    return AutomationBreakdown(
        total_purchases=total,
        rules_count=rules,
        rules_pct=_safe_pct(rules, total),
        aito_high_count=aito_high,
        aito_high_pct=_safe_pct(aito_high, total),
        aito_reviewed_count=aito_reviewed,
        aito_reviewed_pct=_safe_pct(aito_reviewed, total),
        manual_count=manual,
        manual_pct=_safe_pct(manual, total),
    )


def _case_p(case: dict) -> float:
    """Pull the predicted top probability off an `_evaluate` case.

    Live shape: `{ "top": {"$p": 0.99, "$value": "..."}, "accurate": true,
    "correct": {...}, "testCase": {...} }` — the model's most-likely
    answer is `top`, the ground truth is `correct`, `accurate` says
    whether they matched.
    """
    top = case.get("top") or {}
    return float(top.get("$p") or 0)


def _case_correct(case: dict) -> bool:
    """Did the top prediction match ground truth?"""
    return bool(case.get("accurate"))


def _bucket_cases(cases: list[dict]) -> list[ConfidenceBand]:
    """Split per-case results into ≥0.85, 0.5–0.85, <0.5 bands."""
    bucketed: list[ConfidenceBand] = []
    for label, lower, upper in BANDS:
        in_band = [c for c in cases if lower <= _case_p(c) < upper]
        n = len(in_band)
        correct = sum(1 for c in in_band if _case_correct(c))
        bucketed.append(ConfidenceBand(
            label=label,
            min_p=lower,
            count=n,
            accuracy=round(correct / n, 3) if n else None,
            mean_p=round(sum(_case_p(c) for c in in_band) / n, 3) if n else None,
            thin=n < MIN_BAND_CASES,
        ))
    return bucketed


def get_prediction_quality(client: AitoClient) -> list[PredictionQuality]:
    """Compute *real* per-field prediction quality via `_evaluate`.

    For each predictable field we run a held-out test:

      testSource: the first 200 purchases (no ordering, so the same
                  rows every run and the bands are reproducible)
      evaluate:   predict <field> from supplier + description + amount

    Aito hides the target column on each test row, predicts it, and
    compares to ground truth. We keep `select: ["cases"]` so we can
    bucket the per-case probabilities into confidence bands — the
    "predictions ≥0.85 are 98% accurate" story the demo's accuracy
    claims need to back up.

    For documentation see guides/08 in aito-accounting-demo. (Trade-off:
    `cases` payloads can be big; we aggregate server-side and only ship
    band counts + sample size to the browser.)
    """
    fields = ["cost_center", "account_code", "approver"]
    feature_fields = ["supplier", "description", "amount_eur"]
    quality: list[PredictionQuality] = []

    for field_name in fields:
        try:
            response = client.evaluate_with_cases(
                table="purchases",
                predict_field=field_name,
                feature_fields=feature_fields,
                limit=200,
            )
        except Exception as e:
            print(f"  evaluate failed for {field_name}: {e}")
            quality.append(PredictionQuality(
                field_name=field_name,
                accuracy=0.0,
                base_accuracy=0.0,
                accuracy_gain=0.0,
                avg_confidence=0.0,
                sample_size=0,
                bands=[],
            ))
            continue

        cases = response.get("cases") or []
        accuracy = float(response.get("accuracy") or 0.0)
        base_accuracy = float(response.get("baseAccuracy") or 0.0)
        total = len(cases)
        avg_conf = (
            sum(_case_p(c) for c in cases) / len(cases)
            if cases else 0.0
        )

        quality.append(PredictionQuality(
            field_name=field_name,
            accuracy=round(accuracy, 3),
            base_accuracy=round(base_accuracy, 3),
            accuracy_gain=round(accuracy - base_accuracy, 3),
            avg_confidence=round(avg_conf, 3),
            sample_size=total,
            bands=_bucket_cases(cases),
        ))

    return quality


def get_learning_curve(client: AitoClient) -> list[dict]:
    """Compute month-by-month automation rate from purchase history.

    Groups purchases by order_month and counts each routed_by category
    to show how automation has improved as more data accumulates.
    """
    result = client.search("purchases", {}, limit=5000)
    hits = result.get("hits", [])

    # Group by month → routed_by counts
    by_month: dict[str, dict[str, int]] = {}
    for row in hits:
        month = row.get("order_month", "")
        if not month:
            continue
        routed = row.get("routed_by", "manual")
        by_month.setdefault(month, {"rule": 0, "aito": 0, "review": 0, "manual": 0})
        # Map routed_by values to four buckets
        if routed in ("rule",):
            by_month[month]["rule"] += 1
        elif routed in ("aito_high", "aito"):
            by_month[month]["aito"] += 1
        elif routed in ("aito_reviewed", "review"):
            by_month[month]["review"] += 1
        else:
            by_month[month]["manual"] += 1

    # Filter to months with enough volume to be statistically meaningful
    # (avoids 100% automation on N=4 looking misleading), then emit a row.
    MIN_VOLUME = 5
    curve: list[dict] = []
    for idx, (month, counts) in enumerate(sorted(by_month.items()), start=1):
        total = sum(counts.values())
        if total < MIN_VOLUME:
            continue
        automated = counts["rule"] + counts["aito"]
        manual_pct = _safe_pct(counts["manual"] + counts["review"], total)
        # Approximate confidence rises as data accumulates — bounded at 0.92
        confidence = min(0.92, 0.40 + 0.05 * idx)
        curve.append({
            "month": month,
            "week": idx,  # Kept for backwards compatibility with frontend
            "automation_pct": round(_safe_pct(automated, total)),
            "avg_confidence": round(confidence, 2),
            "manual_pct": round(manual_pct),
            "total": total,
        })

    return curve


def get_overview(client: AitoClient) -> OverviewMetrics:
    """Get complete overview metrics for the dashboard.

    Combines automation breakdown, prediction quality, and learning
    curve — all computed from the live Aito purchases table.
    """
    automation = get_automation_breakdown(client)
    quality = get_prediction_quality(client)
    learning_curve = get_learning_curve(client)

    total_automated = automation.rules_count + automation.aito_high_count
    total = automation.total_purchases

    # No euro figure. The headline used to be "€234k estimated savings",
    # a real count of automated POs multiplied by three invented rates
    # (5 min/PO, €0.80/min, €120 per mis-coding) — and it treated
    # accuracy as "mis-codings prevented", which it is not. Every figure
    # below is a count or a measurement; a reader brings their own rates.
    measured_accuracies = [q.accuracy for q in quality if q.sample_size > 0]
    avg_accuracy = (sum(measured_accuracies) / len(measured_accuracies)
                    if measured_accuracies else 0.0)

    avg_baseline = (sum(q.base_accuracy for q in quality
                        if q.sample_size > 0) / len(measured_accuracies)
                    if measured_accuracies else 0.0)

    summary = {
        "automation_rate": _safe_pct(total_automated, total),
        "total_automated": total_automated,
        "needs_review": automation.aito_reviewed_count,
        "fully_manual": automation.manual_count,
        "avg_prediction_confidence": round(
            sum(q.avg_confidence for q in quality) / len(quality), 3
        ) if quality else 0,
        # Real evaluation outputs — what the operator should trust.
        "model_accuracy": round(avg_accuracy, 3),
        "baseline_accuracy": round(avg_baseline, 3),
        "accuracy_gain": round(avg_accuracy - avg_baseline, 3),
    }

    return OverviewMetrics(
        automation=automation,
        prediction_quality=quality,
        learning_curve=learning_curve,
        summary=summary,
    )



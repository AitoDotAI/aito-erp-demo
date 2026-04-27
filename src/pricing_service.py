"""Price estimation — historical price analysis and quote scoring.

Searches the price_history table for comparable transactions, computes
statistical estimates, and scores incoming vendor quotes against
the expected price range. Flags quotes that exceed the estimate by
more than 20%.
"""

import math
from dataclasses import dataclass, field

from src.aito_client import AitoClient


QUOTE_FLAG_THRESHOLD = 0.20  # Flag quotes >20% above estimate


@dataclass
class PriceEstimate:
    product_id: str
    supplier: str | None
    volume: int | None
    estimated_price: float
    price_min: float
    price_max: float
    range_low: float
    range_high: float
    sample_size: int
    confidence: float  # Based on sample size
    std_dev: float

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "supplier": self.supplier,
            "volume": self.volume,
            "estimated_price": self.estimated_price,
            "price_min": self.price_min,
            "price_max": self.price_max,
            "range_low": self.range_low,
            "range_high": self.range_high,
            "sample_size": self.sample_size,
            "confidence": self.confidence,
            "std_dev": self.std_dev,
        }


@dataclass
class QuoteScore:
    supplier: str
    quoted_price: float
    estimated_price: float
    deviation_pct: float
    flagged: bool
    verdict: str  # "good" | "acceptable" | "overpriced"

    def to_dict(self) -> dict:
        return {
            "supplier": self.supplier,
            "quoted_price": self.quoted_price,
            "estimated_price": self.estimated_price,
            "deviation_pct": self.deviation_pct,
            "flagged": self.flagged,
            "verdict": self.verdict,
        }


def _compute_confidence(sample_size: int) -> float:
    """Compute confidence score based on sample size.

    More data points = higher confidence, with diminishing returns.
    """
    if sample_size == 0:
        return 0.0
    if sample_size >= 20:
        return 0.95
    if sample_size >= 10:
        return 0.85
    if sample_size >= 5:
        return 0.70
    return 0.40 + (sample_size * 0.06)


def estimate_price(
    client: AitoClient,
    product_id: str,
    supplier: str | None = None,
    volume: int | None = None,
) -> PriceEstimate:
    """Estimate price for a product based on historical price data.

    Searches price_history for matching records, computes statistics,
    and returns an estimate with a confidence range (mean +/- 1.5 std).

    Args:
        client: Aito API client.
        product_id: Product SKU to estimate price for.
        supplier: Optional supplier filter.
        volume: Optional volume filter (not used as exact match).

    Returns:
        PriceEstimate with mean, range, and confidence.
    """
    where: dict = {"product_id": product_id}
    if supplier:
        where["supplier"] = supplier

    result = client.search("price_history", where, limit=100)
    hits = result.get("hits", [])

    prices = [h.get("unit_price", 0) for h in hits if h.get("unit_price")]

    if not prices:
        return PriceEstimate(
            product_id=product_id,
            supplier=supplier,
            volume=volume,
            estimated_price=0.0,
            price_min=0.0,
            price_max=0.0,
            range_low=0.0,
            range_high=0.0,
            sample_size=0,
            confidence=0.0,
            std_dev=0.0,
        )

    mean = sum(prices) / len(prices)
    variance = sum((p - mean) ** 2 for p in prices) / len(prices) if len(prices) > 1 else 0
    std = math.sqrt(variance)

    range_low = max(0, mean - 1.5 * std)
    range_high = mean + 1.5 * std

    return PriceEstimate(
        product_id=product_id,
        supplier=supplier,
        volume=volume,
        estimated_price=round(mean, 2),
        price_min=round(min(prices), 2),
        price_max=round(max(prices), 2),
        range_low=round(range_low, 2),
        range_high=round(range_high, 2),
        sample_size=len(prices),
        confidence=_compute_confidence(len(prices)),
        std_dev=round(std, 2),
    )


def score_quotes(
    estimate: PriceEstimate,
    quotes: list[dict],
) -> list[QuoteScore]:
    """Compare incoming quotes against the price estimate.

    Flags quotes that exceed the estimated price by more than 20%.

    Args:
        estimate: Price estimate from estimate_price().
        quotes: List of dicts with keys: supplier, quoted_price.

    Returns:
        List of QuoteScore sorted by deviation (best first).
    """
    scores = []
    for quote in quotes:
        quoted = quote["quoted_price"]
        if estimate.estimated_price > 0:
            deviation = (quoted - estimate.estimated_price) / estimate.estimated_price
        else:
            deviation = 0.0

        flagged = deviation > QUOTE_FLAG_THRESHOLD

        if deviation <= 0:
            verdict = "good"
        elif deviation <= QUOTE_FLAG_THRESHOLD:
            verdict = "acceptable"
        else:
            verdict = "overpriced"

        scores.append(QuoteScore(
            supplier=quote["supplier"],
            quoted_price=quoted,
            estimated_price=estimate.estimated_price,
            deviation_pct=round(deviation * 100, 1),
            flagged=flagged,
            verdict=verdict,
        ))

    scores.sort(key=lambda s: s.deviation_pct)
    return scores


# Demo products matching the HTML mock
DEMO_PRODUCTS = {
    "seal": {"product_id": "SKU-4421", "name": "Wärtsilä Seal Kit WS-442", "supplier": "Wärtsilä Components"},
    "fuel": {"product_id": "SKU-FUEL", "name": "Neste Fleet Fuel (per 100L)", "supplier": "Neste Oyj"},
    "hvac": {"product_id": "SKU-HVAC", "name": "Caverion HVAC Service (hr)", "supplier": "Caverion Suomi"},
    "workwear": {"product_id": "SKU-2234", "name": "Lindström Workwear Set M", "supplier": "Lindström Oy"},
}

DEMO_QUOTES = {
    "seal": [
        {"supplier": "Wärtsilä", "quoted_price": 142},
        {"supplier": "Parts Direct", "quoted_price": 189},
        {"supplier": "Nordic Supply", "quoted_price": 151},
    ],
    "fuel": [
        {"supplier": "Neste", "quoted_price": 91},
        {"supplier": "Shell Finland", "quoted_price": 98},
        {"supplier": "ABC Energy", "quoted_price": 118},
    ],
    "hvac": [
        {"supplier": "Caverion", "quoted_price": 78},
        {"supplier": "YIT Service", "quoted_price": 85},
        {"supplier": "Granlund", "quoted_price": 112},
    ],
    "workwear": [
        {"supplier": "Lindström", "quoted_price": 84},
        {"supplier": "Alsico", "quoted_price": 92},
        {"supplier": "Engel", "quoted_price": 108},
    ],
}


def get_pricing_overview(client: AitoClient) -> dict:
    """Get price estimates, quote scores, and PPV (Purchase Price Variance)
    metrics for all demo products."""
    products = {}
    total_quotes = 0
    flagged_quotes = 0
    total_overpayment = 0.0  # Sum of deviations on flagged quotes
    total_savings = 0.0       # Sum of deviations on accepted quotes (negative = savings)
    ppv_per_product: dict[str, float] = {}

    for key, info in DEMO_PRODUCTS.items():
        estimate = estimate_price(client, info["product_id"], info["supplier"])
        quotes = score_quotes(estimate, DEMO_QUOTES.get(key, []))

        # PPV per product = (avg actual price - estimate) / estimate
        if quotes:
            avg_quoted = sum(q.quoted_price for q in quotes) / len(quotes)
            ppv = ((avg_quoted - estimate.estimated_price) / estimate.estimated_price * 100
                   if estimate.estimated_price > 0 else 0)
            ppv_per_product[info["product_id"]] = round(ppv, 2)

        for q in quotes:
            total_quotes += 1
            deviation_eur = q.quoted_price - q.estimated_price
            if q.flagged:
                flagged_quotes += 1
                total_overpayment += deviation_eur
            elif deviation_eur < 0:
                total_savings += abs(deviation_eur)

        products[key] = {
            "product_id": info["product_id"],
            "name": info["name"],
            "supplier": info["supplier"],
            "estimate": estimate.to_dict(),
            "quotes": [q.to_dict() for q in quotes],
        }

    # Aggregate PPV — weighted average across products
    overall_ppv = (sum(ppv_per_product.values()) / len(ppv_per_product)
                   if ppv_per_product else 0)

    return {
        "products": products,
        "ppv": {
            "overall_pct": round(overall_ppv, 2),
            "by_product": ppv_per_product,
            "flagged_quotes": flagged_quotes,
            "total_quotes": total_quotes,
            "total_overpayment_eur": round(total_overpayment, 2),
            "total_savings_eur": round(total_savings, 2),
            # Annualized: assume 10 orders/year per flagged item
            "annualized_overpayment_eur": round(total_overpayment * 10, 2),
        },
    }

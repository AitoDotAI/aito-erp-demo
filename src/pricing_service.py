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


# Per-tenant hero products. Each set picks 4 SKUs from that tenant's
# real `products` table that have meaningful price_history coverage,
# so `estimate_price()` returns non-zero estimates and the quote-
# scoring narrative actually works. Picked by querying each tenant's
# `price_history` for SKUs with the most rows + cross-checking
# `orders` for demand coverage. See `.ai/issues/01-...md`.
DEMO_PRODUCTS_BY_TENANT: dict[str, dict[str, dict]] = {
    "metsa": {
        "fuel": {"product_id": "SKU-1027", "name": "AdBlue v2 (10L)", "supplier": "Lyreco"},
        "engine_oil": {"product_id": "SKU-1271", "name": "Engine Oil v2 (5L)", "supplier": "Neste Oyj"},
        "calibration": {"product_id": "SKU-1213", "name": "Equipment Calibration #231", "supplier": "Lyreco"},
        "inspection": {"product_id": "SKU-1038", "name": "Electrical Inspection (hr)", "supplier": "Siemens Finland"},
    },
    "aurora": {
        "yogurt": {"product_id": "SKU-1231", "name": "Yogurt 4-pack", "supplier": "Valio Oy"},
        "cleaner": {"product_id": "SKU-1122", "name": "Multi-Surface Cleaner 10pk", "supplier": "Berner Beauty"},
        "paint": {"product_id": "SKU-1267", "name": "Paint Roller (refill set)", "supplier": "Bauhaus"},
        "body_lotion": {"product_id": "SKU-1289", "name": "Body Lotion 250ml", "supplier": "L'Oréal Finland"},
    },
    "studio": {
        "adobe": {"product_id": "SKU-1087", "name": "Adobe CC Seat (monthly)", "supplier": "Adobe Systems"},
        "tea": {"product_id": "SKU-1029", "name": "Tea Bags (office pack)", "supplier": "Kespro"},
        "markers": {"product_id": "SKU-1113", "name": "Whiteboard Markers (set of 12)", "supplier": "Lyreco"},
        "pens": {"product_id": "SKU-1134", "name": "Pens Pack Pro (50pk)", "supplier": "Lyreco"},
    },
}


def demo_products_for(tenant: str | None) -> dict[str, dict]:
    return DEMO_PRODUCTS_BY_TENANT.get(tenant or "metsa",
                                        DEMO_PRODUCTS_BY_TENANT["metsa"])


# Mocked competing-supplier quote sets per (tenant, product key).
# These are the rows the Pricing view scores against the Aito-derived
# fair-price estimate. Suppliers chosen to feel realistic for each
# vertical without claiming they correspond to real quotes.
DEMO_QUOTES_BY_TENANT: dict[str, dict[str, list[dict]]] = {
    "metsa": {
        "fuel": [
            {"supplier": "Lyreco", "quoted_price": 88},
            {"supplier": "Neste Oyj", "quoted_price": 94},
            {"supplier": "Shell Finland", "quoted_price": 112},
        ],
        "engine_oil": [
            {"supplier": "Neste Oyj", "quoted_price": 162},
            {"supplier": "Shell Finland", "quoted_price": 175},
            {"supplier": "ABC Energy", "quoted_price": 219},
        ],
        "calibration": [
            {"supplier": "Lyreco", "quoted_price": 108},
            {"supplier": "Caverion Suomi", "quoted_price": 122},
            {"supplier": "YIT Service", "quoted_price": 145},
        ],
        "inspection": [
            {"supplier": "Siemens Finland", "quoted_price": 119},
            {"supplier": "ABB Finland", "quoted_price": 128},
            {"supplier": "Caverion Suomi", "quoted_price": 156},
        ],
    },
    "aurora": {
        "yogurt": [
            {"supplier": "Valio Oy", "quoted_price": 24},
            {"supplier": "Atria Oyj", "quoted_price": 26},
            {"supplier": "Arla Foods", "quoted_price": 31},
        ],
        "cleaner": [
            {"supplier": "Berner Beauty", "quoted_price": 92},
            {"supplier": "Lyreco", "quoted_price": 98},
            {"supplier": "Tikkurila", "quoted_price": 124},
        ],
        "paint": [
            {"supplier": "Bauhaus", "quoted_price": 138},
            {"supplier": "Tikkurila", "quoted_price": 149},
            {"supplier": "K-Rauta", "quoted_price": 178},
        ],
        "body_lotion": [
            {"supplier": "L'Oréal Finland", "quoted_price": 7},
            {"supplier": "Berner Beauty", "quoted_price": 9},
            {"supplier": "Cocoon Imports", "quoted_price": 14},
        ],
    },
    "studio": {
        "adobe": [
            {"supplier": "Adobe Systems", "quoted_price": 16},
            {"supplier": "Insight Enterprises", "quoted_price": 18},
            {"supplier": "Atea Finland", "quoted_price": 22},
        ],
        "tea": [
            {"supplier": "Kespro", "quoted_price": 42},
            {"supplier": "Paulig Group", "quoted_price": 46},
            {"supplier": "Fazer Food Services", "quoted_price": 58},
        ],
        "markers": [
            {"supplier": "Lyreco", "quoted_price": 64},
            {"supplier": "Staples Oy", "quoted_price": 71},
            {"supplier": "Wulff Supplies", "quoted_price": 89},
        ],
        "pens": [
            {"supplier": "Lyreco", "quoted_price": 5},
            {"supplier": "Staples Oy", "quoted_price": 6},
            {"supplier": "Wulff Supplies", "quoted_price": 9},
        ],
    },
}


def demo_quotes_for(tenant: str | None) -> dict[str, list[dict]]:
    return DEMO_QUOTES_BY_TENANT.get(tenant or "metsa",
                                      DEMO_QUOTES_BY_TENANT["metsa"])


# Backward-compat aliases (single-tenant callers + tests).
DEMO_PRODUCTS = DEMO_PRODUCTS_BY_TENANT["metsa"]
DEMO_QUOTES = DEMO_QUOTES_BY_TENANT["metsa"]


def get_pricing_overview(client: AitoClient, tenant: str | None = None) -> dict:
    """Get price estimates, quote scores, and PPV (Purchase Price Variance)
    metrics for all demo products in this tenant's hero set."""
    products = {}
    total_quotes = 0
    flagged_quotes = 0
    total_overpayment = 0.0  # Sum of deviations on flagged quotes
    total_savings = 0.0       # Sum of deviations on accepted quotes (negative = savings)
    ppv_per_product: dict[str, float] = {}

    tenant_products = demo_products_for(tenant)
    tenant_quotes = demo_quotes_for(tenant)

    for key, info in tenant_products.items():
        # Estimate against the full price-history (all suppliers) — gives
        # the "market fair price" band rather than one supplier's history.
        # The product's primary supplier is shown on the card for context
        # but isn't used as a filter.
        estimate = estimate_price(client, info["product_id"])
        quotes = score_quotes(estimate, tenant_quotes.get(key, []))

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

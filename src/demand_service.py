"""Demand forecasting — predict future order volumes from history.

Searches the orders table for historical sales data, computes a
baseline average, and uses Aito's _predict to estimate future demand.
Provides trend direction and confidence for inventory planning.
"""

from dataclasses import dataclass

from src.aito_client import AitoClient


@dataclass
class DemandForecast:
    product_id: str
    product_name: str
    month: str
    baseline: float  # Average monthly demand
    forecast: float  # Predicted demand
    trend: str  # "up" | "down" | "stable"
    confidence: float
    history: list[dict]  # Recent monthly volumes

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "month": self.month,
            "baseline": self.baseline,
            "forecast": self.forecast,
            "trend": self.trend,
            "confidence": self.confidence,
            "history": self.history,
        }


def _compute_trend(history_values: list[float]) -> str:
    """Determine trend from recent history.

    Compares the average of the last 3 months to the previous 3 months.
    """
    if len(history_values) < 4:
        return "stable"

    recent = history_values[-3:]
    earlier = history_values[-6:-3] if len(history_values) >= 6 else history_values[:-3]

    if not earlier:
        return "stable"

    recent_avg = sum(recent) / len(recent)
    earlier_avg = sum(earlier) / len(earlier)

    if earlier_avg == 0:
        return "stable"

    change = (recent_avg - earlier_avg) / earlier_avg
    if change > 0.10:
        return "up"
    elif change < -0.10:
        return "down"
    else:
        return "stable"


def forecast_demand(
    client: AitoClient,
    product_id: str,
    month: str,
) -> DemandForecast:
    """Forecast demand for a product in a given month.

    1. Search orders for this product's history.
    2. Compute baseline (average monthly volume).
    3. Try _predict on orders table for units_sold.
    4. Return forecast with trend and confidence.

    Args:
        client: Aito API client.
        product_id: Product SKU.
        month: Target month (e.g. "2025-06").

    Returns:
        DemandForecast with baseline, forecast, and trend.
    """
    # Get historical orders
    result = client.search("orders", {"product_id": product_id}, limit=200)
    hits = result.get("hits", [])

    # Build monthly history
    monthly: dict[str, int] = {}
    for order in hits:
        m = order.get("month", "")
        units = order.get("units_sold", 0)
        monthly[m] = monthly.get(m, 0) + units

    history = [{"month": m, "units": u} for m, u in sorted(monthly.items())]
    history_values = [h["units"] for h in history]

    baseline = sum(history_values) / len(history_values) if history_values else 0
    trend = _compute_trend(history_values)

    # Seasonality: average historical demand for the same calendar month.
    # This captures yearly patterns — workwear August spike, fuel July dip,
    # maintenance March/September peaks — directly from the data.
    target_month_suffix = month.split("-")[1] if "-" in month else ""
    seasonal_values = [
        h["units"] for h in history
        if h["month"].split("-")[1] == target_month_suffix
    ]
    seasonal_avg = sum(seasonal_values) / len(seasonal_values) if seasonal_values else baseline

    # Compute a seasonality factor and apply to baseline
    seasonal_lift = (seasonal_avg / baseline) if baseline > 0 else 1.0
    forecast_value = baseline * seasonal_lift

    # Confidence based on sample size — more historical data points = higher confidence
    sample_size = len(seasonal_values)
    if sample_size >= 3:
        confidence = 0.85
    elif sample_size >= 2:
        confidence = 0.70
    elif sample_size >= 1:
        confidence = 0.55
    else:
        confidence = 0.40
        forecast_value = baseline

    # Try Aito _predict for explanation factors and to validate the seasonal estimate
    try:
        pred_result = client.predict(
            "orders",
            {"product_id": product_id, "month": month},
            "units_sold",
        )
        pred_hits = pred_result.get("hits", [])
        if pred_hits and pred_hits[0].get("$p", 0.0) > 0.30:
            top = pred_hits[0]
            predicted = top.get("feature", 0)
            if isinstance(predicted, (int, float)) and predicted > 0:
                # Blend Aito prediction with seasonal estimate
                aito_conf = top.get("$p", 0.0)
                forecast_value = 0.5 * forecast_value + 0.5 * float(predicted)
                confidence = max(confidence, aito_conf)
    except Exception:
        pass

    # Recompute trend based on whether forecast is up/down from baseline
    if baseline > 0:
        change_pct = (forecast_value - baseline) / baseline
        if change_pct > 0.10:
            trend = "up"
        elif change_pct < -0.10:
            trend = "down"
        else:
            trend = "stable"

    product_name = DEMO_PRODUCTS.get(product_id, {}).get("name", product_id)

    return DemandForecast(
        product_id=product_id,
        product_name=product_name,
        month=month,
        baseline=round(baseline, 1),
        forecast=round(forecast_value, 1),
        trend=trend,
        confidence=round(confidence, 3),
        history=history,
    )


# Demo products matching the HTML mock
DEMO_PRODUCTS = {
    "SKU-4421": {"name": "Wärtsilä Seal Kit WS-442", "monthly_avg": 8},
    "SKU-FUEL": {"name": "Neste Fleet Fuel (100L)", "monthly_avg": 42},
    "SKU-2234": {"name": "Lindström Workwear Set M", "monthly_avg": 6},
    "SKU-HVAC": {"name": "Caverion HVAC Service (hr)", "monthly_avg": 24},
    "SKU-5560": {"name": "Fazer Vending Refill Pack", "monthly_avg": 18},
    "SKU-9901": {"name": "Generic Cable Gland M20", "monthly_avg": 180},
}

DEMO_FORECAST_SKUS = list(DEMO_PRODUCTS.keys())


def get_demand_forecast(client: AitoClient, month: str = "2025-06") -> dict:
    """Get demand forecasts for all demo products plus aggregate impact metrics."""
    forecasts = []
    spike_count = 0
    drop_count = 0
    high_conf_count = 0
    significant_change_pct_sum = 0.0
    significant_change_count = 0

    for sku in DEMO_FORECAST_SKUS:
        fc = forecast_demand(client, sku, month)
        forecasts.append(fc.to_dict())
        if fc.trend == "up":
            spike_count += 1
        elif fc.trend == "down":
            drop_count += 1
        if fc.confidence >= 0.70:
            high_conf_count += 1
        if fc.baseline > 0:
            change_pct = abs((fc.forecast - fc.baseline) / fc.baseline)
            if change_pct >= 0.10:
                significant_change_pct_sum += change_pct
                significant_change_count += 1

    # Impact estimates: each correctly-predicted spike prevents one stockout
    # event (€800 avg cost: lost margin + expedite shipping). Each correctly-
    # predicted drop prevents excess ordering (€400 avg carrying cost).
    stockouts_prevented_eur = spike_count * 800
    excess_prevented_eur = drop_count * 400

    return {
        "forecasts": forecasts,
        "month": month,
        "impact": {
            "spikes_predicted": spike_count,
            "drops_predicted": drop_count,
            "high_confidence_count": high_conf_count,
            "stockouts_prevented_eur": stockouts_prevented_eur,
            "excess_prevented_eur": excess_prevented_eur,
            "total_impact_eur": stockouts_prevented_eur + excess_prevented_eur,
        },
    }

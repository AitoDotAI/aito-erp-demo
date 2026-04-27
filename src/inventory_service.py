"""Inventory intelligence — combines demand forecasts with stock data.

Computes days-of-supply for each product, flags critical items where
stock may run out before the next delivery, and suggests substitutions
for at-risk SKUs. Also identifies overstock situations.
"""

from dataclasses import dataclass, field

from src.aito_client import AitoClient
from src.demand_service import forecast_demand, DEMO_PRODUCTS


# Current stock levels (units on hand) — matches HTML mock
STOCK_LEVELS = {
    "SKU-4421": 4,       # Wärtsilä Seal Kit — 15 days supply, 14-day lead time → 1-day margin
    "SKU-FUEL": 980,     # Neste Fleet Fuel — 773 days supply → overstock
    "SKU-2234": 3,       # Lindström Workwear — 9 days supply, 14-day lead time → overdue
    "SKU-HVAC": 80,      # Caverion HVAC — 109 days supply → OK
    "SKU-5560": 28,      # Fazer Vending — 40 days supply → reorder soon
    "SKU-9901": 90,      # Cable Gland — 20 days supply, 21-day lead time → critical
}

# Supplier lead times in days
LEAD_TIMES = {
    "SKU-4421": 14,
    "SKU-FUEL": 3,
    "SKU-2234": 14,
    "SKU-HVAC": 7,
    "SKU-5560": 3,
    "SKU-9901": 21,
}

# Reorder points (units)
REORDER_POINTS = {
    "SKU-4421": 12,
    "SKU-FUEL": 80,
    "SKU-2234": 10,
    "SKU-HVAC": 30,
    "SKU-5560": 20,
    "SKU-9901": 200,
}

# Substitution suggestions — matches HTML mock
SUBSTITUTIONS = {
    "SKU-4421": [
        {"product_id": "SKU-4420", "name": "Seal Kit WS-440", "similarity": 0.84},
    ],
    "SKU-2234": [
        {"product_id": "SKU-2235", "name": "Workwear Set L (alt)", "similarity": 0.71},
    ],
    "SKU-9901": [
        {"product_id": "SKU-9902", "name": "Cable Gland M20 (alt brand)", "similarity": 0.91},
    ],
}

OVERSTOCK_MONTHS = 3


@dataclass
class InventoryItem:
    product_id: str
    product_name: str
    stock_on_hand: int
    daily_demand: float
    days_of_supply: float
    lead_time_days: int
    reorder_point: int
    status: str  # "critical" | "low" | "ok" | "overstock"
    forecast_units: float
    unit_price: float = 0.0
    excess_units: int = 0       # Units above 60-day target (overstock)
    tied_capital_eur: float = 0.0  # excess_units * unit_price
    stockout_risk_eur: float = 0.0  # potential lost margin if critical
    substitutions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "stock_on_hand": self.stock_on_hand,
            "daily_demand": self.daily_demand,
            "days_of_supply": self.days_of_supply,
            "lead_time_days": self.lead_time_days,
            "reorder_point": self.reorder_point,
            "status": self.status,
            "forecast_units": self.forecast_units,
            "unit_price": self.unit_price,
            "excess_units": self.excess_units,
            "tied_capital_eur": self.tied_capital_eur,
            "stockout_risk_eur": self.stockout_risk_eur,
            "substitutions": self.substitutions,
        }


@dataclass
class InventoryOverview:
    items: list[InventoryItem]
    critical_count: int
    low_count: int
    overstock_count: int
    ok_count: int
    total_tied_capital_eur: float = 0.0
    total_stockout_risk_eur: float = 0.0
    target_freed_eur: float = 0.0  # If overstock reduced to 60-day target

    def to_dict(self) -> dict:
        return {
            "items": [i.to_dict() for i in self.items],
            "critical_count": self.critical_count,
            "low_count": self.low_count,
            "overstock_count": self.overstock_count,
            "ok_count": self.ok_count,
            "total_tied_capital_eur": self.total_tied_capital_eur,
            "total_stockout_risk_eur": self.total_stockout_risk_eur,
            "target_freed_eur": self.target_freed_eur,
        }


def _classify_status(days_of_supply: float, lead_time: int) -> str:
    """Classify inventory status based on days of supply vs lead time.

    Critical: stock will run out before the supplier can deliver, even with
    a small buffer. This is a stockout risk — action required today.

    Low: stock survives the lead time but with no comfortable buffer.
    Reorder soon, not urgent.

    Overstock: more than OVERSTOCK_MONTHS of supply on hand.

    OK: comfortable buffer above lead time.
    """
    # 7-day safety buffer above lead time
    SAFETY_BUFFER_DAYS = 7
    critical_threshold = lead_time + SAFETY_BUFFER_DAYS
    low_threshold = lead_time * 2 + SAFETY_BUFFER_DAYS

    if days_of_supply < critical_threshold:
        return "critical"
    elif days_of_supply < low_threshold:
        return "low"
    elif days_of_supply > OVERSTOCK_MONTHS * 30:
        return "overstock"
    else:
        return "ok"


def get_inventory_status(client: AitoClient, target_month: str = "2025-06") -> InventoryOverview:
    """Compute inventory status for all demo products.

    For each product:
    1. Get demand forecast from demand_service.
    2. Compute daily demand = forecast / 30.
    3. Compute days_of_supply = stock / daily_demand.
    4. Flag critical if days_of_supply < lead_time.

    Args:
        client: Aito API client.
        target_month: Month to forecast demand for.

    Returns:
        InventoryOverview with per-item status and summary counts.
    """
    # Per-product unit prices for capital calculations.
    # In a real ERP these come from products table; we use known
    # prices to ensure the numbers tell the right story.
    UNIT_PRICES = {
        "SKU-4421": 148.00, "SKU-FUEL": 94.00, "SKU-2234": 89.00,
        "SKU-HVAC": 82.00, "SKU-5560": 25.00, "SKU-9901": 3.40,
    }
    # Target buffer for overstock calculation: 60 days
    TARGET_BUFFER_DAYS = 60

    items: list[InventoryItem] = []

    for product_id, product_info in DEMO_PRODUCTS.items():
        stock = STOCK_LEVELS.get(product_id, 0)
        lead_time = LEAD_TIMES.get(product_id, 14)
        reorder = REORDER_POINTS.get(product_id, 0)
        unit_price = UNIT_PRICES.get(product_id, 0.0)

        # Get demand forecast
        demand = forecast_demand(client, product_id, target_month)
        monthly_forecast = demand.forecast if demand.forecast > 0 else demand.baseline
        daily_demand = monthly_forecast / 30.0

        if daily_demand > 0:
            days_of_supply = round(stock / daily_demand, 1)
        else:
            days_of_supply = 999.0  # No demand = effectively infinite supply

        status = _classify_status(days_of_supply, lead_time)
        subs = SUBSTITUTIONS.get(product_id, []) if status in ("critical", "low") else []

        # Cash impact calculations
        excess_units = 0
        tied_capital = 0.0
        stockout_risk = 0.0
        if status == "overstock" and daily_demand > 0:
            target_stock = daily_demand * TARGET_BUFFER_DAYS
            excess_units = max(0, int(stock - target_stock))
            tied_capital = round(excess_units * unit_price, 2)
        elif status == "critical":
            # Estimate one-week's worth of lost margin if stockout occurs
            stockout_risk = round(daily_demand * 7 * unit_price, 2)

        items.append(InventoryItem(
            product_id=product_id,
            product_name=product_info["name"],
            stock_on_hand=stock,
            daily_demand=round(daily_demand, 1),
            days_of_supply=days_of_supply,
            lead_time_days=lead_time,
            reorder_point=reorder,
            status=status,
            forecast_units=round(monthly_forecast, 1),
            unit_price=unit_price,
            excess_units=excess_units,
            tied_capital_eur=tied_capital,
            stockout_risk_eur=stockout_risk,
            substitutions=subs,
        ))

    # Sort: critical first, then low, then ok, then overstock
    status_order = {"critical": 0, "low": 1, "ok": 2, "overstock": 3}
    items.sort(key=lambda i: status_order.get(i.status, 2))

    total_tied = sum(i.tied_capital_eur for i in items)
    total_risk = sum(i.stockout_risk_eur for i in items)

    return InventoryOverview(
        items=items,
        critical_count=sum(1 for i in items if i.status == "critical"),
        low_count=sum(1 for i in items if i.status == "low"),
        overstock_count=sum(1 for i in items if i.status == "overstock"),
        ok_count=sum(1 for i in items if i.status == "ok"),
        total_tied_capital_eur=round(total_tied, 2),
        total_stockout_risk_eur=round(total_risk, 2),
        target_freed_eur=round(total_tied, 2),
    )


def get_overstock_analysis(client: AitoClient, target_month: str = "2025-06") -> list[dict]:
    """Identify overstocked items and estimate excess value.

    Returns items where days_of_supply exceeds the overstock threshold.
    """
    overview = get_inventory_status(client, target_month)
    overstock = []
    for item in overview.items:
        if item.status == "overstock":
            excess_days = item.days_of_supply - (OVERSTOCK_MONTHS * 30)
            excess_units = round(excess_days * item.daily_demand)
            overstock.append({
                "product_id": item.product_id,
                "product_name": item.product_name,
                "stock_on_hand": item.stock_on_hand,
                "days_of_supply": item.days_of_supply,
                "excess_units": excess_units,
                "recommendation": "Reduce order quantity or negotiate consignment",
            })
    return overstock

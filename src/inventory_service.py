"""Inventory intelligence — combines demand forecasts with stock data.

Computes days-of-supply for each product, flags critical items where
stock may run out before the next delivery, and suggests substitutions
for at-risk SKUs. Also identifies overstock situations.
"""

from dataclasses import dataclass, field

from src.aito_client import AitoClient
from src.demand_service import forecast_demand, demo_products_for


# Per-tenant inventory state. Stock levels, lead times, reorder
# points, unit prices, and substitution suggestions are tunable mocks
# that combine with `demand_service.demo_products_for(tenant)` to
# produce one critical / one overstock / one OK / one low row per
# tenant — the canonical "Inventory Intelligence" story shape.
INVENTORY_BY_TENANT: dict[str, dict[str, dict]] = {
    "metsa": {
        # SKU-1027 AdBlue v2 — fast-moving, 14-day lead, hovering low
        "SKU-1027": {"stock": 18, "lead_time": 14, "reorder_point": 30, "unit_price": 88.97,
                      "substitutions": [{"product_id": "SKU-1028", "name": "AdBlue v3 (10L)", "similarity": 0.92}]},
        # SKU-1271 Engine Oil v2 — Neste, healthy buffer
        "SKU-1271": {"stock": 60, "lead_time": 7, "reorder_point": 25, "unit_price": 163.92,
                      "substitutions": []},
        # SKU-1213 Equipment Calibration — service item, lumpy demand → critical
        "SKU-1213": {"stock": 2, "lead_time": 21, "reorder_point": 6, "unit_price": 111.10,
                      "substitutions": [{"product_id": "SKU-1214", "name": "Equipment Calibration #240", "similarity": 0.78}]},
        # SKU-1038 Electrical Inspection — overstocked from a bulk procurement run
        "SKU-1038": {"stock": 240, "lead_time": 14, "reorder_point": 30, "unit_price": 120.09,
                      "substitutions": []},
    },
    "aurora": {
        # SKU-1231 Yogurt — perishable, fast-moving, low margin → critical
        "SKU-1231": {"stock": 80, "lead_time": 3, "reorder_point": 200, "unit_price": 24.98,
                      "substitutions": [{"product_id": "SKU-1232", "name": "Yogurt 6-pack", "similarity": 0.88}]},
        # SKU-1122 Multi-Surface Cleaner — household consumable
        "SKU-1122": {"stock": 140, "lead_time": 7, "reorder_point": 80, "unit_price": 93.70,
                      "substitutions": []},
        # SKU-1267 Paint Roller — DIY seasonal spike, low stock → low/critical
        "SKU-1267": {"stock": 22, "lead_time": 14, "reorder_point": 50, "unit_price": 140.43,
                      "substitutions": [{"product_id": "SKU-1268", "name": "Paint Roller Pro", "similarity": 0.85}]},
        # SKU-1289 Body Lotion — overstocked from end-of-season buy
        "SKU-1289": {"stock": 1800, "lead_time": 14, "reorder_point": 200, "unit_price": 7.98,
                      "substitutions": []},
    },
    "studio": {
        # SKU-1087 Adobe CC seats — software licenses, 0 lead time, "stock" = paid-but-unallocated
        "SKU-1087": {"stock": 6, "lead_time": 1, "reorder_point": 10, "unit_price": 16.09,
                      "substitutions": [{"product_id": "SKU-1088", "name": "Adobe CC Seat (annual)", "similarity": 0.95}]},
        # SKU-1029 Tea Bags — office consumable
        "SKU-1029": {"stock": 90, "lead_time": 3, "reorder_point": 30, "unit_price": 42.43,
                      "substitutions": []},
        # SKU-1113 Whiteboard markers — slow-moving overstock
        "SKU-1113": {"stock": 280, "lead_time": 7, "reorder_point": 30, "unit_price": 66.10,
                      "substitutions": []},
        # SKU-1134 Pens — about to run out, 14-day lead → critical
        "SKU-1134": {"stock": 8, "lead_time": 14, "reorder_point": 40, "unit_price": 4.73,
                      "substitutions": [{"product_id": "SKU-1135", "name": "Pens Pack v2 (50pk)", "similarity": 0.93}]},
    },
}


def _inventory_for(tenant: str | None) -> dict[str, dict]:
    return INVENTORY_BY_TENANT.get(tenant or "metsa",
                                    INVENTORY_BY_TENANT["metsa"])


# Backward-compat: Metsä's STOCK_LEVELS / LEAD_TIMES / REORDER_POINTS /
# SUBSTITUTIONS exposed as flat dicts so older callers keep working.
STOCK_LEVELS = {sku: row["stock"] for sku, row in INVENTORY_BY_TENANT["metsa"].items()}
LEAD_TIMES = {sku: row["lead_time"] for sku, row in INVENTORY_BY_TENANT["metsa"].items()}
REORDER_POINTS = {sku: row["reorder_point"] for sku, row in INVENTORY_BY_TENANT["metsa"].items()}
SUBSTITUTIONS = {sku: row["substitutions"] for sku, row in INVENTORY_BY_TENANT["metsa"].items() if row["substitutions"]}

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


def get_inventory_status(
    client: AitoClient,
    target_month: str = "2025-06",
    tenant: str | None = None,
) -> InventoryOverview:
    """Compute inventory status for this tenant's hero SKUs.

    For each product:
    1. Get demand forecast from demand_service.
    2. Compute daily demand = forecast / 30.
    3. Compute days_of_supply = stock / daily_demand.
    4. Flag critical if days_of_supply < lead_time.

    Args:
        client: Aito API client.
        target_month: Month to forecast demand for.
        tenant: Persona id; selects which hero SKUs + stock state to use.

    Returns:
        InventoryOverview with per-item status and summary counts.
    """
    # Target buffer for overstock calculation: 60 days
    TARGET_BUFFER_DAYS = 60

    inventory = _inventory_for(tenant)
    products = demo_products_for(tenant)
    items: list[InventoryItem] = []

    for product_id, product_info in products.items():
        row = inventory.get(product_id, {})
        stock = row.get("stock", 0)
        lead_time = row.get("lead_time", 14)
        reorder = row.get("reorder_point", 0)
        unit_price = row.get("unit_price", 0.0)
        sub_options = row.get("substitutions", [])

        # Get demand forecast
        demand = forecast_demand(client, product_id, target_month)
        monthly_forecast = demand.forecast if demand.forecast > 0 else demand.baseline
        daily_demand = monthly_forecast / 30.0

        if daily_demand > 0:
            days_of_supply = round(stock / daily_demand, 1)
        else:
            days_of_supply = 999.0  # No demand = effectively infinite supply

        status = _classify_status(days_of_supply, lead_time)
        subs = sub_options if status in ("critical", "low") else []

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

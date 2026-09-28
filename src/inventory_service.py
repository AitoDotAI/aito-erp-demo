"""Inventory Intelligence — will this run out before the next delivery?

Stock comes from `stock` and demand from `_estimate units_sold`, so the
question is the one a buyer asks: does what I have, plus what is already
on its way, cover what will sell before a new order could arrive?

It is asked twice. Once with Aito's forecast and once with the trailing
three-month average a plain ERP min/max rule uses — the rule the stock
in this table was actually managed by. Then it is checked: the months
after the cutoff are held out, so the view can show which items really
did run short and how often each forecast's warning was right. That
check is the claim; there is no other.

`stock` is synthetic and the view says so. It is simulated from the
same sales history the forecast learns from (data/generate_demand.py),
so it is depleted by real demand rather than typed in.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from src.aito_client import AitoClient
from src.demand_service import FEATURES, _whole_table

# The busiest stocked items, by sales over the last twelve months. Every
# one costs an `_estimate`, and a buyer's attention goes to the movers.
ITEMS_CHECKED = 40
OVERSTOCK_DAYS = 90


@dataclass
class StockCheck:
    sku: str
    name: str
    category: str
    supplier: str
    unit_price: float | None
    on_hand: int
    on_order: int
    next_delivery_month: str | None
    lead_time_days: int
    reorder_point: int
    arriving_in_time: int        # the part of on_order that lands within the lead time
    aito_daily: float            # `_estimate` for the cutoff month, per day
    trailing_daily: float        # the ERP rule's view of the same month
    actual_daily: float          # what sold (held out)
    neighbours: int
    where: dict                  # the exact `where` of the forecast

    def _cover(self, daily: float) -> float:
        return (self.on_hand + self.arriving_in_time) / daily if daily > 0 else math.inf

    def _short(self, daily: float) -> bool:
        return self._cover(daily) < self.lead_time_days

    @property
    def aito_short(self) -> bool:
        return self._short(self.aito_daily)

    @property
    def rule_short(self) -> bool:
        return self._short(self.trailing_daily)

    @property
    def actually_short(self) -> bool:
        return self._short(self.actual_daily)

    @property
    def status(self) -> str:
        """By Aito's forecast — the column the view leads with."""
        if self.aito_short:
            return "critical"
        cover = self._cover(self.aito_daily)
        if cover < 2 * self.lead_time_days:
            return "low"
        if cover > OVERSTOCK_DAYS:
            return "overstock"
        return "ok"

    def to_dict(self) -> dict:
        cover = self._cover(self.aito_daily)
        return {
            "sku": self.sku, "name": self.name, "category": self.category,
            "supplier": self.supplier, "unit_price": self.unit_price,
            "on_hand": self.on_hand, "on_order": self.on_order,
            "next_delivery_month": self.next_delivery_month,
            "arriving_in_time": self.arriving_in_time,
            "lead_time_days": self.lead_time_days, "reorder_point": self.reorder_point,
            "aito_daily": round(self.aito_daily, 2),
            "trailing_daily": round(self.trailing_daily, 2),
            "actual_daily": round(self.actual_daily, 2),
            "days_of_cover": None if math.isinf(cover) else round(cover, 1),
            "status": self.status,
            "aito_short": self.aito_short, "rule_short": self.rule_short,
            "actually_short": self.actually_short,
            "neighbours": self.neighbours,
            "where": self.where,
        }


def _months_after(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:]) + n
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y}-{m:02d}"


def _warning_score(items: list[StockCheck], flagged) -> dict:
    """How often a method's "will run short" was right, and how many real
    shortfalls it caught. Counts, not rates alone, so a reader can see
    how few cases a percentage rests on."""
    raised = [i for i in items if flagged(i)]
    real = [i for i in items if i.actually_short]
    hit = [i for i in raised if i.actually_short]
    return {"raised": len(raised), "right": len(hit),
            "real_shortfalls": len(real), "caught": len(hit)}


def get_inventory_status(client: AitoClient, tenant: str | None = None) -> dict:
    history = _whole_table(client, "monthly_demand")
    holdout = _whole_table(client, "monthly_demand_holdout")
    stock = {r["sku"]: r for r in _whole_table(client, "stock")}
    cutoff = min(r["month"] for r in holdout)

    last_months = sorted({r["month"] for r in history})[-12:]
    volume: dict[str, int] = {}
    for r in history:
        if r["sku"] in stock and r["month"] in last_months:
            volume[r["sku"]] = volume.get(r["sku"], 0) + r["units_sold"]
    chosen = sorted(volume, key=lambda s: (-volume[s], s))[:ITEMS_CHECKED]
    if not chosen:
        raise RuntimeError("no stocked item has sales in the last twelve months")

    first_month = {r["sku"]: r for r in holdout if r["month"] == cutoff}
    own_history: dict[str, list[dict]] = {}
    for r in history:
        own_history.setdefault(r["sku"], []).append(r)

    def check(sku: str) -> StockCheck:
        s = stock[sku]
        row = first_month[sku]
        where = {k: row[k] for k in FEATURES}
        res = client.estimate("monthly_demand", where, "units_sold")
        monthly = res.get("estimate")
        if not isinstance(monthly, (int, float)):
            raise ValueError(f"_estimate units_sold returned no number for {sku}: {res}")
        products = client.search("products", {"sku": sku}, limit=1).get("hits") or []
        if not products:
            raise RuntimeError(f"{sku} is stocked but not in products")
        recent = sorted(own_history[sku], key=lambda r: r["month"])[-3:]
        # A delivery already ordered counts if it lands before a new
        # order could: within the lead time, month-granular.
        horizon_end = _months_after(cutoff, max(0, math.ceil(s["lead_time_days"] / 30) - 1))
        # Nullable, and Aito omits a null column from the hit rather than
        # returning null: absent here means "nothing on order".
        next_delivery = s.get("next_delivery_month")
        arriving = s["on_order"] if next_delivery and next_delivery <= horizon_end else 0
        return StockCheck(
            sku=sku, name=products[0]["name"], category=row["category"],
            supplier=s["supplier"], unit_price=products[0].get("unit_price"),
            on_hand=s["on_hand"], on_order=s["on_order"],
            next_delivery_month=next_delivery,
            lead_time_days=s["lead_time_days"], reorder_point=s["reorder_point"],
            arriving_in_time=arriving,
            aito_daily=float(monthly) / 30,
            trailing_daily=sum(r["units_sold"] for r in recent) / 3 / 30,
            actual_daily=row["units_sold"] / 30,
            neighbours=len((res.get("why") or {}).get("components") or []),
            where=where)

    with ThreadPoolExecutor(max_workers=8) as pool:
        items = list(pool.map(check, chosen))

    order = {"critical": 0, "low": 1, "overstock": 2, "ok": 3}
    items.sort(key=lambda i: (order[i.status], i._cover(i.aito_daily)))
    counts = {k: sum(1 for i in items if i.status == k) for k in order}
    return {
        "as_of": cutoff,
        "items_checked": len(items),
        "counts": counts,
        "warnings": {
            "aito": _warning_score(items, lambda i: i.aito_short),
            "trailing_rule": _warning_score(items, lambda i: i.rule_short),
        },
        "synthetic_stock": True,
        "items": [i.to_dict() for i in items],
    }

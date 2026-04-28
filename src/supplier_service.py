"""Supplier intelligence — spend overview and delivery risk analysis.

Combines Aito's _search and _relate endpoints to build two views:
1. Spend overview: group purchases by supplier, sum amounts, count POs.
2. Delivery risk: use _relate to find which suppliers correlate with
   late deliveries.
"""

from dataclasses import dataclass, field

from src.aito_client import AitoClient


@dataclass
class SupplierSpend:
    supplier: str
    total_amount: float
    po_count: int
    avg_amount: float
    categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "supplier": self.supplier,
            "total_amount": self.total_amount,
            "po_count": self.po_count,
            "avg_amount": self.avg_amount,
            "categories": self.categories,
        }


@dataclass
class DeliveryRisk:
    supplier: str
    late_rate: float  # proportion of late deliveries
    lift: float  # how much more likely to be late vs baseline
    total_orders: int
    late_orders: int
    risk_level: str  # "high" | "medium" | "low"

    def to_dict(self) -> dict:
        return {
            "supplier": self.supplier,
            "late_rate": self.late_rate,
            "lift": self.lift,
            "total_orders": self.total_orders,
            "late_orders": self.late_orders,
            "risk_level": self.risk_level,
        }


@dataclass
class SupplierIntelligence:
    spend_overview: list[SupplierSpend]
    delivery_risks: list[DeliveryRisk]

    def to_dict(self) -> dict:
        # Both keys ship in parallel for one release: `spend_overview`
        # remains for any external/integration code that already
        # depends on the original payload; `top_suppliers` is the new
        # canonical name (matches use-case 5 doc and reads naturally
        # next to `delivery_risks`). Drop `spend_overview` after the
        # frontend has been updated and any downstream consumers have
        # had time to migrate.
        spend = [s.to_dict() for s in self.spend_overview]
        return {
            "top_suppliers": spend,
            "spend_overview": spend,
            "delivery_risks": self.delivery_risks_payload(),
        }

    def delivery_risks_payload(self) -> list[dict]:
        return [d.to_dict() for d in self.delivery_risks]


def _classify_risk(late_rate: float, lift: float) -> str:
    """Classify delivery risk based on late rate and lift."""
    if late_rate >= 0.30 or lift >= 2.0:
        return "high"
    elif late_rate >= 0.15 or lift >= 1.5:
        return "medium"
    else:
        return "low"


def get_spend_overview(client: AitoClient) -> list[SupplierSpend]:
    """Search purchases and group by supplier to build spend overview.

    Fetches a large sample of purchases and aggregates client-side.
    In production this would use Aito's aggregation or a data warehouse.
    """
    result = client.search("purchases", {}, limit=5000)
    hits = result.get("hits", [])

    # Group by supplier
    by_supplier: dict[str, list[dict]] = {}
    for row in hits:
        supplier = row.get("supplier", "Unknown")
        by_supplier.setdefault(supplier, []).append(row)

    overview = []
    for supplier, rows in by_supplier.items():
        amounts = [r.get("amount_eur", 0) for r in rows]
        categories = list({r.get("category", "") for r in rows if r.get("category")})
        total = sum(amounts)
        count = len(rows)
        overview.append(SupplierSpend(
            supplier=supplier,
            total_amount=round(total, 2),
            po_count=count,
            avg_amount=round(total / count, 2) if count else 0,
            categories=sorted(categories),
        ))

    overview.sort(key=lambda s: s.total_amount, reverse=True)
    return overview


def get_delivery_risk(client: AitoClient) -> list[DeliveryRisk]:
    """Use _relate to find suppliers with high late delivery rates.

    Asks Aito: "Given delivery_late=True, which suppliers are most
    related?" — suppliers with high lift are disproportionately late.
    """
    result = client.relate(
        "purchases",
        {"delivery_late": True},
        "supplier",
    )
    hits = result.get("hits", [])

    risks = []
    for hit in hits:
        related = hit.get("related", {})
        supplier_info = related.get("supplier", {})
        supplier_name = supplier_info.get("$has", "") if isinstance(supplier_info, dict) else str(supplier_info)

        if not supplier_name:
            continue

        lift = hit.get("lift", 1.0)
        fs = hit.get("fs", {})
        ps = hit.get("ps", {})

        total_orders = fs.get("f", 0)
        late_orders = fs.get("fOnCondition", 0)
        late_rate = ps.get("pOnCondition", 0.0)

        risks.append(DeliveryRisk(
            supplier=supplier_name,
            late_rate=round(late_rate, 3),
            lift=round(lift, 2),
            total_orders=total_orders,
            late_orders=late_orders,
            risk_level=_classify_risk(late_rate, lift),
        ))

    risks.sort(key=lambda r: r.lift, reverse=True)
    return risks


def get_supplier_intelligence(client: AitoClient) -> SupplierIntelligence:
    """Get complete supplier intelligence: spend overview + delivery risk."""
    return SupplierIntelligence(
        spend_overview=get_spend_overview(client),
        delivery_risks=get_delivery_risk(client),
    )

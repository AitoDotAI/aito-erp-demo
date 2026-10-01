"""Supplier intelligence — spend overview and delivery risk analysis.

Combines Aito's _search and _relate endpoints to build two views:
1. Spend overview: group purchases by supplier, sum amounts, count POs.
2. Delivery risk: use _relate to find which suppliers correlate with
   late deliveries.
"""

from dataclasses import dataclass, field

from src.aito_client import AitoClient
from src.demand_service import _whole_table


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
    late_rate: float  # this supplier's late deliveries / its deliveries
    base_late_rate: float  # late deliveries / all deliveries, every supplier
    lift: float  # Aito's lift: late_rate over base, shrunk toward 1 on thin data
    raw_lift: float  # late_rate / base_late_rate, straight from the counts
    total_orders: int
    late_orders: int
    risk_level: str  # "high" | "medium" | "low"

    def to_dict(self) -> dict:
        return {
            "supplier": self.supplier,
            "late_rate": self.late_rate,
            "base_late_rate": self.base_late_rate,
            "lift": self.lift,
            "raw_lift": self.raw_lift,
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


# The ONE risk rule. The header's "high risk" count, the table's badge
# and the side panel all read `risk_level`, so they cannot disagree.
#
# It is defined on LIFT — how much likelier a late delivery is from this
# supplier than from the average one — plus a floor on evidence. It used
# to take absolute late-rate thresholds too, calibrated against a column
# that was not a late rate (see get_delivery_risk), and it had no floor,
# so one late delivery out of twenty could read as high risk.
HIGH_RISK_LIFT = 2.0
MEDIUM_RISK_LIFT = 1.5
MIN_LATE_DELIVERIES = 3


def _classify_risk(lift: float, late: int) -> str:
    """Risk level from lift and the number of late deliveries behind it."""
    if late < MIN_LATE_DELIVERIES:
        return "low"
    if lift >= HIGH_RISK_LIFT:
        return "high"
    if lift >= MEDIUM_RISK_LIFT:
        return "medium"
    return "low"


def get_spend_overview(client: AitoClient) -> list[SupplierSpend]:
    """Search purchases and group by supplier to build spend overview.

    Reads every purchase and aggregates client-side. In production this
    would use Aito's aggregation or a data warehouse.
    """
    # The whole table, count asserted: Aurora has more than 5000 purchases,
    # and a fixed page summed as "total spend" under-counts without a word.
    hits = _whole_table(client, "purchases")

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
        # v1 wraps the value as {"$has": name}; v2 returns the bare string.
        related = hit["related"]["supplier"]
        supplier_name = related["$has"] if isinstance(related, dict) else related
        if not supplier_name:
            raise ValueError(f"_relate hit without a supplier: {hit}")

        # Every count below is read strictly. A missing key coerced to 0
        # would show a 0% late rate and a "low" badge — a claim the data
        # never made.
        lift = hit["lift"]
        fs = hit["fs"]

        # `fs.f` is this supplier's deliveries and `fs.fOnCondition` the
        # late ones among them, so their ratio is the late RATE.
        #
        # Not `ps.pOnCondition`, which is what this used to read. With
        # the late condition in the `where`, that is P(supplier | late) —
        # the supplier's SHARE of all late deliveries — and it made the
        # biggest supplier look like the worst: Neste read 19.4% because
        # 31 of the 160 late deliveries were theirs, while its late rate
        # is 31/477 = 6.5%. Checked against raw counts on env.master.
        total_orders = int(fs["f"])
        late_orders = int(fs["fOnCondition"])
        if total_orders <= 0 or fs["n"] <= 0:
            raise ValueError(f"_relate hit for {supplier_name} has no deliveries: {fs}")
        late_rate = late_orders / total_orders
        # The baseline the lift is measured against. Shipped so a reader
        # can see that Aito's lift is NOT late_rate / base_late_rate: it
        # is shrunk toward 1, harder the fewer deliveries a supplier has
        # (NCC Suomi: 10.1% vs 4.9% is 2.07x raw, Aito says 1.52x). That
        # shrinkage is why the risk rule can trust it on small suppliers.
        base_late_rate = fs["fCondition"] / fs["n"]

        risks.append(DeliveryRisk(
            supplier=supplier_name,
            late_rate=round(late_rate, 3),
            base_late_rate=round(base_late_rate, 3),
            lift=round(lift, 2),
            # Shown NEXT TO Aito's lift. On its own the shrunk figure read as
            # the supplier's actual rate: NCC Suomi showed 1.5x where its
            # deliveries are 2.1x as often late as everyone's.
            raw_lift=round(late_rate / base_late_rate, 2),
            total_orders=total_orders,
            late_orders=late_orders,
            risk_level=_classify_risk(lift=lift, late=late_orders),
        ))

    risks.sort(key=lambda r: r.lift, reverse=True)
    return risks


def get_supplier_intelligence(client: AitoClient) -> SupplierIntelligence:
    """Get complete supplier intelligence: spend overview + delivery risk."""
    return SupplierIntelligence(
        spend_overview=get_spend_overview(client),
        delivery_risks=get_delivery_risk(client),
    )

"""Generate ERP demo fixtures at realistic SMB scale.

Produces ~3000 purchases, ~1500 products, ~8000 orders, ~3000 price_history rows
spanning 2023-01 → 2025-05. The canonical demo PO numbers (PO-7841..7846,
PO-7799, PO-7812, PO-7827, PO-7831, PO-7838, PO-7845) and SKUs (SKU-4421,
SKU-FUEL, SKU-2234, SKU-HVAC, SKU-5560, SKU-9901, SKU-8812) are preserved
so the existing pages and tests keep working.

Run with: python data/generate_fixtures.py
"""

import json
import random
from pathlib import Path

random.seed(42)
DATA = Path(__file__).resolve().parent

# ── Suppliers with known patterns (matching the spec) ─────────────
# Each supplier maps deterministically to cost_center + account_code in the
# vast majority of historical records. The 5–10% noise is what teaches Aito
# that uncertainty exists, and what produces the realistic confidence spread.

SUPPLIERS = {
    # Procurement-only
    "Elenia Oy":             {"cc": "Facilities",   "acct": "6110", "approver": "M. Hakala",   "category": "utilities",  "freq": 14, "amount": (1500, 6500)},
    "Wärtsilä Components":   {"cc": "Production",   "acct": "4220", "approver": "T. Virtanen", "category": "production", "freq": 30, "amount": (300, 8000)},
    "Telia Finland Oyj":     {"cc": "IT",           "acct": "5510", "approver": "J. Lehtinen", "category": "telecom",    "freq": 28, "amount": (300, 1500)},
    "Elisa Oyj":             {"cc": "IT",           "acct": "5510", "approver": "J. Lehtinen", "category": "telecom",    "freq": 24, "amount": (200, 1800)},
    "Berner Oy":             {"cc": "Facilities",   "acct": "4110", "approver": "M. Hakala",   "category": "cleaning",   "freq": 18, "amount": (150, 1200)},
    "Abloy Oy":              {"cc": "Facilities",   "acct": "6230", "approver": "M. Hakala",   "category": "security",   "freq": 8,  "amount": (200, 9000)},
    "Neste Oyj":             {"cc": "Logistics",    "acct": "4310", "approver": "K. Mäkinen",  "category": "fuel",       "freq": 50, "amount": (1500, 4500)},
    "Lindström Oy":          {"cc": "Production",   "acct": "4810", "approver": "T. Virtanen", "category": "ppe",        "freq": 25, "amount": (400, 2400)},
    "Caverion Suomi":        {"cc": "Facilities",   "acct": "6120", "approver": "M. Hakala",   "category": "maintenance","freq": 32, "amount": (800, 6500)},
    "Fazer Food Services":   {"cc": "HR",           "acct": "5710", "approver": "K. Mäkinen",  "category": "catering",   "freq": 40, "amount": (300, 2200)},
    "Siemens Finland":       {"cc": "Production",   "acct": "4250", "approver": "T. Virtanen", "category": "capex",      "freq": 6,  "amount": (8000, 35000)},
    "Harjula Consulting":    {"cc": "Admin",        "acct": "7100", "approver": "R. Leinonen", "category": "consulting", "freq": 3,  "amount": (1500, 8000)},
    "ABB Service":           {"cc": "Production",   "acct": "4220", "approver": "T. Virtanen", "category": "production", "freq": 18, "amount": (500, 4500)},
    "Schneider Finland":     {"cc": "Production",   "acct": "4225", "approver": "T. Virtanen", "category": "electrical", "freq": 14, "amount": (200, 3500)},
    "Atea Finland":          {"cc": "IT",           "acct": "5520", "approver": "J. Lehtinen", "category": "it",         "freq": 12, "amount": (150, 6000)},
    "YIT Service":           {"cc": "Facilities",   "acct": "6120", "approver": "M. Hakala",   "category": "maintenance","freq": 10, "amount": (600, 4500)},
    "Lyreco":                {"cc": "Admin",        "acct": "6810", "approver": "R. Leinonen", "category": "office",     "freq": 22, "amount": (50, 800)},
    "Kespro":                {"cc": "HR",           "acct": "5710", "approver": "K. Mäkinen",  "category": "catering",   "freq": 16, "amount": (200, 1800)},
    "Shell Finland":         {"cc": "Logistics",    "acct": "4310", "approver": "K. Mäkinen",  "category": "fuel",       "freq": 12, "amount": (1200, 4000)},
    "Stanley Security":      {"cc": "Facilities",   "acct": "6230", "approver": "M. Hakala",   "category": "security",   "freq": 5,  "amount": (300, 3500)},
}

PROJECTS = ["OPEX-2024", "OPEX-2025", "MAINT-2024", "MAINT-2025", "CAPEX-2024", "CAPEX-2025", "IT-OPS", "OFFICE", "PROD-LINE-A", "PROD-LINE-B"]

# Months 2023-01 through 2025-05
def month_iter():
    for year in (2023, 2024, 2025):
        for month in range(1, 13):
            if year == 2025 and month > 5:
                break
            yield f"{year}-{month:02d}"

MONTHS = list(month_iter())  # 29 months

# ── Generate purchases ────────────────────────────────────────────
# Target: ~3000 records across 29 months ≈ 100/month, distributed by supplier freq.

purchases: list[dict] = []
po_counter = 1000  # PO-1001..

# Reserve specific PO numbers used by demo pages
RESERVED_POS = {
    "PO-7841": ("Elenia Oy",           "Electricity Q2 2025",          4820.00, "utilities"),
    "PO-7842": ("Wärtsilä Components", "Hydraulic seals #WS-442",      1240.00, "production"),
    "PO-7843": ("Telia Finland Oyj",   "Mobile subscriptions May",      780.00, "telecom"),
    "PO-7844": ("Berner Oy",           "Cleaning chemicals bulk",       392.00, "cleaning"),
    "PO-7845": ("Abloy Oy",            "Security upgrade — door locks", 6100.00, "security"),
    "PO-7846": ("Neste Oyj",           "Fleet fuel card top-up",       2150.00, "fuel"),
    "PO-7799": ("Harjula Consulting",  "Strategy consulting Q1",       3200.00, "consulting"),
    "PO-7812": ("Fazer Food Services", "Anomaly: misposted catering",  1450.00, "catering"),
    "PO-7827": ("Neste Oyj",           "Bulk fuel pre-purchase",       9800.00, "fuel"),
    "PO-7831": ("Siemens Finland",     "Capex equipment upgrade",     22400.00, "capex"),
    "PO-7838": ("Harjula Consulting",  "First-time vendor advisory",    890.00, "consulting"),
}

def routed_by_for(amount, category, override=None):
    """Realistic distribution: 21% rules, 51% aito_high, 10% aito_reviewed, 18% manual."""
    if override:
        return override
    r = random.random()
    if r < 0.21:
        return "rule"
    elif r < 0.72:
        return "aito_high"
    elif r < 0.82:
        return "aito_reviewed"
    return "manual"

def approval_level_for(amount, category):
    """Discoverable rule: amount > 5K + security → CFO; > 20K + capex → board."""
    if amount > 20000 and category == "capex":
        return "board"
    if amount > 5000 and category == "security":
        return "cfo"
    if amount > 5000:
        # Some > 5K go to CFO, most to manager — creates a fuzzy threshold
        return "cfo" if random.random() < 0.55 else "manager"
    return "manager"

def approver_for(supplier_info, level, override=None):
    if override:
        return override
    if level == "cfo" or level == "board":
        return "R. Leinonen"
    return supplier_info["approver"]

# Insert reserved POs first
for po_id, (sup, desc, amt, cat) in RESERVED_POS.items():
    s = SUPPLIERS[sup]
    # Special case: PO-7812 is the Fazer anomaly with wrong account code
    if po_id == "PO-7812":
        acct = "4220"  # The mis-posted one
        cc = "Production"
    else:
        acct = s["acct"]
        cc = s["cc"]
    level = approval_level_for(amt, cat)
    purchases.append({
        "purchase_id": po_id,
        "supplier": sup,
        "description": desc,
        "category": cat,
        "amount_eur": amt,
        "cost_center": cc,
        "account_code": acct,
        "approver": approver_for(s, level),
        "approval_level": level,
        "delivery_late": False,
        "order_month": "2025-05",
        "project": random.choice(PROJECTS),
        "routed_by": "manual",  # These are unrouted (the demo POs)
    })

# Bulk historical generation
DESCRIPTIONS_BY_CATEGORY = {
    "utilities":    ["Electricity Q1", "Electricity Q2", "Electricity Q3", "Electricity Q4", "District heating", "Water utility"],
    "production":   ["Hydraulic seals", "Bearings batch", "Conveyor parts", "Pump replacement", "Drive belt set", "Filter cartridges", "Coupling elements"],
    "telecom":      ["Mobile subscriptions", "Internet service", "VoIP licenses", "Mobile data top-up"],
    "cleaning":     ["Cleaning chemicals", "Floor polish bulk", "Sanitation supplies", "Hand soap refill"],
    "security":     ["Door lock upgrade", "Access control system", "CCTV camera install", "Master key cylinders"],
    "fuel":         ["Fleet fuel top-up", "Diesel bulk delivery", "Fuel card refill", "Engine oil 5W-30"],
    "ppe":          ["Workwear set rental", "Safety boots batch", "Hi-vis vests", "Safety helmets"],
    "maintenance":  ["HVAC quarterly service", "Plumbing repair", "Electrical inspection", "Equipment calibration"],
    "catering":     ["Staff canteen monthly", "Vending machine refill", "Office coffee supply", "Event catering"],
    "capex":        ["Production line upgrade", "Robotics installation", "Industrial equipment"],
    "consulting":   ["Strategy advisory", "Compliance audit", "Process consulting"],
    "electrical":   ["Cable supply batch", "Contactors and relays", "Terminal blocks"],
    "it":           ["Laptop refresh batch", "Software licenses", "Network equipment", "USB-C docks"],
    "office":       ["A4 paper supply", "Office stationery", "Printer toner", "Folders and binders"],
}

for month in MONTHS:
    for sup, info in SUPPLIERS.items():
        # Each supplier gets `freq` POs PER MONTH (with variability)
        num_this_month = max(1, int(round(info["freq"] / 4 * random.uniform(0.7, 1.3))))
        for _ in range(num_this_month):
            po_counter += 1
            po_id = f"PO-{po_counter}"

            cat = info["category"]
            descriptions = DESCRIPTIONS_BY_CATEGORY.get(cat, ["Generic purchase"])
            desc = random.choice(descriptions)

            lo, hi = info["amount"]
            amount = round(random.uniform(lo, hi), 2)

            # Add 5–10% noise: some records have slightly different cc/acct
            if random.random() < 0.07:
                # Noise in cost center
                cc = random.choice(["Facilities", "Production", "IT", "Logistics", "HR", "Admin"])
            else:
                cc = info["cc"]

            if random.random() < 0.06:
                # Noise in account code — pick a nearby one
                acct = random.choice(["4100", "4110", "4220", "4310", "5510", "5710", "6110", "6810"])
            else:
                acct = info["acct"]

            level = approval_level_for(amount, cat)
            late = random.random() < (
                0.18 if (sup == "Neste Oyj" and month.endswith(("-10", "-11", "-12"))) else
                0.10 if (sup == "Elenia Oy" and month.endswith(("-12", "-01", "-02"))) else
                0.04
            )

            purchases.append({
                "purchase_id": po_id,
                "supplier": sup,
                "description": desc,
                "category": cat,
                "amount_eur": amount,
                "cost_center": cc,
                "account_code": acct,
                "approver": approver_for(info, level),
                "approval_level": level,
                "delivery_late": late,
                "order_month": month,
                "project": random.choice(PROJECTS),
                "routed_by": routed_by_for(amount, cat),
            })

print(f"Purchases: {len(purchases)}")

# ── Generate products ────────────────────────────────────────────
# Target: ~1500 SKUs. Most complete; ~150 incomplete to drive Catalog view.

CATEGORIES_PRODUCT = {
    "Spare Parts":            {"price": (15, 850), "hs": ["8484.10", "8482.10", "8483.30", "8431.20"], "units": ["ea", "set"], "acct": "4220", "tax": "Standard 25.5%"},
    "Electrical Components":  {"price": (2, 180),  "hs": ["8547.90", "8536.50", "8504.40", "8537.10"], "units": ["ea", "m"],   "acct": "4225", "tax": "Standard 25.5%"},
    "PPE & Workwear":         {"price": (12, 220), "hs": ["6211.33", "6403.40", "6307.90"],            "units": ["set", "pair"],"acct": "4810", "tax": "Standard 25.5%"},
    "Cleaning Supplies":      {"price": (8, 95),   "hs": ["3402.20", "3402.90"],                       "units": ["L", "kg"],   "acct": "4110", "tax": "Standard 25.5%"},
    "Catering Supplies":      {"price": (5, 65),   "hs": ["1806.90", "2106.90"],                       "units": ["pack", "box"],"acct": "5710", "tax": "Reduced 14%"},
    "Fleet & Fuel":           {"price": (45, 220), "hs": ["2710.12", "2710.19"],                       "units": ["100L", "L"], "acct": "4310", "tax": "Standard 25.5%"},
    "Maintenance Services":   {"price": (60, 145), "hs": [],                                            "units": ["hr"],        "acct": "6120", "tax": "Standard 25.5%"},
    "Office Supplies":        {"price": (3, 85),   "hs": ["4820.10", "8472.90"],                       "units": ["ea", "pack"],"acct": "6810", "tax": "Standard 25.5%"},
    "IT Equipment":           {"price": (45, 1850),"hs": ["8471.30", "8517.62", "8528.42"],            "units": ["ea"],        "acct": "5510", "tax": "Standard 25.5%"},
    "Security":               {"price": (35, 850), "hs": ["8301.40", "8531.10"],                       "units": ["ea", "set"], "acct": "6230", "tax": "Standard 25.5%"},
}

# Reserve canonical SKUs from spec
RESERVED_PRODUCTS = [
    {"sku": "SKU-4421", "name": "Wärtsilä Seal Kit WS-442",   "supplier": "Wärtsilä Components", "category": "Spare Parts",          "unit_price": 148.00, "hs_code": "8484.10",  "unit_of_measure": "ea",   "weight_kg": 0.8, "account_code": "4220", "tax_class": "Standard 25.5%"},
    {"sku": "SKU-FUEL", "name": "Neste Fleet Fuel (100L)",     "supplier": "Neste Oyj",            "category": "Fleet & Fuel",         "unit_price": 94.00,  "hs_code": "2710.12",  "unit_of_measure": "100L", "weight_kg": 84.0,"account_code": "4310", "tax_class": "Standard 25.5%"},
    {"sku": "SKU-2234", "name": "Lindström Workwear Set M",    "supplier": "Lindström Oy",         "category": "PPE & Workwear",       "unit_price": 89.00,  "hs_code": "6211.33",  "unit_of_measure": "set",  "weight_kg": 1.2, "account_code": "4810", "tax_class": "Standard 25.5%"},
    {"sku": "SKU-HVAC", "name": "Caverion HVAC Service (hr)",  "supplier": "Caverion Suomi",       "category": "Maintenance Services", "unit_price": 82.00,  "hs_code": None,        "unit_of_measure": "hr",   "weight_kg": None,"account_code": "6120", "tax_class": "Standard 25.5%"},
    {"sku": "SKU-5560", "name": "Fazer Vending Refill Pack",   "supplier": "Fazer Food Services",  "category": "Catering Supplies",    "unit_price": 24.90,  "hs_code": "1806.90",  "unit_of_measure": "pack", "weight_kg": 5.5, "account_code": "5710", "tax_class": "Reduced 14%"},
    # Intentionally incomplete demo products
    {"sku": "SKU-9901", "name": "Generic Cable Gland M20",     "supplier": None,                   "category": None,                    "unit_price": None,   "hs_code": None,        "unit_of_measure": None,   "weight_kg": None,"account_code": None,   "tax_class": None},
    {"sku": "SKU-8812", "name": "Berner Floor Cleaner 10L",    "supplier": "Berner Oy",            "category": None,                    "unit_price": 42.50,  "hs_code": "3402.20",  "unit_of_measure": None,   "weight_kg": 10.5,"account_code": None,   "tax_class": None},
]

products: list[dict] = list(RESERVED_PRODUCTS)
sku_counter = 1000

NAME_TEMPLATES = {
    "Spare Parts":           ["Bearing", "V-Belt", "Pump Seal", "Filter Cartridge", "Coupling", "Drive Shaft", "Hydraulic Hose", "O-Ring Set", "Gasket Kit", "Sprocket"],
    "Electrical Components": ["Cable Gland", "Contactor", "Terminal Block", "Cable Tie Pack", "Fuse Holder", "Relay 24V", "Connector", "Heat Shrink"],
    "PPE & Workwear":        ["Workwear Set", "Safety Boots", "Hi-Vis Vest", "Safety Helmet", "Work Gloves", "Hearing Protection", "Safety Glasses", "Knee Pads"],
    "Cleaning Supplies":     ["Multi-Surface Cleaner", "Toilet Paper Pack", "Hand Soap Refill", "Paper Towels", "Window Cleaner", "Floor Polish"],
    "Catering Supplies":     ["Coffee Beans", "Sugar Sachets", "Tea Bags", "Bottled Water", "Snack Mix", "Disposable Cups"],
    "Fleet & Fuel":          ["Diesel B7", "AdBlue", "Engine Oil", "Tire", "Windshield Fluid", "Brake Pads"],
    "Maintenance Services":  ["Electrical Inspection", "Plumbing Service", "Cleaning Service", "Equipment Calibration", "HVAC Tuning"],
    "Office Supplies":       ["A4 Copy Paper", "Black Pens Pack", "Stapler", "Folder Pack", "Whiteboard Markers", "Sticky Notes"],
    "IT Equipment":          ["Laptop", "USB-C Dock", "External SSD", "Wireless Mouse", "Mechanical Keyboard", "Monitor 27\"", "Webcam"],
    "Security":              ["Padlock", "Door Closer", "Card Reader", "CCTV Camera", "Access Card Pack"],
}

EXISTING_SKUS = {p["sku"] for p in products}

# Generate ~1500 products total
TARGET_PRODUCTS = 1500
INCOMPLETE_RATE = 0.05  # 5% incomplete — realistic for an actively-maintained catalog

while len(products) < TARGET_PRODUCTS:
    sku_counter += 1
    sku = f"SKU-{sku_counter}"
    if sku in EXISTING_SKUS:
        continue
    EXISTING_SKUS.add(sku)

    cat = random.choice(list(CATEGORIES_PRODUCT.keys()))
    cat_data = CATEGORIES_PRODUCT[cat]
    template = random.choice(NAME_TEMPLATES[cat])
    suffix = random.choice(["", " v2", " HD", " Pro", " 10pk", " M16", " 12V", " kit", " #" + str(random.randint(100, 999))])
    name = template + suffix

    # Pick a supplier whose category matches
    candidate_suppliers = [s for s, info in SUPPLIERS.items() if info["category"] in (cat.lower(), "production", "office", "it") or random.random() < 0.05]
    supplier = random.choice(candidate_suppliers) if candidate_suppliers else random.choice(list(SUPPLIERS.keys()))

    incomplete = random.random() < INCOMPLETE_RATE
    if incomplete:
        # Drop 2-4 fields randomly
        n_drop = random.randint(2, 4)
        droppable = ["category", "unit_price", "hs_code", "unit_of_measure", "weight_kg", "account_code", "tax_class"]
        dropped = set(random.sample(droppable, n_drop))
    else:
        dropped = set()

    products.append({
        "sku": sku,
        "name": name,
        "supplier": supplier if "supplier" not in dropped else None,
        "category": cat if "category" not in dropped else None,
        "unit_price": round(random.uniform(*cat_data["price"]), 2) if "unit_price" not in dropped else None,
        "hs_code": (random.choice(cat_data["hs"]) if cat_data["hs"] else None) if "hs_code" not in dropped else None,
        "unit_of_measure": random.choice(cat_data["units"]) if "unit_of_measure" not in dropped else None,
        "weight_kg": round(random.uniform(0.05, 8.0), 2) if "weight_kg" not in dropped and cat != "Maintenance Services" else None,
        "account_code": cat_data["acct"] if "account_code" not in dropped else None,
        "tax_class": cat_data["tax"] if "tax_class" not in dropped else None,
    })

print(f"Products: {len(products)}")

# ── Generate orders ──────────────────────────────────────────────
# Target: ~8000 orders over 29 months, biased toward demo SKUs to keep their
# patterns visible (the seasonality stories).

orders: list[dict] = []
order_counter = 0

# Demo SKUs with seasonal stories
DEMO_SKU_PROFILES = {
    "SKU-4421": {"avg": 8,  "seasonal": {"03": 1.7, "09": 1.7}, "trend": 0.03},  # maintenance windows
    "SKU-FUEL": {"avg": 42, "seasonal": {"07": 0.65, "08": 0.7},  "trend": 0.0},  # summer dip
    "SKU-2234": {"avg": 6,  "seasonal": {"08": 2.3, "09": 1.4},  "trend": 0.05},  # August onboarding spike
    "SKU-HVAC": {"avg": 24, "seasonal": {},                        "trend": 0.0},  # stable
    "SKU-5560": {"avg": 18, "seasonal": {"05": 1.4, "12": 1.6},  "trend": 0.02},  # events
    "SKU-9901": {"avg": 30, "seasonal": {},                        "trend": 0.04},  # high-volume small part
}

# Generate orders for demo SKUs across all months
for sku, profile in DEMO_SKU_PROFILES.items():
    for month_idx, month in enumerate(MONTHS):
        mm = month.split("-")[1]
        seasonal_factor = profile["seasonal"].get(mm, 1.0)
        trend_factor = 1.0 + profile["trend"] * month_idx
        units = max(0, int(round(profile["avg"] * seasonal_factor * trend_factor * random.uniform(0.85, 1.15))))
        if units > 0:
            order_counter += 1
            orders.append({
                "order_id": f"ORD-{order_counter:05d}",
                "product_id": sku,
                "month": month,
                "units_sold": units,
            })

# Fill in orders for many other products to get to ~5000
OTHER_SKUS = [p["sku"] for p in products if p["sku"] not in DEMO_SKU_PROFILES and p.get("category") is not None][:200]
for sku in OTHER_SKUS:
    for month in MONTHS:
        if random.random() < 0.85:  # Most products sell most months
            order_counter += 1
            orders.append({
                "order_id": f"ORD-{order_counter:05d}",
                "product_id": sku,
                "month": month,
                "units_sold": random.randint(1, 35),
            })

print(f"Orders: {len(orders)}")

# ── Generate price_history ───────────────────────────────────────

price_history: list[dict] = []
price_counter = 0

# Demo SKU price ranges — match the spec's expected ranges
DEMO_PRICE_PROFILES = {
    "SKU-4421": {"mean": 148, "std": 18, "suppliers": ["Wärtsilä Components", "Parts Direct", "Nordic Supply"], "n": 60},
    "SKU-FUEL": {"mean": 94,  "std": 6,  "suppliers": ["Neste Oyj", "Shell Finland", "ABC Energy"],            "n": 80},
    "SKU-2234": {"mean": 89,  "std": 9,  "suppliers": ["Lindström Oy", "Alsico", "Engel"],                     "n": 50},
    "SKU-HVAC": {"mean": 82,  "std": 7,  "suppliers": ["Caverion Suomi", "YIT Service", "Granlund"],           "n": 50},
    "SKU-5560": {"mean": 25,  "std": 3,  "suppliers": ["Fazer Food Services", "Kespro"],                       "n": 40},
    "SKU-9901": {"mean": 3.40,"std": 0.6,"suppliers": ["Generic Supplier", "Schneider Finland"],               "n": 35},
}

for sku, profile in DEMO_PRICE_PROFILES.items():
    for _ in range(profile["n"]):
        price_counter += 1
        # Most prices cluster near mean; ~5% are outliers (the flagged quotes)
        if random.random() < 0.05:
            price = profile["mean"] * random.uniform(1.20, 1.45)
        else:
            price = max(0.5, random.gauss(profile["mean"], profile["std"]))
        price_history.append({
            "price_id": f"PH-{price_counter:05d}",
            "product_id": sku,
            "supplier": random.choice(profile["suppliers"]),
            "unit_price": round(price, 2),
            "volume": random.choice([1, 5, 10, 25, 50, 100]),
            "order_date": f"{random.choice(MONTHS)}-{random.randint(1, 28):02d}",
        })

# Add price history for additional products to reach ~3000 total
ADDITIONAL_PRICE_SKUS = [p["sku"] for p in products if p.get("unit_price") is not None and p["sku"] not in DEMO_PRICE_PROFILES][:200]
for sku in ADDITIONAL_PRICE_SKUS:
    base_price = next(p["unit_price"] for p in products if p["sku"] == sku)
    n = random.randint(8, 18)
    for _ in range(n):
        price_counter += 1
        price = max(0.5, random.gauss(base_price, base_price * 0.08))
        if random.random() < 0.04:
            price = base_price * random.uniform(1.20, 1.40)
        # Find supplier from product
        prod = next(p for p in products if p["sku"] == sku)
        sup = prod.get("supplier") or random.choice(list(SUPPLIERS.keys()))
        price_history.append({
            "price_id": f"PH-{price_counter:05d}",
            "product_id": sku,
            "supplier": sup,
            "unit_price": round(price, 2),
            "volume": random.choice([1, 5, 10, 25, 50, 100]),
            "order_date": f"{random.choice(MONTHS)}-{random.randint(1, 28):02d}",
        })

print(f"Price history: {len(price_history)}")

# ── Write fixtures ───────────────────────────────────────────────

with open(DATA / "purchases.json", "w") as f:
    json.dump(purchases, f, indent=2, ensure_ascii=False)
with open(DATA / "products.json", "w") as f:
    json.dump(products, f, indent=2, ensure_ascii=False)
with open(DATA / "orders.json", "w") as f:
    json.dump(orders, f, indent=2, ensure_ascii=False)
with open(DATA / "price_history.json", "w") as f:
    json.dump(price_history, f, indent=2, ensure_ascii=False)

# Quick sanity stats
incomplete_count = sum(1 for p in products if any(p.get(f) is None for f in ["category", "unit_price", "hs_code", "unit_of_measure", "weight_kg", "account_code", "tax_class"]))
print(f"\nSummary:")
print(f"  Purchases: {len(purchases)} ({len(MONTHS)} months × ~{len(purchases)//len(MONTHS)} avg)")
print(f"  Products:  {len(products)} total, {incomplete_count} incomplete ({round(incomplete_count/len(products)*100, 1)}%)")
print(f"  Orders:    {len(orders)}")
print(f"  Prices:    {len(price_history)}")
print(f"  Total:     {len(purchases) + len(products) + len(orders) + len(price_history)} records")

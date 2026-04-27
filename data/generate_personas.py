"""Generate per-tenant demo fixtures.

Produces three industry-distinct universes that map onto the three
TopBar profiles:

  data/metsa/     → Metsä Machinery Oy  (industrial maintenance,
                    Lemonsoft-style buyer)
  data/aurora/    → Aurora Retail Oy    (multi-channel retail,
                    Oscar / ERPly-style buyer)
  data/studio/    → Helsinki Studio     (professional services,
                    horizontal SaaS buyer)

Every persona produces the full table set (purchases / products /
orders / price_history / projects / assignments) so the schemas in
src/data_loader.py succeed on each tenant — but the *content* is
industry-appropriate. Empty / thin tables are fine where the
persona's UI doesn't surface them.

Run with:  python data/generate_personas.py
"""

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parent

# Months 2022-06 through 2026-03 (46 months) — wider window than
# before so per-supplier _relate has enough samples even on the
# thinner personas (Studio's 12-25 freq suppliers).
MONTHS = [
    f"{y}-{m:02d}"
    for y in (2022, 2023, 2024, 2025, 2026)
    for m in range(1, 13)
    if (y, m) >= (2022, 6) and (y, m) <= (2026, 3)
]


# ── Persona spec ────────────────────────────────────────────────────


@dataclass
class SupplierSpec:
    """One supplier and the patterns the persona should learn for it."""
    name: str
    cc: str
    acct: str
    approver: str
    category: str
    freq: int                  # ~POs per month
    amount: tuple[float, float]
    late_factor: float = 1.0   # multiplied into the base late rate


@dataclass
class PersonaSpec:
    """Everything that changes between three industries."""
    tenant_id: str
    name: str
    suppliers: list[SupplierSpec]
    cost_centres: list[str]
    approvers: dict[str, str]           # cfo, board → person
    projects_pool: list[str]            # GL-style project codes for purchases.project
    # Catalog / orders — retail-heavy personas set these big; service personas thin.
    n_products: int
    n_orders: int
    n_price_history: int
    # Operations layer.
    n_completed_projects: int
    n_active_projects: int
    project_types: dict[str, dict]      # project_type → {budget, duration, team, weight}
    project_managers: list[str]
    project_leads: dict[str, list[str]] # project_type → leads
    project_team_pool: list[str]
    project_reliable: set[str]
    project_chaotic: set[str]
    project_customers: dict[str, list[str]]
    manager_fit: dict[tuple[str, str], float]
    # Description vocabularies — used to build readable purchase descriptions.
    descriptions: dict[str, list[str]]
    # Product catalog (commerce-oriented persona only — others get a thin set)
    product_categories: dict[str, dict] = field(default_factory=dict)
    product_name_templates: dict[str, list[str]] = field(default_factory=dict)


# ── Metsä Machinery Oy — industrial maintenance / construction ──────


METSA = PersonaSpec(
    tenant_id="metsa",
    name="Metsä Machinery Oy",
    suppliers=[
        SupplierSpec("Wärtsilä Components",   "Production",   "4220", "T. Virtanen", "production",  32, (300, 8000)),
        SupplierSpec("ABB Service",           "Production",   "4220", "T. Virtanen", "production",  20, (500, 5500)),
        SupplierSpec("Siemens Finland",       "Production",   "4250", "T. Virtanen", "capex",        7, (8000, 45000)),
        SupplierSpec("Schneider Finland",     "Production",   "4225", "T. Virtanen", "electrical",  16, (200, 3500)),
        SupplierSpec("Konecranes",            "Production",   "4225", "T. Virtanen", "capex",        4, (12000, 60000)),
        SupplierSpec("Sandvik Mining",        "Production",   "4220", "T. Virtanen", "production",   6, (3000, 22000)),
        SupplierSpec("Caverion Suomi",        "Site-Helsinki","6120", "M. Hakala",   "maintenance", 28, (800, 6500)),
        SupplierSpec("YIT Service",           "Site-Tampere", "6120", "M. Hakala",   "maintenance", 18, (600, 5500)),
        SupplierSpec("NCC Suomi",             "Site-Oulu",    "6125", "M. Hakala",   "construction", 8, (15000, 80000), late_factor=1.6),
        SupplierSpec("Lemminkäinen",          "Site-Tampere", "6125", "M. Hakala",   "construction", 5, (8000, 35000), late_factor=1.4),
        SupplierSpec("Vesto Service",         "Maintenance",  "6120", "M. Hakala",   "maintenance", 14, (400, 3200)),
        SupplierSpec("Abloy Oy",              "Maintenance",  "6230", "M. Hakala",   "security",     6, (200, 9000)),
        SupplierSpec("Elenia Oy",             "Site-Helsinki","6110", "M. Hakala",   "utilities",   12, (1500, 6500)),
        SupplierSpec("Fortum",                "Site-Tampere", "6110", "M. Hakala",   "utilities",   10, (2200, 9500)),
        SupplierSpec("Neste Oyj",             "Logistics",    "4310", "K. Mäkinen",  "fuel",        40, (1500, 4500), late_factor=1.5),
        SupplierSpec("Shell Finland",         "Logistics",    "4310", "K. Mäkinen",  "fuel",        12, (1200, 4000)),
        SupplierSpec("Lindström Oy",          "Production",   "4810", "T. Virtanen", "ppe",         20, (400, 2400)),
        SupplierSpec("Berner Oy",             "Site-Helsinki","4110", "M. Hakala",   "cleaning",    10, (150, 1200)),
        SupplierSpec("Telia Finland Oyj",     "Admin",        "5510", "J. Lehtinen", "telecom",      8, (300, 1500)),
        SupplierSpec("Lyreco",                "Admin",        "6810", "R. Leinonen", "office",       6, (50, 800)),
    ],
    cost_centres=[
        "Production", "Site-Helsinki", "Site-Tampere", "Site-Oulu",
        "Maintenance", "Logistics", "Admin",
    ],
    approvers={"manager_default": "M. Hakala", "cfo": "R. Leinonen", "board": "R. Leinonen"},
    projects_pool=[
        "MAINT-2024", "MAINT-2025", "CAPEX-2024", "CAPEX-2025",
        "SITE-HEL-A", "SITE-HEL-B", "SITE-TRE-1", "SITE-OUL-1",
        "PROD-LINE-A", "PROD-LINE-B",
    ],
    n_products=320,           # spare parts catalog only — not retail SKUs
    n_orders=1400,
    n_price_history=900,
    n_completed_projects=220,
    n_active_projects=65,
    project_types={
        "maintenance":  {"budget": (8000, 60000),  "duration": (10, 60),  "team": (2, 5), "weight": 40},
        "construction": {"budget": (40000, 280000),"duration": (60, 240), "team": (5, 12),"weight": 25},
        "rollout":      {"budget": (15000, 80000), "duration": (20, 90),  "team": (3, 6), "weight": 15},
        "audit":        {"budget": (4000, 25000),  "duration": (5, 25),   "team": (1, 3), "weight": 10},
        "rd":           {"budget": (20000, 120000),"duration": (30, 150), "team": (2, 5), "weight": 10},
    },
    project_managers=["M. Hakala", "T. Virtanen", "K. Mäkinen", "J. Lehtinen"],
    project_leads={
        "maintenance":  ["P. Korhonen", "T. Virtanen", "S. Niemi"],
        "construction": ["L. Aho", "P. Korhonen", "K. Saari"],
        "rollout":      ["A. Lindgren", "K. Saari", "L. Aho"],
        "audit":        ["R. Leinonen", "H. Mattila"],
        "rd":           ["E. Heikkinen", "M. Salo", "K. Saari"],
    },
    project_team_pool=[
        "A. Lindgren", "K. Saari", "L. Aho", "P. Korhonen", "S. Niemi",
        "M. Salo", "E. Heikkinen", "H. Mattila", "V. Jokinen", "T. Rinne",
        "O. Halonen", "I. Pulkkinen", "N. Forsberg", "J. Karjalainen",
    ],
    project_reliable={"A. Lindgren", "K. Saari", "P. Korhonen", "M. Salo", "H. Mattila"},
    project_chaotic={"V. Jokinen", "T. Rinne"},
    project_customers={
        "maintenance":  ["Internal — Production", "Internal — Site Helsinki", "Wärtsilä Oy", "Caverion Suomi"],
        "construction": ["NCC Suomi", "Lemminkäinen", "City of Tampere"],
        "rollout":      ["Internal — IT", "Internal — Logistics", "Telia Finland Oyj"],
        "audit":        ["Internal — Compliance", "Internal — Finance"],
        "rd":           ["Internal — R&D", "ABB Service", "Siemens Finland"],
    },
    manager_fit={
        ("M. Hakala", "maintenance"):  1.25,
        ("M. Hakala", "construction"): 1.20,
        ("M. Hakala", "rd"):           0.75,
        ("T. Virtanen", "maintenance"): 1.20,
        ("T. Virtanen", "rd"):          1.15,
        ("J. Lehtinen", "rollout"):     1.20,
        ("K. Mäkinen", "rollout"):      1.10,
    },
    descriptions={
        "production":   ["Bearings batch", "Hydraulic seals", "Pump replacement", "Drive belt set", "Filter cartridges", "Coupling elements", "Spare parts kit"],
        "capex":        ["Production line upgrade", "Robotics installation", "Industrial equipment", "Crane refurbishment"],
        "construction": ["Site mobilisation", "Earthworks subcontract", "Steel erection batch", "Concrete pour subcontract"],
        "electrical":   ["Cable supply batch", "Contactors and relays", "Terminal blocks", "Switchgear retrofit"],
        "maintenance":  ["HVAC quarterly service", "Plumbing repair", "Electrical inspection", "Equipment calibration", "Pump overhaul"],
        "security":     ["Door lock upgrade", "Access control system", "CCTV camera install"],
        "utilities":    ["Electricity Q1", "Electricity Q2", "Electricity Q3", "Electricity Q4", "District heating"],
        "fuel":         ["Fleet fuel top-up", "Diesel bulk delivery", "Fuel card refill"],
        "ppe":          ["Workwear set rental", "Safety boots batch", "Hi-vis vests", "Safety helmets"],
        "cleaning":     ["Cleaning chemicals", "Floor polish bulk", "Sanitation supplies"],
        "telecom":      ["Mobile subscriptions", "Internet service", "Site connectivity"],
        "office":       ["A4 paper supply", "Office stationery", "Printer toner"],
    },
    product_categories={
        "Spare Parts":          {"price": (15, 850), "hs": ["8484.10", "8482.10"], "units": ["ea", "set"], "acct": "4220"},
        "Electrical Components":{"price": (2, 180),  "hs": ["8547.90", "8536.50"], "units": ["ea", "m"],   "acct": "4225"},
        "PPE & Workwear":       {"price": (12, 220), "hs": ["6211.33", "6403.40"], "units": ["set", "pair"],"acct": "4810"},
        "Maintenance Services": {"price": (60, 145), "hs": [],                      "units": ["hr"],         "acct": "6120"},
        "Fleet & Fuel":         {"price": (45, 220), "hs": ["2710.12"],             "units": ["100L", "L"], "acct": "4310"},
    },
    product_name_templates={
        "Spare Parts":           ["Bearing", "V-Belt", "Pump Seal", "Filter Cartridge", "Coupling", "Drive Shaft"],
        "Electrical Components": ["Cable Gland", "Contactor", "Terminal Block", "Fuse Holder", "Relay 24V"],
        "PPE & Workwear":        ["Workwear Set", "Safety Boots", "Hi-Vis Vest", "Safety Helmet"],
        "Maintenance Services":  ["Electrical Inspection", "Plumbing Service", "Equipment Calibration", "HVAC Tuning"],
        "Fleet & Fuel":          ["Diesel B7", "AdBlue", "Engine Oil"],
    },
)


# ── Aurora Retail Oy — multi-channel retail ─────────────────────────


AURORA = PersonaSpec(
    tenant_id="aurora",
    name="Aurora Retail Oy",
    suppliers=[
        SupplierSpec("Valio Oy",              "Warehouse-Vantaa", "4010", "M. Eronen", "groceries",  60, (2200, 12000)),
        SupplierSpec("HKScan Finland",        "Warehouse-Vantaa", "4010", "M. Eronen", "groceries",  40, (1800, 9500)),
        SupplierSpec("Atria Oyj",             "Warehouse-Vantaa", "4010", "M. Eronen", "groceries",  45, (1500, 8500)),
        SupplierSpec("Fazer Konfektyr",       "Warehouse-Vantaa", "4015", "M. Eronen", "groceries",  35, (1200, 7000)),
        SupplierSpec("Paulig Group",          "Warehouse-Vantaa", "4015", "M. Eronen", "groceries",  30, (900, 5500)),
        SupplierSpec("Marimekko",             "Store-Helsinki",   "4030", "A. Niemi",  "fashion",    18, (3500, 22000)),
        SupplierSpec("Nokian Tyres Retail",   "Store-Tampere",    "4040", "A. Niemi",  "automotive", 12, (4000, 25000)),
        SupplierSpec("Tikkurila",             "Store-Helsinki",   "4050", "A. Niemi",  "household",  20, (1200, 8500)),
        SupplierSpec("Iittala",               "Store-Helsinki",   "4032", "A. Niemi",  "homeware",   14, (2500, 14000)),
        SupplierSpec("Fiskars",               "Store-Tampere",    "4032", "A. Niemi",  "homeware",   10, (1500, 9500)),
        SupplierSpec("Berner Beauty",         "Store-Helsinki",   "4035", "A. Niemi",  "beauty",     22, (800, 4500)),
        SupplierSpec("L'Oréal Finland",       "Store-Helsinki",   "4035", "A. Niemi",  "beauty",     18, (2000, 12000)),
        SupplierSpec("Verkkokauppa.com",      "E-com",            "4520", "R. Salonen","electronics",16, (4500, 18000)),
        SupplierSpec("Elektroskandia",        "Warehouse-Vantaa", "4520", "R. Salonen","electronics",10, (2500, 16000)),
        SupplierSpec("Telia Finland Oyj",     "HQ",               "5510", "R. Salonen","telecom",     6, (300, 1500)),
        SupplierSpec("Posti",                 "Logistics",        "4310", "R. Salonen","logistics",  35, (4000, 18000), late_factor=1.4),
        SupplierSpec("DB Schenker",           "Logistics",        "4315", "R. Salonen","logistics",  18, (3500, 14000)),
        SupplierSpec("Fortum",                "Store-Helsinki",   "6110", "M. Eronen", "utilities",  12, (2200, 9500)),
        SupplierSpec("Berner Oy",             "Store-Tampere",    "4110", "M. Eronen", "cleaning",    8, (200, 1500)),
        SupplierSpec("Lyreco",                "HQ",               "6810", "R. Salonen","office",      8, (50, 800)),
        SupplierSpec("Adobe Systems",         "Marketing",        "5540", "R. Salonen","software",    6, (2500, 12000)),
        SupplierSpec("Bauhaus",               "Store-Oulu",       "4060", "A. Niemi",  "diy",        16, (1500, 9500)),
    ],
    cost_centres=[
        "Store-Helsinki", "Store-Tampere", "Store-Oulu", "Warehouse-Vantaa",
        "E-com", "Logistics", "Marketing", "HQ",
    ],
    approvers={"manager_default": "M. Eronen", "cfo": "K. Salonen-CFO", "board": "K. Salonen-CFO"},
    projects_pool=[
        "OPEX-RETAIL-2024", "OPEX-RETAIL-2025", "STORE-FITOUT-2025",
        "ECOM-PLATFORM", "MARKETING-CAMPAIGN-Q1", "MARKETING-CAMPAIGN-Q4",
        "WAREHOUSE-AUTOMATION", "POS-REFRESH",
    ],
    n_products=3200,          # rich SKU catalog — drives Catalog / Pricing / Demand / Inventory
    n_orders=18000,
    n_price_history=6500,
    # Smaller project tier — retail does fewer formal projects than maintenance.
    n_completed_projects=70,
    n_active_projects=22,
    project_types={
        "store-fitout":   {"budget": (40000, 200000),"duration": (30, 90),  "team": (3, 7), "weight": 40},
        "ecom-launch":    {"budget": (60000, 300000),"duration": (60, 180), "team": (4, 9), "weight": 25},
        "marketing-camp": {"budget": (15000, 90000), "duration": (15, 60),  "team": (2, 5), "weight": 25},
        "audit":          {"budget": (4000, 20000),  "duration": (5, 20),   "team": (1, 3), "weight": 10},
    },
    project_managers=["M. Eronen", "A. Niemi", "R. Salonen"],
    project_leads={
        "store-fitout":   ["L. Aho", "P. Korhonen"],
        "ecom-launch":    ["A. Lindgren", "K. Saari"],
        "marketing-camp": ["S. Niemi", "M. Salo"],
        "audit":          ["H. Mattila"],
    },
    project_team_pool=[
        "A. Lindgren", "K. Saari", "L. Aho", "P. Korhonen", "S. Niemi",
        "M. Salo", "H. Mattila", "V. Jokinen", "T. Rinne",
        "O. Halonen", "N. Forsberg",
    ],
    project_reliable={"A. Lindgren", "K. Saari", "P. Korhonen", "M. Salo", "H. Mattila"},
    project_chaotic={"V. Jokinen", "T. Rinne"},
    project_customers={
        "store-fitout":   ["Internal — Store Helsinki", "Internal — Store Tampere", "Internal — Store Oulu"],
        "ecom-launch":    ["Internal — E-com"],
        "marketing-camp": ["Internal — Marketing"],
        "audit":          ["Internal — Finance"],
    },
    manager_fit={
        ("M. Eronen", "store-fitout"):  1.20,
        ("A. Niemi",  "store-fitout"):  1.10,
        ("R. Salonen","ecom-launch"):   1.30,
        ("R. Salonen","marketing-camp"):0.95,
    },
    descriptions={
        "groceries":  ["Weekly delivery — dairy", "Weekly delivery — meat", "Weekly delivery — produce", "Confectionery batch", "Coffee batch"],
        "fashion":    ["SS25 collection drop", "AW24 restock", "Limited capsule batch"],
        "automotive": ["Tyre stock — winter", "Tyre stock — summer"],
        "household":  ["Paint batch — interior", "Paint batch — exterior", "Cleaning chemicals"],
        "homeware":   ["Glassware restock", "Kitchenware restock", "Decor SS25"],
        "beauty":     ["Skincare restock", "Cosmetics restock", "Premium fragrance"],
        "electronics":["TV restock", "Mobile accessories", "Computing peripherals"],
        "telecom":    ["Mobile subscriptions", "Store internet"],
        "logistics":  ["Pallet shipping", "Last-mile delivery", "Returns handling"],
        "utilities":  ["Electricity Q1", "Electricity Q2", "Electricity Q3", "Electricity Q4", "District heating"],
        "cleaning":   ["Cleaning chemicals", "Floor polish bulk"],
        "office":     ["Office supplies", "Printer toner"],
        "software":   ["Adobe CC licenses", "Marketing tools"],
        "diy":        ["Hardware restock", "Tools batch"],
    },
    product_categories={
        "Groceries":      {"price": (1, 25),    "hs": ["0401.20", "1601.00"], "units": ["ea", "kg"],  "acct": "4010"},
        "Fashion":        {"price": (29, 350),  "hs": ["6109.10", "6204.42"], "units": ["ea"],         "acct": "4030"},
        "Homeware":       {"price": (8, 180),   "hs": ["7013.41", "7323.93"], "units": ["ea", "set"], "acct": "4032"},
        "Beauty":         {"price": (5, 120),   "hs": ["3304.99", "3303.00"], "units": ["ea"],         "acct": "4035"},
        "Electronics":    {"price": (45, 1500), "hs": ["8528.72", "8517.13"], "units": ["ea"],         "acct": "4520"},
        "Household":      {"price": (3, 95),    "hs": ["3402.20", "3924.10"], "units": ["L", "kg"],   "acct": "4050"},
        "DIY":            {"price": (5, 280),   "hs": ["8205.40", "3208.10"], "units": ["ea", "set"], "acct": "4060"},
    },
    product_name_templates={
        "Groceries":   ["Milk 1L", "Yogurt", "Cheese 250g", "Bread", "Butter 200g", "Coffee 500g", "Sausage", "Apple Juice"],
        "Fashion":     ["T-shirt", "Sweater", "Jacket", "Trousers", "Dress", "Scarf", "Tote Bag"],
        "Homeware":    ["Glass Set", "Plate Set", "Vase", "Cushion", "Throw", "Candle", "Bowl"],
        "Beauty":      ["Moisturiser", "Lipstick", "Mascara", "Shampoo", "Body Lotion", "Eau de Toilette"],
        "Electronics": ["TV 55\"", "Smartphone", "Wireless Earbuds", "Tablet", "Laptop", "Smart Speaker"],
        "Household":   ["Multi-Surface Cleaner", "Dishwasher Tablets", "Laundry Detergent", "Storage Box"],
        "DIY":         ["Drill Bit Set", "Paint Roller", "Tape Measure", "Wrench Set"],
    },
)


# ── Helsinki Studio — professional services ─────────────────────────


STUDIO = PersonaSpec(
    tenant_id="studio",
    name="Helsinki Studio",
    suppliers=[
        # Frequencies bumped ~2× from the original — services firms
        # have many small, recurring SaaS / subscription line items.
        SupplierSpec("Adobe Systems",         "Design",      "5530", "A. Lahti",   "software",   18, (800, 4500)),
        SupplierSpec("Microsoft Ireland",     "Engineering", "5510", "J. Mäkelä",  "software",   24, (1200, 9500)),
        SupplierSpec("Amazon Web Services",   "Engineering", "5512", "J. Mäkelä",  "software",   28, (3500, 28000)),
        SupplierSpec("Google Cloud",          "Engineering", "5512", "J. Mäkelä",  "software",   16, (2500, 22000)),
        SupplierSpec("Slack Technologies",    "HQ",          "5520", "K. Saarinen","software",   10, (1000, 4000)),
        SupplierSpec("Notion Labs",           "HQ",          "5520", "K. Saarinen","software",    8, (400, 2400)),
        SupplierSpec("Figma Inc.",            "Design",      "5530", "A. Lahti",   "software",   10, (600, 3500)),
        SupplierSpec("Linear App",            "Engineering", "5520", "J. Mäkelä",  "software",    7, (400, 2200)),
        SupplierSpec("RecruitFinland",        "HR",          "5750", "K. Saarinen","recruitment",10, (3500, 18000)),
        SupplierSpec("Severa",                "HQ",          "5520", "K. Saarinen","software",    8, (1200, 4800)),
        SupplierSpec("Eficode Training",      "HR",          "5755", "K. Saarinen","training",   12, (1800, 8500)),
        SupplierSpec("Aalto Pro",             "HR",          "5755", "K. Saarinen","training",    8, (2500, 12000)),
        SupplierSpec("Accountor",             "Admin",       "7100", "K. Saarinen","consulting",  9, (1500, 7500)),
        SupplierSpec("Telia Finland Oyj",     "HQ",          "5511", "K. Saarinen","telecom",    16, (300, 1500)),
        SupplierSpec("Lyreco",                "HQ",          "6810", "K. Saarinen","office",     14, (50, 800)),
        SupplierSpec("Berner Beauty",         "HQ",          "4110", "K. Saarinen","cleaning",    8, (150, 1200)),
        SupplierSpec("Fazer Food Services",   "HR",          "5710", "K. Saarinen","catering",   28, (300, 2200)),
        SupplierSpec("Kespro",                "HR",          "5710", "K. Saarinen","catering",   16, (200, 1800)),
        SupplierSpec("Paulig Group",          "HR",          "5710", "K. Saarinen","catering",   12, (200, 1500)),
        SupplierSpec("Stockmann Business",    "HR",          "5760", "K. Saarinen","gifts",       7, (500, 4500)),
        SupplierSpec("LinkedIn Talent",       "HR",          "5750", "K. Saarinen","recruitment", 9, (1500, 12000)),
    ],
    cost_centres=[
        "Design", "Engineering", "Strategy", "Sales", "HR", "Admin", "HQ",
    ],
    approvers={"manager_default": "K. Saarinen", "cfo": "P. Tikkanen-CFO", "board": "P. Tikkanen-CFO"},
    projects_pool=[
        "ENG-2024", "ENG-2025", "DESIGN-2025", "STRATEGY-2025",
        "INT-OFFICE", "INT-IT-OPS", "INT-RECRUIT",
    ],
    n_products=240,           # software licences + small office stock
    n_orders=900,
    n_price_history=700,
    # Project-heavy persona — billable client engagements.
    n_completed_projects=340,
    n_active_projects=95,
    project_types={
        "design":         {"budget": (8000, 80000),  "duration": (15, 90),  "team": (2, 5),  "weight": 30},
        "implementation": {"budget": (30000, 200000),"duration": (45, 180), "team": (4, 9),  "weight": 25},
        "strategy":       {"budget": (15000, 90000), "duration": (20, 60),  "team": (2, 4),  "weight": 20},
        "discovery":      {"budget": (4000, 20000),  "duration": (5, 25),   "team": (1, 3),  "weight": 15},
        "retainer":       {"budget": (12000, 60000), "duration": (90, 365), "team": (1, 3),  "weight": 10},
    },
    project_managers=["A. Lahti", "J. Mäkelä", "K. Saarinen", "L. Lounela"],
    project_leads={
        "design":         ["A. Lindgren", "K. Saari", "S. Niemi"],
        "implementation": ["J. Mäkelä", "M. Salo", "L. Aho"],
        "strategy":       ["L. Lounela", "H. Mattila"],
        "discovery":      ["H. Mattila", "K. Saari"],
        "retainer":       ["A. Lindgren", "M. Salo"],
    },
    project_team_pool=[
        "A. Lindgren", "K. Saari", "L. Aho", "P. Korhonen", "S. Niemi",
        "M. Salo", "E. Heikkinen", "H. Mattila", "V. Jokinen", "T. Rinne",
        "O. Halonen", "I. Pulkkinen", "N. Forsberg", "J. Karjalainen",
        "L. Lounela",
    ],
    project_reliable={"A. Lindgren", "K. Saari", "P. Korhonen", "M. Salo", "H. Mattila"},
    project_chaotic={"V. Jokinen", "T. Rinne"},
    project_customers={
        "design":         ["Wolt Enterprises", "Reaktor", "Nordea Brand", "Marimekko"],
        "implementation": ["Telia Finland", "Posti Group", "Fortum", "S-Group"],
        "strategy":       ["Sanoma Media", "Stora Enso", "Internal — Strategy"],
        "discovery":      ["Sanoma Media", "Wärtsilä", "Internal — R&D"],
        "retainer":       ["Telia Finland", "Marimekko", "Wolt Enterprises"],
    },
    manager_fit={
        ("A. Lahti",    "design"):         1.30,
        ("A. Lahti",    "implementation"): 0.85,
        ("J. Mäkelä",   "implementation"): 1.30,
        ("J. Mäkelä",   "discovery"):      1.10,
        ("K. Saarinen", "retainer"):       1.20,
        ("L. Lounela",  "strategy"):       1.30,
    },
    descriptions={
        "software":    ["Adobe CC team licenses", "Microsoft 365 seats", "AWS monthly bill", "GCP monthly bill", "Figma seats", "Notion enterprise"],
        "recruitment": ["Senior engineer placement", "Designer placement", "Sales hire"],
        "training":    ["Engineering bootcamp", "Design course batch", "Leadership workshop"],
        "consulting":  ["Bookkeeping monthly", "Tax advisory", "HR consulting"],
        "telecom":     ["Mobile subscriptions", "Office internet"],
        "office":      ["Office supplies", "Printer toner", "Stationery"],
        "cleaning":    ["Office cleaning monthly"],
        "catering":    ["Office coffee supply", "Lunch catering", "Event catering"],
        "gifts":       ["Client gifts batch", "Holiday gifts"],
    },
    product_categories={
        "Software Licenses":  {"price": (8, 240),   "hs": [],            "units": ["seat", "yr"], "acct": "5520"},
        "Office Supplies":    {"price": (3, 85),    "hs": ["4820.10"],   "units": ["ea", "pack"],"acct": "6810"},
        "Catering":           {"price": (5, 65),    "hs": ["1806.90"],   "units": ["pack", "box"],"acct": "5710"},
    },
    product_name_templates={
        "Software Licenses":  ["Adobe CC Seat", "Microsoft 365 Seat", "Figma Editor Seat", "Notion Enterprise Seat", "Slack Enterprise Seat"],
        "Office Supplies":    ["A4 Copy Paper", "Pens Pack", "Folders", "Whiteboard Markers"],
        "Catering":           ["Coffee Beans", "Tea Bags", "Sugar Sachets"],
    },
)


PERSONAS = [METSA, AURORA, STUDIO]


# ── Generation ──────────────────────────────────────────────────────


def routed_by(_amount: float, _category: str) -> str:
    r = random.random()
    if r < 0.21:
        return "rule"
    if r < 0.72:
        return "aito_high"
    if r < 0.82:
        return "aito_reviewed"
    return "manual"


def approval_level(amount: float, category: str) -> str:
    if amount > 20000 and category in {"capex", "construction", "ecom-launch"}:
        return "board"
    if amount > 5000:
        return "cfo" if random.random() < 0.55 else "manager"
    return "manager"


def approver_for(supplier: SupplierSpec, level: str, persona: PersonaSpec) -> str:
    if level in {"cfo", "board"}:
        return persona.approvers["cfo"]
    return supplier.approver


def generate_purchases(persona: PersonaSpec) -> list[dict]:
    purchases: list[dict] = []
    counter = 1000
    base_late = 0.05
    for month in MONTHS:
        for supplier in persona.suppliers:
            n_this = max(1, int(round(supplier.freq / 4 * random.uniform(0.7, 1.3))))
            for _ in range(n_this):
                counter += 1
                cat = supplier.category
                desc = random.choice(persona.descriptions.get(cat, ["Generic purchase"]))
                lo, hi = supplier.amount
                amount = round(random.uniform(lo, hi), 2)

                # 6–7% noise so confidence isn't pegged at 1.0.
                cc = (random.choice(persona.cost_centres)
                      if random.random() < 0.07 else supplier.cc)
                acct = (random.choice([s.acct for s in persona.suppliers])
                        if random.random() < 0.06 else supplier.acct)

                level = approval_level(amount, cat)
                late = random.random() < min(0.5, base_late * supplier.late_factor)

                purchases.append({
                    "purchase_id": f"PO-{counter}",
                    "supplier": supplier.name,
                    "description": desc,
                    "category": cat,
                    "amount_eur": amount,
                    "cost_center": cc,
                    "account_code": acct,
                    "approver": approver_for(supplier, level, persona),
                    "approval_level": level,
                    "delivery_late": late,
                    "order_month": month,
                    "project": random.choice(persona.projects_pool),
                    "routed_by": routed_by(amount, cat),
                })
    return purchases


def generate_products(persona: PersonaSpec) -> list[dict]:
    if not persona.product_categories:
        return []
    products: list[dict] = []
    counter = 1000
    while len(products) < persona.n_products:
        counter += 1
        sku = f"SKU-{counter}"
        cat = random.choice(list(persona.product_categories.keys()))
        spec = persona.product_categories[cat]
        templates = persona.product_name_templates.get(cat, ["Item"])
        name = random.choice(templates)
        suffix = random.choice(["", " v2", " HD", " Pro", " 10pk", " #" + str(random.randint(100, 999))])

        # 5% incomplete — drives the Catalog Intelligence demo.
        incomplete = random.random() < 0.05
        droppable = ["category", "unit_price", "hs_code", "unit_of_measure",
                     "weight_kg", "account_code", "tax_class"]
        dropped = set(random.sample(droppable, random.randint(2, 4))) if incomplete else set()

        # Pick a supplier that touches this category roughly.
        sup_candidates = [s.name for s in persona.suppliers
                          if s.category in (cat.lower(), "office") or random.random() < 0.06]
        supplier = random.choice(sup_candidates) if sup_candidates else random.choice([s.name for s in persona.suppliers])

        products.append({
            "sku": sku,
            "name": name + suffix,
            "supplier": supplier if "supplier" not in dropped else None,
            "category": cat if "category" not in dropped else None,
            "unit_price": round(random.uniform(*spec["price"]), 2) if "unit_price" not in dropped else None,
            "hs_code": (random.choice(spec["hs"]) if spec["hs"] else None) if "hs_code" not in dropped else None,
            "unit_of_measure": random.choice(spec["units"]) if "unit_of_measure" not in dropped else None,
            "weight_kg": round(random.uniform(0.05, 8.0), 2) if "weight_kg" not in dropped and cat != "Maintenance Services" else None,
            "account_code": spec["acct"] if "account_code" not in dropped else None,
            "tax_class": "Standard 25.5%" if "tax_class" not in dropped else None,
        })
    return products


def generate_orders(persona: PersonaSpec, products: list[dict]) -> list[dict]:
    orders: list[dict] = []
    if not products:
        return orders
    counter = 0
    eligible = [p["sku"] for p in products if p.get("category")]
    if not eligible:
        return orders
    target = persona.n_orders
    while len(orders) < target:
        sku = random.choice(eligible)
        for month in MONTHS:
            if random.random() < 0.65:
                counter += 1
                orders.append({
                    "order_id": f"ORD-{counter:05d}",
                    "product_id": sku,
                    "month": month,
                    "units_sold": random.randint(1, 35),
                })
            if len(orders) >= target:
                break
    return orders


def generate_price_history(persona: PersonaSpec, products: list[dict]) -> list[dict]:
    if not products:
        return []
    rows: list[dict] = []
    counter = 0
    suppliers = [s.name for s in persona.suppliers]
    eligible = [p for p in products if p.get("unit_price") is not None][:300]
    while len(rows) < persona.n_price_history and eligible:
        prod = random.choice(eligible)
        base = prod["unit_price"]
        # Most prices cluster around base; ~5% are outliers.
        if random.random() < 0.05:
            price = base * random.uniform(1.20, 1.45)
        else:
            price = max(0.5, random.gauss(base, base * 0.08))
        counter += 1
        rows.append({
            "price_id": f"PH-{counter:05d}",
            "product_id": prod["sku"],
            "supplier": prod.get("supplier") or random.choice(suppliers),
            "unit_price": round(price, 2),
            "volume": random.choice([1, 5, 10, 25, 50, 100]),
            "order_date": f"{random.choice(MONTHS)}-{random.randint(1, 28):02d}",
        })
    return rows


def _project_success_p(
    persona: PersonaSpec,
    ptype: str,
    manager: str,
    team_size: int,
    members: list[str],
    budget: float,
    duration: int,
    priority: str,
) -> float:
    """Engineered probability used to decide outcome — mirrors the
    booktest invariants (manager fit, reliable boost, chaotic drag,
    budget × duration risk)."""
    p = 0.65
    p *= persona.manager_fit.get((manager, ptype), 1.0)
    spec = persona.project_types[ptype]
    lo, hi = spec["team"]
    if team_size < lo:
        p *= 0.7
    elif team_size > hi:
        p *= 0.85
    else:
        p *= 1.10
    p *= 1.0 + 0.08 * sum(1 for m in members if m in persona.project_reliable)
    p *= 1.0 - 0.18 * sum(1 for m in members if m in persona.project_chaotic)
    if budget / max(duration, 1) > 2500:
        p *= 0.80
    if priority == "high":
        p *= 0.95
    return max(0.05, min(0.97, p))


def generate_projects_and_assignments(persona: PersonaSpec) -> tuple[list[dict], list[dict]]:
    projects: list[dict] = []
    assignments: list[dict] = []
    types = list(persona.project_types.keys())
    weights = [persona.project_types[t]["weight"] for t in types]

    def make_one(idx: int, completed: bool) -> None:
        ptype = random.choices(types, weights=weights, k=1)[0]
        spec = persona.project_types[ptype]
        manager = random.choice(persona.project_managers)
        lead = random.choice(persona.project_leads[ptype])
        team_size = random.randint(*spec["team"])
        pool = [p for p in persona.project_team_pool if p != lead]
        members = random.sample(pool, k=min(team_size, len(pool)))
        budget = round(random.uniform(*spec["budget"]), -2)
        duration = random.randint(*spec["duration"])
        priority = random.choices(["low", "medium", "high"], weights=[25, 50, 25], k=1)[0]
        customer = random.choice(persona.project_customers[ptype])
        start_month = random.choice(MONTHS)

        p_succ = _project_success_p(
            persona, ptype, manager, team_size, members, budget, duration, priority,
        )

        if completed:
            success = random.random() < p_succ
            on_time = success or (random.random() < 0.35)
            on_budget = success or (random.random() < 0.30)
            if not success and on_time and on_budget:
                if random.random() < 0.5:
                    on_time = False
                else:
                    on_budget = False
            status = "complete"
        else:
            success = on_time = on_budget = None
            status = random.choices(["active", "at_risk", "delayed"], weights=[60, 25, 15], k=1)[0]

        pid = f"PRJ-{1000 + idx}"
        all_people = [lead] + members
        projects.append({
            "project_id": pid,
            "name": f"{ptype.capitalize()} — {customer.split('—')[-1].strip()} #{idx}",
            "project_type": ptype,
            "customer": customer,
            "manager": manager,
            "team_lead": lead,
            "team_size": team_size,
            "team_members": " ".join(all_people),
            "budget_eur": budget,
            "duration_days": duration,
            "priority": priority,
            "status": status,
            "start_month": start_month,
            "on_time": on_time,
            "on_budget": on_budget,
            "success": success,
        })
        for i, person in enumerate(all_people):
            role = "lead" if i == 0 else ("senior" if person in persona.project_reliable else "engineer")
            allocation = random.choice([60, 80, 100]) if i == 0 else random.choice([20, 25, 40, 50, 75, 100])
            # `project_type` is denormalised onto the assignment so
            # `_predict` queries can filter by it without needing a
            # cross-table join. Production ERPs typically do the same
            # for query performance on timesheet/assignment tables.
            assignments.append({
                "assignment_id": f"ASG-{pid}-{i:02d}",
                "project_id": pid,
                "person": person,
                "role": role,
                "allocation_pct": allocation,
                "project_type": ptype,
                "project_success": success,  # nullable mirror of projects.success
            })

    for i in range(persona.n_completed_projects):
        make_one(i, completed=True)
    for i in range(persona.n_active_projects):
        make_one(persona.n_completed_projects + i, completed=False)
    random.shuffle(projects)
    return projects, assignments


# ── Driver ──────────────────────────────────────────────────────────


def write_persona(persona: PersonaSpec) -> None:
    out = DATA / persona.tenant_id
    out.mkdir(parents=True, exist_ok=True)
    # Reseed per-persona so each universe is independently deterministic.
    random.seed(hash(persona.tenant_id) & 0xFFFFFFFF)

    purchases = generate_purchases(persona)
    products = generate_products(persona)
    orders = generate_orders(persona, products)
    prices = generate_price_history(persona, products)
    projects, assignments = generate_projects_and_assignments(persona)

    with open(out / "purchases.json",     "w") as f: json.dump(purchases,    f, indent=2, ensure_ascii=False)
    with open(out / "products.json",      "w") as f: json.dump(products,     f, indent=2, ensure_ascii=False)
    with open(out / "orders.json",        "w") as f: json.dump(orders,       f, indent=2, ensure_ascii=False)
    with open(out / "price_history.json", "w") as f: json.dump(prices,       f, indent=2, ensure_ascii=False)
    with open(out / "projects.json",      "w") as f: json.dump(projects,     f, indent=2, ensure_ascii=False)
    with open(out / "assignments.json",   "w") as f: json.dump(assignments,  f, indent=2, ensure_ascii=False)

    completed = [p for p in projects if p["status"] == "complete"]
    succ = [p for p in completed if p["success"]]
    print(f"\n[{persona.tenant_id}] {persona.name}")
    print(f"  purchases:      {len(purchases)}")
    print(f"  products:       {len(products)}")
    print(f"  orders:         {len(orders)}")
    print(f"  price_history:  {len(prices)}")
    print(f"  projects:       {len(projects)} ({len(completed)} complete, "
          f"{len(projects)-len(completed)} active)")
    if completed:
        print(f"    success rate: {len(succ)}/{len(completed)} = "
              f"{len(succ)/len(completed):.0%}")
    print(f"  assignments:    {len(assignments)}")


def main() -> None:
    print("Generating per-tenant fixtures...")
    for persona in PERSONAS:
        write_persona(persona)
    print("\nDone. Load into Aito with: ./do load-data --tenant=all")


if __name__ == "__main__":
    main()

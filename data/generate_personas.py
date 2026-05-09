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

    # Map product category → set of supplier categories that fit. Lets
    # suppliers be picked sensibly without having to align every name
    # downstream. Categories not in the map fall through to "any
    # supplier" — currently fine for the three personas because each
    # one's product categories are covered by one of these keys.
    PRODUCT_CAT_TO_SUPPLIER_CATS: dict[str, set[str]] = {
        # Metsä product categories
        "spare parts":           {"production", "electrical"},
        "electrical components": {"electrical", "production"},
        "ppe & workwear":        {"ppe"},
        "maintenance services":  {"maintenance", "production"},
        "fleet & fuel":          {"fuel"},
        # Aurora product categories
        "groceries":             {"groceries"},
        "fashion":               {"fashion"},
        "homeware":              {"household", "fashion"},
        "beauty":                {"beauty", "cleaning"},
        "electronics":           {"electronics"},
        "household":             {"household", "cleaning"},
        "diy":                   {"diy", "household"},
        # Studio product categories
        "software licenses":     {"software"},
        "office supplies":       {"office"},
        "catering":              {"catering"},
    }

    # Suffix policy by category. SaaS/services/groceries shouldn't get
    # physical-quality suffixes ("HD", "Pro", "v2") — they're meaningless
    # on a Notion seat, a yoghurt 4-pack, or "Milk 1L HD". Each
    # category gets its own pool; physical-tooling categories keep
    # the variety suffixes for sample-size diversity.
    SUFFIX_POOL: dict[str, list[str]] = {
        "software licenses":   ["", " (monthly)", " (annual)", " — Team"],
        "maintenance services":["", " (hr)", " — site visit"],
        "catering":            ["", " (office pack)", " — barista grade"],
        "groceries":           ["", " 4-pack", " 6-pack", " (family pack)"],
        "beauty":              ["", " 50ml", " 100ml", " 250ml"],
    }
    DEFAULT_SUFFIXES = ["", " v2", " HD", " Pro", " 10pk"]

    while len(products) < persona.n_products:
        counter += 1
        sku = f"SKU-{counter}"
        cat = random.choice(list(persona.product_categories.keys()))
        spec = persona.product_categories[cat]
        templates = persona.product_name_templates.get(cat, ["Item"])
        name = random.choice(templates)

        suffix_pool = SUFFIX_POOL.get(cat.lower(), DEFAULT_SUFFIXES)
        suffix = random.choice(suffix_pool)
        # Add a random "#NNN" code on the unsuffixed default-pool path
        # ~10% of the time — gives the same realistic-SKU-name texture
        # the original generator had without making it the only option.
        if suffix == "" and suffix_pool is DEFAULT_SUFFIXES and random.random() < 0.10:
            suffix = " #" + str(random.randint(100, 999))

        # 5% incomplete — drives the Catalog Intelligence demo.
        incomplete = random.random() < 0.05
        droppable = ["category", "unit_price", "hs_code", "unit_of_measure",
                     "weight_kg", "account_code", "tax_class"]
        dropped = set(random.sample(droppable, random.randint(2, 4))) if incomplete else set()

        # Pick a supplier whose category fits this product category.
        # Falls back to any office/general supplier if no category
        # match (rare — only happens if the persona ships a product
        # category not in PRODUCT_CAT_TO_SUPPLIER_CATS).
        wanted_supplier_cats = PRODUCT_CAT_TO_SUPPLIER_CATS.get(cat.lower(), set())
        if wanted_supplier_cats:
            sup_candidates = [s.name for s in persona.suppliers
                              if s.category in wanted_supplier_cats]
        else:
            sup_candidates = []
        if not sup_candidates:
            # 8% of the time even with a clean category match, fall
            # through to a generic supplier — that messy-real-world
            # signal is what Catalog Intelligence learns from.
            sup_candidates = [s.name for s in persona.suppliers
                              if s.category == "office"] \
                             or [s.name for s in persona.suppliers]
        supplier = random.choice(sup_candidates)

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


def generate_impressions(persona: PersonaSpec, products: list[dict]) -> list[dict]:
    """Synthetic browsing/cart impressions — only Aurora gets these.

    Each session walks 3–6 products. The first impression has no prev;
    subsequent impressions carry the previous product as `prev_product_id`.
    `clicked` and `purchased` probabilities are weighted so:

      - same-category prev→next clicks more often (the cross-sell signal
        Aito will discover via `_recommend goal: {clicked: true}`)
      - certain category pairs (Fashion→Beauty, DIY→Homeware,
        Groceries→Household) cross-cluster — engineered so the demo
        can show non-obvious cross-sell hits across departments
      - segments shape category bias: 'young-urban' favours
        Fashion + Beauty + Electronics; 'family' favours Groceries +
        Household + Homeware; 'professional' favours Electronics + DIY.

    This is the impressions pattern from accounting-demo guide 07 —
    the *same* operator that drives help-article CTR ranking drives
    product cross-sell. No new model, just the right where + goal.
    """
    if persona.tenant_id != "aurora":
        return []
    eligible = [p for p in products if p.get("category")]
    if not eligible:
        return []
    by_cat: dict[str, list[dict]] = {}
    for p in eligible:
        by_cat.setdefault(p["category"], []).append(p)

    # Engineered cross-category affinities. Same category is implicit
    # (high baseline); these add lift for non-obvious pairs.
    cross_category_pull = {
        ("Fashion", "Beauty"): 1.6,
        ("Beauty", "Fashion"): 1.4,
        ("DIY", "Homeware"): 1.5,
        ("Homeware", "DIY"): 1.3,
        ("Groceries", "Household"): 1.7,
        ("Household", "Groceries"): 1.5,
        ("Electronics", "Homeware"): 1.2,
    }
    segment_bias = {
        "young-urban": {"Fashion": 1.4, "Beauty": 1.5, "Electronics": 1.3},
        "family":      {"Groceries": 1.5, "Household": 1.4, "Homeware": 1.3},
        "professional": {"Electronics": 1.4, "DIY": 1.3, "Homeware": 1.1},
    }
    segments = list(segment_bias.keys())

    rows: list[dict] = []
    counter = 0
    n_sessions = 1500   # 1500 sessions × ~4 imp = ~6000 rows
    for _ in range(n_sessions):
        session_id = f"S-{counter // 4:05d}"
        segment = random.choice(segments)
        bias = segment_bias[segment]
        month = random.choice(MONTHS[-12:])     # last 12 months only

        # Walk the session with a "current category" that drifts.
        first = random.choice(eligible)
        current = first
        prev_id: str | None = None
        steps = random.randint(3, 6)
        for _step in range(steps):
            counter += 1
            cur_cat = current["category"]
            # Pick the next product:
            # 70% same category, 25% biased neighbour, 5% random
            roll = random.random()
            if roll < 0.7:
                next_p = random.choice(by_cat[cur_cat])
            elif roll < 0.95:
                # Biased neighbour: weight by cross-category affinity.
                weights = []
                cats = list(by_cat.keys())
                for c in cats:
                    w = cross_category_pull.get((cur_cat, c), 0.4)
                    w *= bias.get(c, 1.0)
                    weights.append(w)
                next_cat = random.choices(cats, weights=weights, k=1)[0]
                next_p = random.choice(by_cat[next_cat])
            else:
                next_p = random.choice(eligible)

            # Click probability: category match + segment bias + price
            same_cat = next_p["category"] == cur_cat
            cross_pull = cross_category_pull.get(
                (cur_cat, next_p["category"]), 1.0
            )
            seg_pull = bias.get(next_p["category"], 1.0)
            base_click_p = 0.30
            if same_cat:
                base_click_p = 0.60
            click_p = min(0.92, base_click_p * cross_pull * seg_pull * 0.8)
            clicked = random.random() < click_p
            # Purchased ⇒ clicked. Of clicks, ~25% convert.
            purchased = clicked and random.random() < 0.25

            rows.append({
                "impression_id": f"IMP-{counter:06d}",
                "session_id": session_id,
                "customer_segment": segment,
                "product_id": next_p["sku"],
                "prev_product_id": prev_id,
                "clicked": clicked,
                "purchased": purchased,
                "month": month,
            })
            prev_id = next_p["sku"]
            current = next_p

    return rows


# ── Metsä tasks (Project Plan view) ─────────────────────────────────
#
# Only Metsä has a phased work-breakdown model (construction + heavy
# maintenance). Each project emits N task rows; outcome (success /
# on-time / on-budget) is driven by a hand-engineered signal so Aito's
# `_predict` and `_recommend` queries surface meaningful rankings:
#
#   - Per-(phase, subcontractor) reliability (Caverion strong on MEP,
#     drag on earthworks; NCC the opposite).
#   - Per-(subcontractor, region) affinity (Caverion's home is
#     Helsinki; Lemminkäinen leans Tampere; NCC has the Oulu site).
#   - Season effects (concrete pour drags in winter; steel erection
#     drags in winter too; MEP is season-neutral).
#   - Project-size effects (Lemminkäinen wants ≥€500k, drag below).
#
# Phases are listed in execution order; the generator picks tasks
# from each phase's pool (with some variance in inclusion + count) so
# the dataset has both 25-task construction projects and 4-task
# maintenance ones.


@dataclass
class TaskTemplate:
    """One canonical task within a phase. Drives both fixture rows and
    the generative project-plan demo (Aito proposes tasks by predicting
    `task_name` given `(project_type, phase)`)."""
    name: str
    days: tuple[int, int]
    cost: tuple[float, float]
    assignee_kind: str           # "subcontractor" | "employee"


# Task templates per (project_type, phase). Order within a list is
# execution order; the generator preserves it so plans look plausible.
METSA_TASK_TEMPLATES: dict[str, dict[str, list[TaskTemplate]]] = {
    "construction": {
        "site-prep": [
            TaskTemplate("Site survey", (2, 5), (1500, 4000), "employee"),
            TaskTemplate("Mobilisation", (3, 7), (4000, 12000), "subcontractor"),
            TaskTemplate("Temporary fencing & access", (1, 3), (2000, 6000), "subcontractor"),
        ],
        "earthworks": [
            TaskTemplate("Excavation", (5, 18), (15000, 60000), "subcontractor"),
            TaskTemplate("Grading & compaction", (3, 9), (6000, 22000), "subcontractor"),
            TaskTemplate("Drainage installation", (4, 10), (8000, 25000), "subcontractor"),
        ],
        "foundations": [
            TaskTemplate("Reinforcement layout", (3, 7), (5000, 14000), "subcontractor"),
            TaskTemplate("Concrete pour", (2, 6), (12000, 45000), "subcontractor"),
            TaskTemplate("Curing & strip", (4, 9), (3000, 8000), "subcontractor"),
        ],
        "structural": [
            TaskTemplate("Steel erection", (8, 20), (25000, 90000), "subcontractor"),
            TaskTemplate("Decking & secondary steel", (4, 10), (8000, 25000), "subcontractor"),
            TaskTemplate("Cladding", (6, 14), (12000, 38000), "subcontractor"),
        ],
        "mep": [
            TaskTemplate("HVAC rough-in", (6, 14), (15000, 45000), "subcontractor"),
            TaskTemplate("Electrical rough-in", (5, 12), (10000, 30000), "subcontractor"),
            TaskTemplate("Plumbing rough-in", (4, 10), (8000, 22000), "subcontractor"),
            TaskTemplate("Controls & BMS install", (5, 11), (12000, 32000), "subcontractor"),
        ],
        "finishing": [
            TaskTemplate("Interior partitioning", (5, 12), (8000, 22000), "subcontractor"),
            TaskTemplate("Floor finishes", (3, 8), (6000, 18000), "subcontractor"),
            TaskTemplate("Painting & coatings", (3, 7), (4000, 12000), "subcontractor"),
        ],
        "commissioning": [
            TaskTemplate("HVAC commissioning", (3, 7), (5000, 15000), "subcontractor"),
            TaskTemplate("Electrical commissioning", (2, 6), (4000, 12000), "subcontractor"),
            TaskTemplate("Final inspection walkthrough", (1, 3), (1500, 4000), "employee"),
        ],
        "handover": [
            TaskTemplate("Customer acceptance test", (1, 3), (1000, 3000), "employee"),
            TaskTemplate("Documentation handover", (1, 2), (800, 2000), "employee"),
        ],
    },
    "maintenance": {
        "planning": [
            TaskTemplate("Scope walkthrough", (1, 2), (500, 1500), "employee"),
        ],
        "inspection": [
            TaskTemplate("Equipment inspection", (1, 3), (800, 2500), "subcontractor"),
            TaskTemplate("Diagnostic report", (1, 2), (500, 1500), "subcontractor"),
        ],
        "procurement": [
            TaskTemplate("Spare parts ordering", (1, 4), (1500, 8000), "employee"),
        ],
        "repair": [
            TaskTemplate("Repair execution", (2, 8), (3000, 18000), "subcontractor"),
            TaskTemplate("Functional test", (1, 2), (500, 1500), "subcontractor"),
        ],
        "handover": [
            TaskTemplate("Sign-off & report", (1, 1), (300, 800), "employee"),
        ],
    },
    "rollout": {
        "design": [
            TaskTemplate("Solution design", (3, 8), (4000, 12000), "employee"),
        ],
        "procurement": [
            TaskTemplate("Equipment ordering", (2, 5), (2000, 8000), "employee"),
        ],
        "installation": [
            TaskTemplate("On-site installation", (3, 10), (6000, 22000), "subcontractor"),
            TaskTemplate("Configuration", (2, 5), (3000, 9000), "subcontractor"),
        ],
        "testing": [
            TaskTemplate("Acceptance testing", (2, 5), (2000, 6000), "employee"),
        ],
        "handover": [
            TaskTemplate("Training & sign-off", (1, 3), (1500, 4000), "employee"),
        ],
    },
    "audit": {
        "planning": [
            TaskTemplate("Audit scope", (1, 2), (500, 1500), "employee"),
        ],
        "fieldwork": [
            TaskTemplate("Site observation", (1, 4), (1500, 4500), "employee"),
            TaskTemplate("Evidence gathering", (1, 3), (1000, 3000), "employee"),
        ],
        "reporting": [
            TaskTemplate("Findings report", (1, 3), (1500, 4500), "employee"),
        ],
    },
    "rd": {
        "discovery": [
            TaskTemplate("Literature review", (3, 7), (3000, 9000), "employee"),
            TaskTemplate("Requirements draft", (2, 5), (2000, 6000), "employee"),
        ],
        "prototype": [
            TaskTemplate("Prototype build", (8, 20), (10000, 35000), "employee"),
        ],
        "validation": [
            TaskTemplate("Test plan", (2, 4), (2000, 5000), "employee"),
            TaskTemplate("Validation runs", (4, 10), (5000, 15000), "employee"),
        ],
        "documentation": [
            TaskTemplate("Final report", (3, 6), (3000, 8000), "employee"),
        ],
    },
}


# Engineered subcontractor reliability per phase. Keys are phase names
# from METSA_TASK_TEMPLATES. Values are {subcontractor: base_success}.
# Subcontractors not listed for a phase are *capable but not specialist*
# — they get a penalty (see _task_success_p).
METSA_SUBCONTRACTOR_FIT: dict[str, dict[str, float]] = {
    "site-prep":     {"NCC Suomi": 0.88, "Lemminkäinen": 0.84, "Caverion Suomi": 0.78},
    "earthworks":    {"NCC Suomi": 0.92, "Lemminkäinen": 0.78},
    "foundations":   {"Lemminkäinen": 0.88, "NCC Suomi": 0.85},
    "structural":    {"NCC Suomi": 0.88, "Lemminkäinen": 0.82, "Konecranes": 0.80},
    "mep":           {"Caverion Suomi": 0.93, "YIT Service": 0.85, "Schneider Finland": 0.78},
    "finishing":     {"Caverion Suomi": 0.86, "YIT Service": 0.84, "Vesto Service": 0.80},
    "commissioning": {"Caverion Suomi": 0.91, "YIT Service": 0.83},
    "inspection":    {"Caverion Suomi": 0.86, "YIT Service": 0.84, "Vesto Service": 0.79},
    "repair":        {"Caverion Suomi": 0.88, "YIT Service": 0.82, "Vesto Service": 0.80},
    "installation":  {"Caverion Suomi": 0.87, "Schneider Finland": 0.85, "YIT Service": 0.82},
}


# Subcontractor home-region. Adds +0.06 P(success) when project region
# matches; adds -0.05 when on the opposite end of Finland.
METSA_SUBCONTRACTOR_HOME: dict[str, str] = {
    "Caverion Suomi":    "Helsinki",
    "YIT Service":       "Tampere",
    "Vesto Service":     "Helsinki",
    "NCC Suomi":         "Oulu",
    "Lemminkäinen":      "Tampere",
    "Schneider Finland": "Helsinki",
    "Konecranes":        "Tampere",
}


# Internal employees Metsä assigns to non-subcontracted tasks. Picked
# from project_team_pool with role-based bias for "planning"/"design"
# phases vs hands-on phases. Reliable people boost slightly.
METSA_EMPLOYEE_POOL: list[str] = [
    "M. Hakala", "T. Virtanen", "K. Mäkinen", "J. Lehtinen",
    "P. Korhonen", "S. Niemi", "L. Aho", "M. Salo", "K. Saari",
    "A. Lindgren", "E. Heikkinen", "H. Mattila",
]


def _project_region(project: dict) -> str:
    """Derive a region label from the project's customer string. Falls
    back to a deterministic round-robin so every project has one."""
    customer = project.get("customer", "")
    for region in ("Helsinki", "Tampere", "Oulu"):
        if region in customer:
            return region
    # Hash the project_id for stable fallback assignment.
    return ("Helsinki", "Tampere", "Oulu")[hash(project["project_id"]) % 3]


def _project_season(start_month: str) -> str:
    month = int(start_month.split("-")[1])
    if month in (12, 1, 2): return "winter"
    if month in (3, 4, 5):  return "spring"
    if month in (6, 7, 8):  return "summer"
    return "autumn"


def _task_success_p(
    template: TaskTemplate,
    phase: str,
    subcontractor: str | None,
    region: str,
    season: str,
    project_budget: float,
) -> float:
    """Engineered probability that the task ends in `success: true`.
    Drives outcome roll for completed tasks and is what Aito's
    `_recommend goal: {success: true}` should learn to predict."""
    # Base rate by assignee kind. Internal employees are average; the
    # interesting variance is on subcontractors.
    if template.assignee_kind == "employee":
        return random.uniform(0.78, 0.88)

    fit = METSA_SUBCONTRACTOR_FIT.get(phase, {})
    p = fit.get(subcontractor or "", 0.62)  # capable-but-not-specialist baseline

    # Region affinity.
    home = METSA_SUBCONTRACTOR_HOME.get(subcontractor or "")
    if home == region:
        p += 0.06
    elif home and home != region:
        p -= 0.04

    # Season effects on weather-sensitive phases.
    if phase == "foundations" and season == "winter":
        p -= 0.18
    if phase == "structural" and season == "winter":
        p -= 0.10
    if phase == "earthworks" and season == "winter":
        p -= 0.12

    # Project-size effects: Lemminkäinen and NCC drag below their target
    # band; Caverion / YIT scale fine across sizes.
    if subcontractor == "Lemminkäinen" and project_budget < 80000:
        p -= 0.10
    if subcontractor == "NCC Suomi" and project_budget < 50000:
        p -= 0.08

    return max(0.05, min(0.97, p))


def _pick_subcontractor(phase: str, region: str, season: str, project_budget: float) -> str:
    """Pick a subcontractor for a task with weight ∝ engineered P(success).

    This is what makes the *fixture* reflect the engineered patterns —
    if subcontractors were picked uniformly, the success roll would
    still vary with subcontractor but the overall historical
    base-rates per (phase, subcontractor) would be flat. We want
    history that *shows* "Caverion does most of the MEP work and
    succeeds 9/10 times" so Aito learns it.
    """
    fit = METSA_SUBCONTRACTOR_FIT.get(phase, {})
    if not fit:
        # Phase has no specialist pool — fall back to maintenance subs.
        return random.choice(["Caverion Suomi", "YIT Service", "Vesto Service"])
    candidates = list(fit.keys())
    # Add 1-2 wildcards (capable-but-not-specialist) so Aito sees the
    # contrast — without them, the demo looks too curated.
    wildcards = ["Caverion Suomi", "YIT Service", "Vesto Service",
                 "NCC Suomi", "Lemminkäinen"]
    for w in wildcards:
        if w not in candidates and random.random() < 0.15:
            candidates.append(w)
    weights = [
        max(0.1, _task_success_p(
            TaskTemplate("", (1, 1), (0, 0), "subcontractor"),
            phase, c, region, season, project_budget,
        )) ** 2
        for c in candidates
    ]
    return random.choices(candidates, weights=weights, k=1)[0]


def generate_metsa_tasks(persona: PersonaSpec, projects: list[dict]) -> list[dict]:
    """Produce one tasks.json row per task across every Metsä project.

    Construction projects yield ~20-25 tasks; maintenance projects ~3-5.
    Outcomes for completed projects are rolled from the engineered
    probability so historical base-rates carry the patterns Aito needs
    to learn.
    """
    if persona.tenant_id != "metsa":
        return []

    tasks: list[dict] = []
    counter = 0
    for project in projects:
        ptype = project["project_type"]
        templates = METSA_TASK_TEMPLATES.get(ptype, {})
        if not templates:
            continue

        region = _project_region(project)
        season = _project_season(project["start_month"])
        project_complete = project["status"] == "complete"
        project_budget = float(project["budget_eur"])

        for phase, phase_tasks in templates.items():
            # Skip a phase entirely 8% of the time so plans aren't
            # boilerplate-identical — gives _predict more variety.
            if random.random() < 0.08:
                continue
            for tmpl in phase_tasks:
                # Drop a sub-task ~12% of the time for the same reason.
                if random.random() < 0.12:
                    continue
                counter += 1

                if tmpl.assignee_kind == "subcontractor":
                    subcontractor = _pick_subcontractor(phase, region, season, project_budget)
                    employee = None
                else:
                    subcontractor = None
                    employee = random.choice(METSA_EMPLOYEE_POOL)

                planned_days = random.randint(*tmpl.days)
                planned_cost = round(random.uniform(*tmpl.cost), -1)

                # Roll the outcome for completed projects only. Active
                # projects leave outcome columns null so the demo's
                # "predict success" view has fresh things to score.
                if project_complete:
                    p_success = _task_success_p(
                        tmpl, phase, subcontractor, region, season, project_budget,
                    )
                    success = random.random() < p_success
                    on_time = success or random.random() < 0.30
                    on_budget = success or random.random() < 0.25
                    actual_days = (
                        planned_days if on_time
                        else int(planned_days * random.uniform(1.10, 1.45))
                    )
                    actual_cost = (
                        planned_cost if on_budget
                        else round(planned_cost * random.uniform(1.08, 1.35), -1)
                    )
                    status = "complete"
                else:
                    success = on_time = on_budget = None
                    actual_days = actual_cost = None
                    # Mix in some partial-progress for active projects.
                    status = random.choices(
                        ["planned", "active", "complete"],
                        weights=[55, 30, 15], k=1,
                    )[0]
                    if status == "complete":
                        # Treat already-finished tasks within an active
                        # project as having outcomes — gives the active
                        # view some realised KPIs alongside open work.
                        p_success = _task_success_p(
                            tmpl, phase, subcontractor, region, season, project_budget,
                        )
                        success = random.random() < p_success
                        on_time = success or random.random() < 0.30
                        on_budget = success or random.random() < 0.25
                        actual_days = (
                            planned_days if on_time
                            else int(planned_days * random.uniform(1.10, 1.45))
                        )
                        actual_cost = (
                            planned_cost if on_budget
                            else round(planned_cost * random.uniform(1.08, 1.35), -1)
                        )

                tasks.append({
                    "task_id": f"TSK-{counter:05d}",
                    "project_id": project["project_id"],
                    "phase": phase,
                    "task_name": tmpl.name,
                    "assignee_kind": tmpl.assignee_kind,
                    "subcontractor": subcontractor,
                    "assignee_person": employee,
                    "planned_days": planned_days,
                    "actual_days": actual_days,
                    "planned_cost_eur": float(planned_cost),
                    "actual_cost_eur": float(actual_cost) if actual_cost is not None else None,
                    "season": season,
                    "region": region,
                    "status": status,
                    "on_time": on_time,
                    "on_budget": on_budget,
                    "success": success,
                    "project_type": ptype,
                })

    return tasks


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
    impressions = generate_impressions(persona, products)
    # Tasks are currently only generated for Metsä — the construction
    # / maintenance phase model the project-plan view depends on doesn't
    # apply directly to retail (Aurora) or services (Studio) personas.
    tasks = generate_metsa_tasks(persona, projects) if persona.tenant_id == "metsa" else []

    with open(out / "purchases.json",     "w") as f: json.dump(purchases,    f, indent=2, ensure_ascii=False)
    with open(out / "products.json",      "w") as f: json.dump(products,     f, indent=2, ensure_ascii=False)
    with open(out / "orders.json",        "w") as f: json.dump(orders,       f, indent=2, ensure_ascii=False)
    with open(out / "price_history.json", "w") as f: json.dump(prices,       f, indent=2, ensure_ascii=False)
    with open(out / "projects.json",      "w") as f: json.dump(projects,     f, indent=2, ensure_ascii=False)
    with open(out / "assignments.json",   "w") as f: json.dump(assignments,  f, indent=2, ensure_ascii=False)
    if impressions:
        with open(out / "impressions.json", "w") as f: json.dump(impressions, f, indent=2, ensure_ascii=False)
    if tasks:
        with open(out / "tasks.json",     "w") as f: json.dump(tasks,        f, indent=2, ensure_ascii=False)

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
    if impressions:
        print(f"  impressions:    {len(impressions)} "
              f"(clicked={sum(1 for r in impressions if r['clicked'])})")
    if persona.tenant_id == "metsa":
        # Re-load to print the count without keeping `tasks` in scope at
        # the function top — write_persona already dumps to disk.
        with open(out / "tasks.json") as f:
            t = json.load(f)
        print(f"  tasks:          {len(t)}  "
              f"(complete={sum(1 for r in t if r['status']=='complete')}, "
              f"active={sum(1 for r in t if r['status']=='active')}, "
              f"planned={sum(1 for r in t if r['status']=='planned')})")


def main() -> None:
    print("Generating per-tenant fixtures...")
    for persona in PERSONAS:
        write_persona(persona)
    print("\nDone. Load into Aito with: ./do load-data --tenant=all")


if __name__ == "__main__":
    main()

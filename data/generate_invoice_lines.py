"""Invoice lines labelled to a catalogue SKU — the line-matching case.

A purchase invoice arrives with one row per product. Somebody has to say
which catalogue item each row refers to, and the row does not say: the
supplier writes the description in their own words, their own order,
their own language and often their own article code. An ERP catalogue
of a few thousand items and a few dozen suppliers each with their own
rendering is a text→id mapping nobody can maintain by hand.

`data/aurora/purchases.json` is invoice HEADERS — one row per purchase,
with a short free-text description and no link to a product. So the
labelled pairs this case needs do not exist and have to be generated.

What makes the generated data worth anything:

  * **The description is never the catalogue name.** Each billing
    supplier renders it through its own style — uppercased, reordered,
    prefixed with their article number, translated, abbreviated to a
    code. If the description were the name, the task would be a string
    join and would prove nothing.

  * **Some suppliers appear only in the test half.** A supplier seen
    for the first time has no history at all, so an id lookup is
    worthless and only the description text and the product's own
    metadata can carry the prediction. That is the number worth
    quoting, and it cannot be measured unless the split is built in.

  * **Difficulty varies.** A few styles keep most of the name; one
    keeps almost none. Reporting a single blended accuracy over a
    corpus that is uniformly easy is how a demo flatters itself.

Deliberately generic. The case this was drawn from is a flower
wholesaler, and modelling it on their data would be both a disclosure
problem and a worse demo — retail catalogue items transfer to every
other line-matching prospect, and a tulip does not.
"""

import json
import random
import zlib
from pathlib import Path

DATA = Path(__file__).resolve().parent

# Billing suppliers are NOT the catalogue's brand names. A wholesaler
# invoices for many brands, which is exactly why the invoice-side text
# drifts from the catalogue-side name.
#
# `style` is how this supplier writes a line. `cold` holds the supplier
# out of the training half entirely, so its accuracy is measurable on
# its own — the first invoice from a new supplier is the hard case and
# the one prospects ask about.
BILLING_SUPPLIERS = [
    ("Pohjola Tukku Oy",        "as_is",          False),
    ("Nordkalk Distribution",   "upper",          False),
    ("Suomen Väline Oy",        "reorder",        False),
    ("Baltic Trade House",      "article_prefix", False),
    ("Kaakon Tukkuliike",       "translate",      False),
    ("Meridian Supply",         "abbreviate",     False),
    ("Lahden Keskusvarasto",    "noisy",          False),
    ("Vellamo Wholesale",       "packsize",       False),
    ("Aurinko Import Oy",       "translate",      False),
    ("Halla Logistics",         "upper",          False),
    ("Itämeri Tuonti Oy",       "article_prefix", False),
    # Never seen in training. Their lines exist only in the test half.
    ("Uusi Kanava Oy",          "reorder",        True),
    ("Frontier Goods Ltd",      "abbreviate",     True),
    ("Ranta Tukku",             "code_only",      True),
]

# Head-noun substitutions. The point is a description that shares few
# or no tokens with the catalogue name, which is where an id lookup
# dies and product metadata has to carry the match.
TRANSLATIONS = {
    "bag": "laukku", "tote": "kassi", "mug": "muki", "towel": "pyyhe",
    "lamp": "valaisin", "chair": "tuoli", "table": "pöytä",
    "knife": "veitsi", "pan": "pannu", "pot": "kattila",
    "shirt": "paita", "socks": "sukat", "jacket": "takki",
    "coffee": "kahvi", "tea": "tee", "soap": "saippua",
    "brush": "harja", "cable": "johto", "drill": "pora",
    "paint": "maali", "shelf": "hylly", "candle": "kynttilä",
    "bowl": "kulho", "plate": "lautanen", "glass": "lasi",
    "cream": "voide", "shampoo": "shampoo", "cloth": "liina",
}


def _render(name: str, style: str, sku: str, hs_code: str,
            rng: random.Random) -> str:
    """One supplier's way of writing a catalogue item on an invoice."""
    words = name.split()

    if style == "as_is":
        return name
    if style == "upper":
        return name.upper()
    if style == "reorder":
        shuffled = words[:]
        rng.shuffle(shuffled)
        return " ".join(shuffled)
    if style == "article_prefix":
        # Their own article number in front, and only part of the name.
        #
        # Derived from a hash of the SKU rather than from its digits: an
        # earlier version spliced the catalogue number straight into the
        # text, which put the answer in the input. Nothing exploited it —
        # this supplier still scores 5% — but a demo whose evidence
        # contains the label is not a demo anyone should believe.
        article = f"{zlib.crc32(sku.encode()) % 900000 + 100000}"
        return f"{article} {' '.join(words[:2])}"
    if style == "translate":
        out = [TRANSLATIONS.get(w.lower(), w) for w in words]
        return " ".join(out).lower()
    if style == "abbreviate":
        # First word intact, the rest cut to stems — a common shorthand
        # that keeps just enough to be matchable.
        head, rest = words[0], words[1:]
        return " ".join([head] + [w[:4] for w in rest])
    if style == "noisy":
        return (f"{name.lower()}, {rng.randint(1, 24)} kpl, "
                f"alv {rng.choice(['25,5', '14', '10'])}%")
    if style == "packsize":
        return f"{name} {rng.choice([6, 12, 24, 48])}-pack"
    if style == "code_only":
        # Almost nothing of the name survives. Only the HS code, the
        # unit and the price are left to go on — the honest worst case.
        return f"ART {rng.randint(10000, 99999)} / {hs_code}"
    raise ValueError(f"unknown rendering style: {style!r}")


def generate(products: list[dict], *, n_train: int = 10000,
             n_test: int = 2000, seed: int = 20260904) -> tuple[list, list]:
    """Labelled invoice lines, split into a training half and a test half.

    The test half is NOT loaded into Aito — it is the held-out set the
    evaluation harness scores against. Loading it would measure how well
    the database remembers rather than how well it generalises, which is
    the mistake that makes a demo number worthless.
    """
    rng = random.Random(seed)
    warm = [s for s in BILLING_SUPPLIERS if not s[2]]
    cold = [s for s in BILLING_SUPPLIERS if s[2]]

    # ~4% of the catalogue is missing a price, an HS code or a unit —
    # deliberately, because Catalog Intelligence exists to predict them.
    # A line cannot be invoiced without a price, so those SKUs are not
    # drawn from. Filtering here rather than defaulting the values keeps
    # the gap visible where it belongs instead of inventing data.
    sellable = [p for p in products
                if p.get("unit_price") and p.get("hs_code")
                and p.get("unit_of_measure") and p.get("name")]
    if not sellable:
        raise ValueError("no catalogue rows carry price, HS code and unit")

    def line(index: int, supplier: tuple, product: dict, prefix: str) -> dict:
        name, style, _ = supplier
        quantity = rng.choice([1, 1, 2, 4, 6, 12, 24])
        # Invoiced prices drift from the list price; a demo where the
        # amount divides exactly into the catalogue price turns the
        # match into arithmetic.
        unit_price = round(float(product["unit_price"])
                           * rng.uniform(0.88, 1.14), 2)
        return {
            "line_id": f"{prefix}-{index:06d}",
            # Lines group into invoices the way they arrive — several
            # products from one supplier on one document.
            "invoice_id": f"INV-{prefix}-{index // 7:05d}",
            "billing_supplier": name,
            "description": _render(product["name"], style, product["sku"],
                                   product["hs_code"], rng),
            "quantity": quantity,
            "unit_of_measure": product["unit_of_measure"],
            "unit_price_eur": unit_price,
            "line_amount_eur": round(unit_price * quantity, 2),
            "invoice_month": f"2026-{rng.randint(1, 9):02d}",
            "sku": product["sku"],
        }

    train = [line(i, rng.choice(warm), rng.choice(sellable), "TRN")
             for i in range(n_train)]

    # The test half is deliberately mixed: two thirds from suppliers the
    # training half knows, one third from suppliers it has never seen.
    # Both numbers get reported, and they are not the same number.
    test = []
    for i in range(n_test):
        supplier = rng.choice(cold) if i % 3 == 0 else rng.choice(warm)
        test.append(line(i, supplier, rng.choice(sellable), "TST"))
    return train, test


def main() -> None:
    out = DATA / "aurora"
    products = json.load(open(out / "products.json"))
    train, test = generate(products)

    with open(out / "invoice_lines.json", "w") as f:
        json.dump(train, f, indent=2, ensure_ascii=False)
    with open(out / "invoice_lines_test.json", "w") as f:
        json.dump(test, f, indent=2, ensure_ascii=False)

    cold_names = {s[0] for s in BILLING_SUPPLIERS if s[2]}
    cold_lines = sum(1 for line in test
                     if line["billing_supplier"] in cold_names)
    print(f"  invoice_lines:      {len(train)} train (loaded into Aito)")
    print(f"  invoice_lines_test: {len(test)} held out — "
          f"{cold_lines} of them from {len(cold_names)} unseen suppliers")
    sellable = sum(1 for p in products
                   if p.get("unit_price") and p.get("hs_code")
                   and p.get("unit_of_measure") and p.get("name"))
    print(f"  catalogue:          {len(products)} SKUs "
          f"({sellable} complete enough to invoice)")


if __name__ == "__main__":
    main()

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
import re
import zlib
from collections.abc import Callable
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
    # Writes the whole line in Finnish. `rose` -> `ruusu`: the words
    # that carry the meaning are replaced, so token overlap with the
    # catalogue name goes to nearly zero and the ONLY route to the
    # answer is history. This is the case the demo exists for.
    ("Kukkatukku Salo Oy",      "translate_all",  False),
    # Their own article number and nothing else — no name text at all.
    # Stable per SKU (see `_render`), so it is learnable from history
    # and a text index is provably 0%. The pure-history showcase, and
    # deliberately NOT cold: a code seen for the first time is
    # unlearnable for a second, uninteresting reason.
    ("Ranta Tukku",             "code_only",      False),
    # Writes the same product a different way each time — `Episode 2`,
    # `Episode II`, `Episode 02`, `Ep 2`. Each form Aito has SEEN is a
    # token pointing at the SKU; a form it has not seen has nothing to
    # look up, and the identity boost is lexical so it will not bridge
    # `II` to `2`. A known engine gap, here so it is measurable.
    ("Variantti Oy",            "numeral_variant", False),
    # Never seen in training. Their lines exist only in the test half.
    ("Uusi Kanava Oy",          "reorder",        True),
    ("Frontier Goods Ltd",      "abbreviate",     True),
    ("Pohjoinen Kauppa Oy",     "translate_all",  True),
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


# What each wholesaler actually deals in.
#
# Without this, `billing_supplier` carries NO product signal: every
# supplier was drawn against a uniform sample of the catalogue, so
# `P(category | supplier)` was flat at ~1/7 and the column could argue
# nothing. Real wholesalers specialise, and that specialisation is one
# of the most legible things a `$why` tree can show a human — "this
# supplier invoices Groceries 80% of the time" is a sentence a finance
# lead believes.
#
# `(predicate, share)` — that share of the supplier's lines are drawn
# from products the predicate accepts, the rest from the whole
# catalogue. Deliberately partial: a supplier at 1.0 would turn the
# column into a lookup rather than evidence.
#
# A predicate rather than a field/value pair because one of these is not
# an attribute at all — Variantti only makes sense on products whose
# name carries a version number to re-spell.
def _in(field: str, value: str):
    return lambda p: p.get(field) == value


SUPPLIER_BIAS: dict[str, tuple[Callable[[dict], bool], float]] = {
    "Kukkatukku Salo Oy":    (_in("category", "Groceries"),   0.80),
    "Pohjoinen Kauppa Oy":   (_in("category", "Groceries"),   0.75),
    "Nordkalk Distribution": (_in("category", "DIY"),         0.70),
    "Suomen Väline Oy":      (_in("category", "DIY"),         0.65),
    "Halla Logistics":       (_in("category", "Electronics"), 0.70),
    "Aurinko Import Oy":     (_in("category", "Beauty"),      0.70),
    "Vellamo Wholesale":     (_in("supplier", "Marimekko"),   0.60),
    "Baltic Trade House":    (_in("supplier", "Tikkurila"),   0.55),
    # Only products whose name carries a version token — the whole point
    # of this supplier is re-spelling a number the catalogue already has.
    "Variantti Oy":          (lambda p: bool(_HAS_VERSION.search(p.get("name") or "")),
                              1.00),
}


# A covering Finnish vocabulary for the catalogue's own words. There are
# only ~165 distinct tokens across 3200 product names, so a supplier who
# writes in Finnish can be made to translate essentially ALL of the
# meaning-carrying ones — which is the point. `TRANSLATIONS` above swaps
# head nouns and leaves 95% of the tokens intact; this leaves almost
# none, so token overlap with the catalogue name collapses and history
# is the only route to the answer.
#
# Brands are deliberately absent: a brand name does not translate, and
# leaving `Marimekko` alone is both realistic and a small honest crumb
# of signal.
VOCABULARY = {
    "black": "musta", "blue": "sininen", "silver": "hopea",
    "yellow": "keltainen", "natural": "luonnonvalkoinen", "navy": "laivastonsininen",
    "beige": "beige", "olive": "oliivi", "rust": "ruoste", "chrome": "kromi",
    "graphite": "grafiitti", "terracotta": "terrakotta", "white": "valkoinen",
    "green": "vihreä", "red": "punainen",
    "set": "sarja", "pack": "pakkaus", "box": "laatikko", "storage": "säilytys",
    "family": "perhe", "wireless": "langaton", "smart": "äly",
    "multi": "moni", "surface": "pinta", "refill": "täyttö",
    "tape": "mitta", "measure": "nauha", "wrench": "kiintoavain",
    "drill": "pora", "bit": "terä", "paint": "maali", "roller": "tela",
    "cleaner": "puhdistusaine", "detergent": "pesuaine", "laundry": "pyykki",
    "dishwasher": "astianpesukone", "tablets": "tabletit",
    "shampoo": "shampoo", "toilette": "toilette", "eau": "eau",
    "beauty": "kauneus", "mascara": "ripsiväri", "lipstick": "huulipuna",
    "cream": "voide", "lotion": "emulsio", "soap": "saippua",
    "speaker": "kaiutin", "earbuds": "nappikuulokkeet", "laptop": "kannettava",
    "smartphone": "älypuhelin", "tablet": "taulutietokone", "monitor": "näyttö",
    "keyboard": "näppäimistö", "mouse": "hiiri", "cable": "johto",
    "charger": "laturi", "battery": "akku", "headphones": "kuulokkeet",
    "camera": "kamera", "printer": "tulostin",
    "shirt": "paita", "jacket": "takki", "socks": "sukat", "dress": "mekko",
    "scarf": "huivi", "bag": "laukku", "tote": "kassi", "towel": "pyyhe",
    "mug": "muki", "bowl": "kulho", "plate": "lautanen", "glass": "lasi",
    "knife": "veitsi", "pan": "pannu", "pot": "kattila", "candle": "kynttilä",
    "shelf": "hylly", "chair": "tuoli", "table": "pöytä", "lamp": "valaisin",
    "brush": "harja", "cloth": "liina", "curtain": "verho", "cushion": "tyyny",
    "coffee": "kahvi", "tea": "tee", "yogurt": "jogurtti", "butter": "voi",
    "cheese": "juusto", "bread": "leipä", "juice": "mehu", "milk": "maito",
    "sausage": "makkara", "apple": "omena", "sugar": "sokeri", "salt": "suola",
}

# The SAME number the catalogue name already carries, written four ways:
# `v2` -> `v2` / `vII` / `v02` / `v 2`. This is the RPA case — `Episode 2`,
# `Episode II`, `Episode 02`, `E02` all name one thing.
#
# Aito learns each form it has SEEN as a token pointing at the SKU. A
# form it has never seen has nothing to look up, and the identity boost
# is lexical, so it will not bridge `II` to `2`. Bridging those needs
# character or subword features; that belongs in the engine. It is here
# so the gap is measurable rather than anecdotal.
_ROMAN = ("", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
          "XI", "XII")

NUMERAL_FORMS = (
    lambda n: f"v{n}",                                     # v2  (as catalogued)
    lambda n: f"v{_ROMAN[n]}" if n < len(_ROMAN) else f"v{n}",   # vII
    lambda n: f"v{n:02d}",                                 # v02
    lambda n: f"v {n}",                                    # v 2
)

# The version token the catalogue actually uses, e.g. the `v2` in
# "Marimekko T-shirt XL v2".
_VERSION = re.compile(r"^v(\d+)$", re.IGNORECASE)
_HAS_VERSION = re.compile(r"\bv\d+\b", re.IGNORECASE)


def _stable_code(sku: str, width: int = 6) -> str:
    """An article number that is the SAME every time this SKU appears.

    The first version drew `rng.randint(10000, 99999)` per LINE, which
    made the code pure noise: nothing could ever learn it, and it was
    10% of the test set holding every headline number down. A supplier's
    article number is a property of the PRODUCT, so it has to be a
    function of the SKU and nothing else.
    """
    return str(zlib.crc32(sku.encode()) % (10 ** width))


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
    if style == "translate_all":
        # Every word this supplier has a Finnish word for. Brands and
        # sizes survive; the meaning does not.
        return " ".join(VOCABULARY.get(w.lower(), w) for w in words).lower()
    if style == "code_only":
        # No name text at all — their article number and the HS code.
        # STABLE per SKU, so history can learn it and a text index
        # provably cannot: the pure-history case.
        return f"ART {_stable_code(sku)} / {hs_code}"
    if style == "numeral_variant":
        # Rewrite the version token the NAME already carries, leaving
        # every other word alone. Names without one are written plainly:
        # inventing a number would make this a different test.
        out, touched = [], False
        for word in words:
            m = _VERSION.match(word)
            if m and not touched:
                out.append(rng.choice(NUMERAL_FORMS)(int(m.group(1))))
                touched = True
            else:
                out.append(word)
        return " ".join(out)
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

    # Pre-bucket the catalogue per bias so the draw stays O(1) rather
    # than filtering 3200 rows per line.
    biased: dict[str, list[dict]] = {}
    for who, (predicate, _) in SUPPLIER_BIAS.items():
        biased[who] = [p for p in sellable if predicate(p)]
        if not biased[who]:
            raise ValueError(
                f"{who} is biased toward a product subset that is empty — "
                "the bias would silently do nothing.")

    def pick(supplier: tuple) -> dict:
        """A product this supplier plausibly deals in."""
        bias = SUPPLIER_BIAS.get(supplier[0])
        if bias and rng.random() < bias[1]:
            return rng.choice(biased[supplier[0]])
        return rng.choice(sellable)

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

    def draw(pool: list[tuple], index: int, prefix: str) -> dict:
        supplier = rng.choice(pool)
        return line(index, supplier, pick(supplier), prefix)

    train = [draw(warm, i, "TRN") for i in range(n_train)]

    # The test half is deliberately mixed: two thirds from suppliers the
    # training half knows, one third from suppliers it has never seen.
    # Both numbers get reported, and they are not the same number.
    test = [draw(cold if i % 3 == 0 else warm, i, "TST")
            for i in range(n_test)]
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

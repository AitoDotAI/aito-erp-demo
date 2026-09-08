"""Invoice lines labelled to a catalogue SKU — the line-matching case.

A purchase invoice arrives with one row per product. Somebody has to say
which catalogue item each row refers to, and the row does not say: the
supplier writes the description in their own words, their own order,
their own language and often their own article code.

**The answer is always derivable.** That is the point of this corpus and
it took a rewrite to get right. A clerk doing this by hand is not
guessing — the invoice, the vendor and the catalogue between them
contain enough to identify exactly one row, and a matcher that cannot
reach 90% is leaving information on the table. An earlier version of
this file had 51.6% of the catalogue sharing a name with another row,
which capped ANY matcher at 63% and made the corpus a test of luck.

Three routes from a line to a row, and every line has at least one:

  1. **The words.** Exact, a synonym, or the other language. `rose` ->
     `Ruusu`. Learnable from history and from nothing else.
  2. **The vendor.** A vendor has a city and a market position, and
     those map onto the product's `origin` and `grade` — a Kouvola
     grower invoices Kouvola stock, a premium importer does not sell
     the budget line. This is what turns `billing_supplier` from a
     category hint into a discriminator between two otherwise identical
     rows. When a vendor sells outside its usual profile, the LINE says
     so, so the information never simply vanishes.
  3. **The description.** The catalogue's spec line carries the sizes a
     row covers, in words and figures. An invoice quoting `40cm` can
     reach a row named `Pitkä` through the description and through
     nothing else.

Deliberately generic. The case this was drawn from is a flower
wholesaler, and modelling it on their data would be both a disclosure
problem and a worse demo — retail catalogue items transfer to every
other line-matching prospect, and a tulip does not.
"""

import json
import random
import re
import sys
import zlib
from pathlib import Path

DATA = Path(__file__).resolve().parent

# Vendors, with the details that let them argue for a row.
#
# `sells_origin` / `sells_grade` are what this vendor normally deals in.
# `style` is how they write a line. `cold` holds them out of the
# training half entirely, so cold start is measurable on its own.
VENDORS = [
    # vendor, city, country, position, origin, grade, style, cold
    ("Pohjola Tukku Oy",      "Kouvola",  "FI", "wholesale", "Kouvola",    "standard", "as_is",         False),
    ("Nordkalk Distribution", "Turku",    "FI", "wholesale", "Turku",      "standard", "upper",         False),
    ("Suomen Väline Oy",      "Tampere",  "FI", "specialist", "Tampere",   "premium",  "reorder",       False),
    ("Baltic Trade House",    "Tallinn",  "EE", "importer",  "tuonti",     "budget",   "article_prefix", False),
    ("Kaakon Tukkuliike",     "Kouvola",  "FI", "wholesale", "lähituote",  "standard", "synonym",       False),
    ("Meridian Supply",       "Oulu",     "FI", "wholesale", "Oulu",       "standard", "abbreviate",    False),
    ("Lahden Keskusvarasto",  "Tampere",  "FI", "wholesale", "kotimainen", "budget",   "noisy",         False),
    ("Vellamo Wholesale",     "Turku",    "FI", "specialist", "Turku",     "premium",  "size_word",     False),
    ("Aurinko Import Oy",     "Riga",     "LV", "importer",  "tuonti",     "standard", "translate_all", False),
    ("Halla Logistics",       "Oulu",     "FI", "wholesale", "Oulu",       "budget",   "upper",         False),
    ("Itämeri Tuonti Oy",     "Tallinn",  "EE", "importer",  "tuonti",     "premium",  "article_prefix", False),
    ("Kukkatukku Salo Oy",    "Kouvola",  "FI", "specialist", "lähituote", "premium",  "translate_all", False),
    ("Ranta Tukku",           "Kouvola",  "FI", "wholesale", "kotimainen", "standard", "code_only",     False),
    ("Variantti Oy",          "Tampere",  "FI", "wholesale", "Tampere",    "standard", "numeral_variant", False),
    # Never seen in training. Their lines exist only in the test half.
    ("Uusi Kanava Oy",        "Turku",    "FI", "wholesale", "Turku",      "standard", "reorder",       True),
    ("Frontier Goods Ltd",    "Riga",     "LV", "importer",  "tuonti",     "budget",   "abbreviate",    True),
    ("Pohjoinen Kauppa Oy",   "Oulu",     "FI", "wholesale", "kotimainen", "premium",  "translate_all", True),
]

# How often a vendor invoices something from its usual origin/grade.
# Not 1.0: a vendor that ALWAYS sold one origin would make the column a
# lookup rather than evidence. When they sell outside it, the line says
# which origin — see `_render` — so the answer stays derivable either
# way. That is the difference between a hard problem and an impossible
# one, and this corpus is meant to be the first.
ON_PROFILE = 0.85

# Head-noun synonyms. A different word for the same thing, in the same
# language — the `rose` / `rose stem` case rather than the `rose` /
# `ruusu` one.
SYNONYMS = {
    "bag": "holdall", "tote": "carryall", "mug": "beaker", "towel": "cloth",
    "lamp": "light", "chair": "seat", "table": "desk", "knife": "blade",
    "pan": "skillet", "pot": "saucepan", "shirt": "top", "socks": "hosiery",
    "jacket": "coat", "soap": "cleanser", "brush": "broom", "cable": "lead",
    "drill": "driver", "paint": "coating", "shelf": "rack", "candle": "taper",
    "bowl": "dish", "plate": "platter", "glass": "tumbler", "cream": "balm",
    "cloth": "wipe", "box": "crate", "set": "kit", "speaker": "monitor",
    "earbuds": "headset", "laptop": "notebook", "juice": "cordial",
    "bread": "loaf", "butter": "spread", "cheese": "curd",
}

# A covering Finnish vocabulary for the catalogue's own words. There are
# only ~165 distinct tokens across 3200 product names, so a supplier who
# writes in Finnish can be made to translate essentially ALL of the
# meaning-carrying ones. Brands are deliberately absent: a brand name
# does not translate.
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

_ROMAN = ("", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
          "XI", "XII")

# The SAME number the catalogue name already carries, written four ways:
# the RPA case — `Episode 2`, `Episode II`, `Episode 02`, `E02` all name
# one thing. Aito learns each form it has SEEN; a form it has not seen
# has nothing to look up, and a lexical boost will not bridge `II` to
# `2`. That is an engine gap, here so it is measurable.
NUMERAL_FORMS = (
    lambda n: f"v{n}",
    lambda n: f"v{_ROMAN[n]}" if n < len(_ROMAN) else f"v{n}",
    lambda n: f"v{n:02d}",
    lambda n: f"v {n}",
)

_VERSION = re.compile(r"^v(\d+)$", re.IGNORECASE)

# `base_name` is defined once, in the evaluation harness, and imported
# here. It decides what an invoice could quote from a catalogue name, so
# a second copy in the generator would eventually disagree with the one
# the scoring uses — and the numbers would move for a reason nobody
# could see. This file is a script rather than a package member, so the
# repo root has to go on the path first.
sys.path.insert(0, str(DATA.parent))
from src.match_baseline import base_name  # noqa: E402


def _stable_code(sku: str, width: int = 6) -> str:
    """An article number that is the SAME every time this SKU appears.

    A supplier's article number is a property of the PRODUCT. Drawing it
    per line made it pure noise that nothing could ever learn.
    """
    return str(zlib.crc32(sku.encode()) % (10 ** width))


def _render(product: dict, style: str, rng: random.Random) -> str:
    """One vendor's way of writing a catalogue item on an invoice."""
    name = base_name(product["name"])
    words = name.split()

    if style == "as_is":
        return name
    if style == "upper":
        return name.upper()
    if style == "reorder":
        shuffled = words[:]
        rng.shuffle(shuffled)
        return " ".join(shuffled)
    if style == "synonym":
        return " ".join(SYNONYMS.get(w.lower(), w) for w in words)
    if style == "translate_all":
        return " ".join(VOCABULARY.get(w.lower(), w) for w in words).lower()
    if style == "abbreviate":
        head, rest = words[0], words[1:]
        return " ".join([head] + [w[:4] for w in rest])
    if style == "noisy":
        return (f"{name.lower()}, {rng.randint(1, 24)} kpl, "
                f"alv {rng.choice(['25,5', '14', '10'])}%")
    if style == "size_word":
        # Writes the size as a WORD where the catalogue name gives a
        # measurement — "8m" invoiced as "pitkä". Only the product's
        # `description`, which carries "8m tai pitkä", connects the two.
        # That is the third route in, and the one a catalogue with tags
        # or a spec blurb really does provide.
        pair = re.search(r"([^\s,]+) tai (\w+)",
                         product.get("description") or "")
        if not pair:
            return name
        measurement, word = pair.group(1), pair.group(2)
        return " ".join(word if w == measurement else w for w in words)
    if style == "article_prefix":
        return f"{_stable_code(product['sku'])} {' '.join(words[:2])}"
    if style == "code_only":
        # No name text at all. Their article number and the HS code —
        # stable, so history can learn it and a text index provably
        # cannot. The pure-history case.
        return f"ART {_stable_code(product['sku'])} / {product['hs_code']}"
    if style == "numeral_variant":
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


def generate(products: list[dict], *, n_train: int = 60000,
             n_test: int = 2000, seed: int = 20260906) -> tuple[list, list, list]:
    """Labelled invoice lines, split into a training and a held-out half.

    Returns `(train, test, vendors)`. The test half is NOT loaded into
    Aito — loading it would measure how well the database remembers
    rather than how well it generalises.
    """
    rng = random.Random(seed)
    vendors = [
        {"vendor": v, "city": c, "country": k, "position": pos,
         "sells_origin": origin, "sells_grade": grade}
        for v, c, k, pos, origin, grade, _, _ in VENDORS
    ]
    warm = [v for v in VENDORS if not v[7]]
    cold = [v for v in VENDORS if v[7]]

    # A line cannot be invoiced without a price, a unit or an HS code.
    sellable = [p for p in products
                if p.get("unit_price") and p.get("hs_code")
                and p.get("unit_of_measure") and p.get("name")]
    if not sellable:
        raise ValueError("no catalogue rows carry price, HS code and unit")

    by_profile: dict[tuple[str, str], list[dict]] = {}
    for p in sellable:
        by_profile.setdefault((p.get("origin"), p.get("grade")), []).append(p)

    def pick(vendor: tuple) -> dict:
        """A product this vendor plausibly deals in."""
        pool = by_profile.get((vendor[4], vendor[5]))
        if pool and rng.random() < ON_PROFILE:
            return rng.choice(pool)
        return rng.choice(sellable)

    def line(index: int, vendor: tuple, product: dict, prefix: str) -> dict:
        name, _, _, _, sells_origin, sells_grade, style, _ = vendor
        text = _render(product, style, rng)
        # If this vendor is invoicing something OUTSIDE its usual
        # origin, the line names the origin. Real invoices do this, and
        # it is what keeps the answer derivable when the vendor's own
        # profile would point at the wrong row.
        if product.get("origin") and product["origin"] != sells_origin:
            text = f"{text} {product['origin'].lower()}"
        if product.get("grade") and product["grade"] != sells_grade:
            text = f"{text} {product['grade']}"

        quantity = rng.choice([1, 1, 2, 4, 6, 12, 24])
        unit_price = round(float(product["unit_price"])
                           * rng.uniform(0.88, 1.14), 2)
        return {
            "line_id": f"{prefix}-{index:06d}",
            "invoice_id": f"INV-{prefix}-{index // 7:05d}",
            "billing_supplier": name,
            "description": text,
            "quantity": quantity,
            "unit_of_measure": product["unit_of_measure"],
            "unit_price_eur": unit_price,
            "line_amount_eur": round(unit_price * quantity, 2),
            "invoice_month": f"2026-{rng.randint(1, 9):02d}",
            "sku": product["sku"],
        }

    def draw(pool: list[tuple], index: int, prefix: str) -> dict:
        vendor = rng.choice(pool)
        return line(index, vendor, pick(vendor), prefix)

    # History has to EXIST before it can be learned from. At 10000
    # lines over 3200 SKUs the corpus averaged 4.2 lines per product,
    # 795 products were never invoiced at all, and most of the rest had
    # been written in exactly one vendor's style — so a line arriving in
    # Finnish had a 50% chance that its product had never been written
    # in Finnish before. Half the measured cold-start failures were that
    # and nothing else.
    #
    # A real wholesaler invoices the same product weekly. 60000 lines is
    # ~19 per SKU, which is still a modest year for one mid-size
    # customer, and it is what makes the corpus answerable FROM HISTORY
    # rather than only in principle.
    #
    # The seeding pass guarantees every sellable product appears, each
    # under a different vendor: a product nobody ever invoiced cannot be
    # matched from history by anyone, and leaving a quarter of the
    # catalogue in that state measured the sampling, not the matcher.
    train: list[dict] = []
    index = 0
    for product in sellable:
        for vendor in rng.sample(warm, min(3, len(warm))):
            train.append(line(index, vendor, product, "TRN"))
            index += 1
    while len(train) < n_train:
        train.append(draw(warm, index, "TRN"))
        index += 1
    rng.shuffle(train)
    # Two thirds from vendors the training half knows, one third from
    # vendors it has never seen. Both get reported, separately.
    test = [draw(cold if i % 3 == 0 else warm, i, "TST")
            for i in range(n_test)]
    return train, test, vendors


def main() -> None:
    out = DATA / "aurora"
    products = json.load(open(out / "products.json"))
    train, test, vendors = generate(products)

    for name, rows in (("invoice_lines", train), ("invoice_lines_test", test),
                       ("vendors", vendors)):
        with open(out / f"{name}.json", "w") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)

    cold_names = {v[0] for v in VENDORS if v[7]}
    cold_lines = sum(1 for line in test
                     if line["billing_supplier"] in cold_names)
    print(f"  vendors:            {len(vendors)}")
    print(f"  invoice_lines:      {len(train)} train (loaded into Aito)")
    print(f"  invoice_lines_test: {len(test)} held out — "
          f"{cold_lines} of them from {len(cold_names)} unseen vendors")
    names = {p["name"] for p in products}
    print(f"  catalogue:          {len(products)} SKUs, "
          f"{len(names)} distinct names")


if __name__ == "__main__":
    main()

"""Booktest for invoice-line → catalogue-SKU matching quality.

Two layers, the same shape as the project booktest.

1. **Offline fixture signal** — protects the demo's *data*. This case
   went through three corpora before it measured anything useful, and
   each failure was silent: half the catalogue sharing a name capped
   every matcher at 63%, an article code drawn per LINE could not be
   learned by anyone, and 4.2 training lines per SKU meant a quarter of
   the catalogue had no history at all. None of those look like bugs
   from the outside — they look like a mediocre database. These tests
   fail loudly instead.

2. **Live Aito backtest** — skipped without credentials. Scores the
   held-out half that was never loaded and checks the claims the view
   actually makes: that Aito beats a text index, that it answers the
   regime a text index cannot answer at all, and that a first-time
   vendor is harder than a familiar one.

Run with: `./do booktest-matching`.
"""

from __future__ import annotations

import collections
import importlib.util
import json
import os
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AURORA = DATA_DIR / "aurora"

needs_fixture = pytest.mark.skipif(
    not (AURORA / "invoice_lines.json").exists(),
    reason="invoice fixtures not generated — run `./do generate-personas`",
)


def _generator():
    """Read the vendor roster FROM the generator rather than mirroring it.

    The project booktest learned this the hard way: a hand-copied list
    of names went stale the moment the fixture grew, and the test went
    on passing while measuring the wrong thing.
    """
    spec = importlib.util.spec_from_file_location(
        "generate_invoice_lines", DATA_DIR / "generate_invoice_lines.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(name: str) -> list[dict]:
    return json.load(open(AURORA / f"{name}.json"))


# ── Layer 1: offline fixture-signal tests ───────────────────────────


@needs_fixture
def test_every_catalogue_row_has_a_distinct_name():
    """The ceiling is 100% only while this holds.

    An earlier catalogue had 51.6% of rows sharing a name with another
    row — thirty-three products called "Tape Measure 10pk". No matcher
    can separate those and no human clerk can either, so top-1 was
    capped at 63% and the case measured luck. If a fixture change ever
    reintroduces collisions, the accuracy drop will look like a ranking
    regression. It is not; it is this.
    """
    products = _load("products")
    names = collections.Counter(p["name"] for p in products)
    shared = {n: c for n, c in names.items() if c > 1}
    assert not shared, (
        f"{sum(shared.values())} catalogue rows share a name "
        f"(e.g. {list(shared)[:3]}). The matching ceiling is no longer 100%.")


@needs_fixture
def test_the_evidence_identifies_exactly_one_row():
    """(base name, origin) must be unique.

    An invoice quotes the product but NOT its origin — the vendor
    supplies that. So the text carries the base name, the vendor carries
    the origin, and between them exactly one row must be left. This is
    what makes the corpus answerable rather than merely hard.
    """
    gen = _generator()
    products = _load("products")
    pairs = collections.Counter(
        (gen.base_name(p["name"]), p.get("origin")) for p in products)
    clashing = {k: c for k, c in pairs.items() if c > 1}
    assert not clashing, (
        f"{len(clashing)} (base name, origin) pairs identify more than one "
        f"row, e.g. {list(clashing)[:2]} — those lines are underivable.")


@needs_fixture
def test_every_sellable_product_has_some_history():
    """History has to exist before anything can learn from it.

    At 10 000 lines over 3200 SKUs, 795 products had never been invoiced
    once. A product nobody ever invoiced cannot be matched from history
    by any engine, and leaving a quarter of the catalogue in that state
    measured the sampling rather than the matcher.
    """
    train = _load("invoice_lines")
    products = _load("products")
    sellable = {p["sku"] for p in products
                if p.get("unit_price") and p.get("hs_code")
                and p.get("unit_of_measure") and p.get("name")}
    seen = {line["sku"] for line in train}
    missing = sellable - seen
    assert not missing, (
        f"{len(missing)} sellable products never appear in training history")
    per_sku = len(train) / max(len(seen), 1)
    assert per_sku >= 10, (
        f"only {per_sku:.1f} training lines per SKU. Below ~10 a product has "
        "not been seen in most vendors' styles, and cold start measures the "
        "sampling instead of the engine.")


@needs_fixture
def test_an_article_code_is_stable_per_product():
    """A supplier's article number is a property of the PRODUCT.

    Drawn per line it is pure noise that nothing can ever learn — and it
    was, for 10% of the corpus, dragging every headline number down
    while looking exactly like a bad ranking.
    """
    gen = _generator()
    coded = {v[0] for v in gen.VENDORS if v[6] in ("code_only", "article_prefix")}
    assert coded, "no vendor writes an article code — the pure-history case is gone"
    by_sku: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for line in _load("invoice_lines") + _load("invoice_lines_holdout"):
        if line["billing_supplier"] in coded:
            by_sku[(line["billing_supplier"], line["sku"])].add(line["description"])
    spread = [k for k, v in by_sku.items() if len(v) > 1]
    assert not spread, (
        f"{len(spread)} (vendor, SKU) pairs have more than one article code; "
        "a code that changes per line carries no information at all")


def test_the_holdout_table_carries_no_links():
    """The held-out rows live in Aito so the view can read a queue in
    production, where `data/` does not exist. That is only safe while
    the table is inert.

    `invoice_lines.sku` links to `products` and `billing_supplier` to
    `vendors`. If the holdout table ever grew the same links, rows Aito
    is supposed to have never seen could contribute evidence to
    `_predict invoice_lines.sku` through those shared tables — and the
    accuracy would go UP, which is the worst possible symptom because it
    looks like progress.
    """
    from src.data_loader import SCHEMAS

    holdout = SCHEMAS["invoice_lines_holdout"]["columns"]
    linked = sorted(k for k, v in holdout.items() if "link" in v)
    assert not linked, (
        f"invoice_lines_holdout has link(s) on {linked}. Held-out rows must "
        "stay unreachable from the prediction path.")
    # And it must still carry what the view needs to render a queue.
    assert {"line_id", "billing_supplier", "description", "sku",
            "unit_of_measure", "unit_price_eur"} <= set(holdout)


@needs_fixture
def test_the_held_out_half_is_actually_held_out():
    """Scoring against rows that were loaded measures memory, not skill."""
    train_ids = {line["line_id"] for line in _load("invoice_lines")}
    test = _load("invoice_lines_holdout")
    overlap = train_ids & {line["line_id"] for line in test}
    assert not overlap, f"{len(overlap)} held-out lines are also in training"
    assert len(test) >= 500, "held-out split too small to measure anything"


@needs_fixture
def test_cold_vendors_appear_only_in_the_held_out_half():
    """Cold start is the argument, so it has to be real.

    A vendor marked cold must have NO training history — otherwise the
    number reported as cold start is measuring something else.
    """
    gen = _generator()
    cold = {v[0] for v in gen.VENDORS if v[7]}
    assert cold, "no cold vendors — cold start is no longer measurable"
    leaked = cold & {line["billing_supplier"] for line in _load("invoice_lines")}
    assert not leaked, f"cold vendors present in training: {sorted(leaked)}"
    in_test = cold & {line["billing_supplier"]
                      for line in _load("invoice_lines_holdout")}
    assert in_test == cold, f"cold vendors missing from the test half: {cold - in_test}"


@needs_fixture
def test_a_vendor_predicts_something_about_the_product():
    """The second route in: vendor → origin.

    Drawn independently, `billing_supplier` carried no product signal at
    all and could only narrow the category. The whole "a Kouvola grower
    invoices Kouvola stock" mechanism rests on this correlation being
    present in the data.
    """
    gen = _generator()
    products = {p["sku"]: p for p in _load("products")}
    train = _load("invoice_lines")
    profile = {v[0]: v[4] for v in gen.VENDORS}
    on = sum(1 for line in train
             if products[line["sku"]].get("origin") == profile.get(
                 line["billing_supplier"]))
    share = on / max(len(train), 1)
    assert share > 0.5, (
        f"only {share:.1%} of lines come from a vendor whose usual origin "
        "matches the product. The vendor route carries no signal.")
    assert share < 0.98, (
        f"{share:.1%} of lines are on-profile — the vendor column has become "
        "a lookup rather than evidence")


@needs_fixture
def test_the_description_carries_the_size_both_ways():
    """The third route in: `ruusu 40cm` → `Ruusu Pitkä`.

    Only the description connects a line quoting a measurement to a row
    named in words, so it has to hold both forms.
    """
    described = [p for p in _load("products")
                 if " tai " in (p.get("description") or "")]
    assert len(described) > 200, (
        f"only {len(described)} products pair a measurement with a word in "
        "their description; the size_word route is not testable")


@needs_fixture
def test_every_rendering_style_is_represented():
    """A style that never appears cannot be reported on per regime."""
    gen = _generator()
    styles = {v[6] for v in gen.VENDORS}
    vendors = {v[0]: v[6] for v in gen.VENDORS}
    present = {vendors[line["billing_supplier"]]
               for line in _load("invoice_lines") + _load("invoice_lines_holdout")}
    assert styles == present, f"styles never generated: {sorted(styles - present)}"


# ── Layer 2: live Aito backtest ─────────────────────────────────────


needs_aito = pytest.mark.skipif(
    not (os.environ.get("AITO_API_URL") and os.environ.get("AITO_API_KEY")),
    reason="AITO_API_URL / AITO_API_KEY not set — skipping live Aito backtest",
)

SAMPLE = 150


@pytest.fixture(scope="module")
def scored():
    """Rank a sample of held-out lines, once, for every live test."""
    from concurrent.futures import ThreadPoolExecutor

    from src.aito_client import AitoClient, AitoError
    from src.config import load_config
    from src.matching_service import rank_line

    cfg = load_config()
    creds = cfg.creds_for("aurora")
    client = AitoClient.from_creds(creds.api_url, creds.api_key,
                                   api_version=cfg.api_version)
    try:
        client.search("invoice_lines", {}, limit=1)
    except AitoError as exc:
        pytest.skip(f"invoice_lines not loaded in Aito ({exc}) — "
                    "run `./do load-data --tenant=aurora` first")

    lines = _load("invoice_lines_holdout")[:SAMPLE]
    vendors = {v["vendor"]: v for v in _load("vendors")}
    with ThreadPoolExecutor(max_workers=8) as pool:
        ranked = list(pool.map(
            lambda line: rank_line(
                client, line,
                vendor=vendors.get(line["billing_supplier"]))[0], lines))
    return list(zip(lines, ranked))


def _top1(pairs) -> float:
    if not pairs:
        return 0.0
    hit = sum(1 for line, r in pairs if r and r[0].sku == line["sku"])
    return hit / len(pairs)


@needs_aito
@needs_fixture
def test_aito_beats_the_text_index_floor(scored):
    """The floor is a TF-IDF index over the catalogue, ~30 lines of
    Python. Below it, the database is not earning its place."""
    from src.match_baseline import TfIdfCatalogue

    index = TfIdfCatalogue(_load("products"))
    floor = sum(1 for line, _ in scored
                if (r := index.rank(line["description"])) and r[0] == line["sku"])
    floor /= len(scored)
    aito = _top1(scored)
    assert aito > floor, (
        f"Aito {aito:.1%} does not beat the TF-IDF floor {floor:.1%}")


@needs_aito
@needs_fixture
def test_aito_answers_the_regime_a_text_index_cannot(scored):
    """Lines sharing NO words with the catalogue name — an article code
    and an HS number. A text index scores 0% there by construction; this
    is the case that only history can answer, and the reason the demo
    has a database in it at all."""
    from src.match_baseline import regime

    names = {p["sku"]: p["name"] for p in _load("products")}
    blind = [(line, r) for line, r in scored
             if regime(line["description"], names.get(line["sku"], "")) == "0%"]
    if len(blind) < 10:
        pytest.skip(f"only {len(blind)} no-overlap lines in the sample")
    assert _top1(blind) > 0.4, (
        f"pure-history regime scored {_top1(blind):.1%}; a text index gets 0% "
        "here, so this is the whole argument for the database")


@needs_aito
@needs_fixture
def test_a_familiar_vendor_is_easier_than_a_first_time_one(scored):
    """Cold start should be measurably harder. If it is not, either the
    split is leaking or the vendor route carries nothing."""
    gen = _generator()
    cold_names = {v[0] for v in gen.VENDORS if v[7]}
    warm = [(l, r) for l, r in scored if l["billing_supplier"] not in cold_names]
    cold = [(l, r) for l, r in scored if l["billing_supplier"] in cold_names]
    if len(cold) < 10 or len(warm) < 10:
        pytest.skip("sample does not contain both warm and cold vendors")
    assert _top1(warm) > _top1(cold), (
        f"warm {_top1(warm):.1%} is not above cold {_top1(cold):.1%} — "
        "suspect a leak in the held-out split")


@needs_aito
@needs_fixture
def test_the_right_answer_is_usually_on_the_shortlist(scored):
    """The view's actual claim: the clerk gets five rows and the answer
    is among them. That is what replaces searching 3200 SKUs."""
    top5 = sum(1 for line, r in scored
               if line["sku"] in [c.sku for c in r[:5]]) / len(scored)
    assert top5 > 0.80, f"top-5 recall {top5:.1%} — the shortlist claim fails"


# ── Layer 3: the explanation, in Aito's own words ───────────────────
#
# The chips on screen are a rendering of `$why`. A rendering can drift
# from what the engine actually said, and it did: the chip list was
# built from `highlight` markers alone, Aito marks only some terms of a
# `$group` (and sometimes none), so a lift-26 factor naming
# "Fazer Konfektyr" was dropped silently and the match looked as if it
# had turned on one rare word. Nothing failed. The screen was just
# quietly less true than the response behind it.


def _why_factors(why: dict | None) -> list[tuple[float, str]]:
    """Every `relatedPropositionLift` in a `$why`, as (lift, proposition)."""
    import json as _json

    out: list[tuple[float, str]] = []

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "relatedPropositionLift":
            out.append((float(node.get("value", 1.0)),
                        _json.dumps(node.get("proposition"), ensure_ascii=False,
                                    sort_keys=True)))
        for child in node.get("factors") or []:
            walk(child)

    walk(why or {})
    return out


@needs_aito
@needs_fixture
def test_the_chips_do_not_drop_evidence_aito_gave(scored, capsys):
    """Every strong factor must survive into the rendered reasons.

    "Strong" is the top five by |lift - 1|, which is what the view
    shows. The assertion is not that the wording matches — it is that a
    factor Aito weighted heavily is represented at all, by its field or
    one of its values. That is the exact failure this test was written
    after.
    """
    import json as _json

    checked = 0
    for line, candidates in scored[:12]:
        if not candidates:
            continue
        top = candidates[0]
        factors = sorted(_why_factors(top.why_raw), key=lambda f: -abs(f[0] - 1.0))
        strong = [f for f in factors[:5] if abs(f[0] - 1.0) >= 0.5]
        if not strong:
            continue
        rendered = " ".join(r["text"] + " " + r.get("field", "")
                            for r in top.reasons).lower()
        for lift, proposition in strong:
            values = [str(v) for v in _json.loads(proposition).values()
                      if not isinstance(v, (dict, list))]
            leaves = _leaf_strings(_json.loads(proposition))
            assert any(leaf.lower() in rendered for leaf in leaves), (
                f"factor lift x{lift:.1f} {proposition} is in Aito's $why but "
                f"nothing in the rendered reasons mentions it: {rendered!r}")
        checked += 1
    if not checked:
        pytest.skip("no strongly-weighted factors in this sample")


def _leaf_strings(prop) -> list[str]:
    """Every scalar leaf of a proposition, as a string."""
    out: list[str] = []
    if isinstance(prop, list):
        for item in prop:
            out += _leaf_strings(item)
    elif isinstance(prop, dict):
        for key, value in prop.items():
            if isinstance(value, (dict, list)):
                out += _leaf_strings(value)
            elif not key.startswith("$"):
                out.append(str(value))
            else:
                out.append(str(value))
    return [o for o in out if o]


@needs_aito
@needs_fixture
def test_print_the_raw_why_for_reading(scored, capsys):
    """Not an assertion — a transcript.

    Run with `-s` to read what Aito actually returns, in its own shape,
    next to the chips derived from it. The two are meant to be
    comparable at a glance; when they stop being, the rendering is
    wrong, not the engine.
    """
    with capsys.disabled():
        shown = 0
        for line, candidates in scored:
            if not candidates or shown >= 2:
                continue
            top = candidates[0]
            print(f"\n  LINE  {line['billing_supplier']} — {line['description']!r}")
            print(f"  MATCH {top.sku} {top.name!r}  p={top.p:.4f}"
                  f"  {'correct' if top.sku == line['sku'] else 'WRONG'}")
            print("  $why, every factor Aito returned:")
            for lift, proposition in sorted(_why_factors(top.why_raw),
                                            key=lambda f: -abs(f[0] - 1.0)):
                print(f"      lift {lift:>10.4f}   {proposition}")
            print("  rendered as:")
            for r in top.reasons:
                print(f"      [{r['kind']:7}] {r['text']}")
            shown += 1

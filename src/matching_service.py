"""Invoice line → catalogue SKU: the match, and the queue it runs in.

A purchase invoice arrives with one row per product and no product id.
The supplier wrote the description in their own words — their order,
their language, often their own article number — and somebody has to
say which of several thousand catalogue rows each line means. At a few
hundred thousand lines a week that is not a task anyone does by hand,
and it is not a mapping table anyone maintains: a new supplier arrives
and the table has no row for them.

Three things about how this is built, all of them deliberate:

**The eval and the view make the same call.** `rank_line` is the only
place that queries, and `src/match_eval.py` imports it. A harness that
issues its own query measures a system nobody ships.

**The unit of work is a batch, not a line.** Invoice lines arrive as
documents on a queue, overnight and in bulk. A screen that matches one
line at a time answers a question nobody asked, so `run_batch` runs the
queue at N workers and reports throughput.

**Nothing posts unattended, and the measurement is why.** The obvious
demo is an auto-post threshold: above the bar the line books itself.
The coverage/precision table says that bar does not exist here — at
the tightest setting the top pick is right 59% of the time, and no AP
team signs off on four wrong lines in ten. So the product is not
automatic posting. It is the *search* that goes away: instead of
hunting a 3200-row catalogue, a clerk gets five ranked rows with the
reasons attached, and confirms. Confident lines arrive pre-filled;
the rest arrive open. Both are a human keystroke, and the honest
version is the one that ships.
"""

import html as html_lib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from src.aito_client import AitoClient, AitoError
from src.why_processor import process_factors

# The evidence a matcher actually has when a line arrives. Deliberately
# not the SKU, and deliberately not `invoice_id` — grouping lines by
# document would leak the answer from siblings, which is a real
# technique but a different claim from the one being measured.
LINE_FEATURES = ("description", "billing_supplier", "unit_of_measure",
                 "unit_price_eur", "quantity")

# The inference preset, set explicitly rather than inherited.
#
# The engines default differently — rep1 to And-only, rep2 to Group
# re-expression — so leaving it unset meant the "rep2 is six points
# behind rep1" reading in this file was comparing two PRESETS as much as
# two engines. Measured on 600 held-out lines against rep2:
#
#     default (group)   top-1 69.3%   warm 85.8%   cold 36.5%
#     and               top-1 75.8%   warm 92.2%   cold 43.0%
#     high (and+group)  top-1 76.2%   warm 92.5%   cold 43.5%
#
# `and` recovers almost all of it for no extra cost — `high` buys a
# further 0.4 points and is measurably slower, which is not a trade
# worth making. Naming it here also means the demo scores the same way
# on both engines, so a v1/v2 comparison is about the engine again.
#
# Note this contradicts the upstream guidance in V2QueryDocs, which says
# And+Group "adds cost without improving accuracy on the corpora". On
# THIS corpus it improves it by 6.9 points, and line matching is the
# case that doc's own ProductMatchingTest book exists for.
INFERENCE_PRESET = "and"

# Generalise candidates by the product's own supplier.
#
# A SKU invoiced nineteen times has thin history of its own. `basedOn`
# lets Aito smooth a factor toward what it knows about products sharing
# that attribute, and — the part that matters on screen — report WHICH
# attribute carried it, as a `prior` inside the factor. Without this
# there are no priors to show at all.
#
# It is a SCORING change, not a display one. Measured on 600 held-out
# lines against rep2 with `and`:
#
#     none                  top-1 75.8%   warm 92.2%   cold 43.0%   127s
#     ["category"]          top-1 76.7%   warm 93.0%   cold 44.0%   148s
#     ["supplier"]          top-1 76.8%   warm 92.2%   cold 46.0%   176s
#     ["category","supplier"] 75.8%       warm 92.0%   cold 43.5%   163s
#
# `supplier` for the cold-start gain: the one place this case is
# genuinely weak. Both attributes together is worse than either — more
# generalisation is not more signal. The cost is real (~40% more time
# per query), which is why this is named here rather than switched on
# everywhere.
#
# Confirmed on the full held-out 2000 rather than left on the sample:
#
#     rep2, and             overall   warm    cold
#     basedOn none            77.1%   91.1%   49.2%
#     basedOn ["supplier"]    78.8%   93.1%   50.1%
#
# The sample had put cold at +3 and it came in at +0.9. The direction
# held on all three and the sample's size did not, which is the usual
# reason a number here is re-run at full size before it is quoted.
#
# **rep2 only, and that is measured, not assumed.** The same argument
# against rep1 on the same 2000 lines and the same build:
#
#     rep1                  overall   warm    cold
#     basedOn none            80.8%   90.5%   61.3%
#     basedOn ["supplier"]    70.6%   85.4%   41.1%
#
# Ten points overall and TWENTY on cold start — the opposite sign and
# an order of magnitude more of it. The two engines do not mean the
# same thing by the argument, so the demo cannot send it to both and
# call the query shared. This is the one place a service module here
# branches on the engine rather than speaking one dialect, and the
# numbers above are why it earns the exception.
BASED_ON = ["supplier"]

# The vendor's own attributes, reached through the link on
# `billing_supplier`. They matter most exactly where the vendor name is
# worthless: a vendor invoicing for the FIRST time has no history under
# its own name, but its city and market position are known from the
# vendor master and are shared with vendors that do have history. That
# is what lets a cold vendor inherit "a premium importer in Tallinn
# sells rows like these" instead of starting from the base rate.
VENDOR_FEATURES = ("city", "position", "sells_origin", "sells_grade")

# Catalogue columns worth carrying back with the ranking. `sku` links to
# `products.sku`, so Aito returns the matched row's own columns — but
# only when they are named, because naming any `select` (which this
# client must, for `$why`) replaces the default whole-row projection.
CATALOGUE_FIELDS = ["name", "category", "supplier", "unit_price",
                    "unit_of_measure"]

# Above this the top candidate arrives pre-filled — still in front of a
# human, just already chosen. Read off the coverage/precision table in
# `./do match-eval` rather than picked by taste: at p ≥ 0.50 the top
# pick covers 22% of lines and is right 59% of the time, which is worth
# pre-filling and nowhere near worth posting.
PRESELECT_THRESHOLD = 0.50


@dataclass
class Candidate:
    """One catalogue row Aito put forward, with its case for itself."""
    sku: str
    name: str
    category: str | None
    supplier: str | None
    unit_price: float | None
    unit_of_measure: str | None
    p: float
    reasons: list[dict] = field(default_factory=list)
    # Aito's `$why` exactly as it arrived. Not serialised to the
    # frontend — it is here so a test can compare what the engine said
    # against what the chips show, which is the drift that hid a
    # lift-26 factor for a week.
    why_raw: dict | None = None

    def to_dict(self) -> dict:
        return {
            "sku": self.sku, "name": self.name, "category": self.category,
            "supplier": self.supplier, "unit_price": self.unit_price,
            "unit_of_measure": self.unit_of_measure,
            "p": self.p, "reasons": self.reasons,
        }


@dataclass
class MatchedLine:
    """An invoice line after matching, and where it was routed."""
    line_id: str
    invoice_id: str
    billing_supplier: str
    description: str
    quantity: float
    unit_of_measure: str | None
    unit_price_eur: float | None
    line_amount_eur: float | None
    candidates: list[Candidate]
    ms: float
    truth: str | None = None          # held-out label, when there is one
    truth_name: str | None = None     # and what the catalogue calls it
    cold: bool = False                # supplier absent from the history

    @property
    def decision(self) -> str:
        top = self.candidates[0].p if self.candidates else 0.0
        return "prefilled" if top >= PRESELECT_THRESHOLD else "open"

    def to_dict(self) -> dict:
        top = self.candidates[0] if self.candidates else None
        return {
            "line_id": self.line_id, "invoice_id": self.invoice_id,
            "billing_supplier": self.billing_supplier,
            "description": self.description, "quantity": self.quantity,
            "unit_of_measure": self.unit_of_measure,
            "unit_price_eur": self.unit_price_eur,
            "line_amount_eur": self.line_amount_eur,
            "candidates": [c.to_dict() for c in self.candidates],
            "decision": self.decision, "ms": round(self.ms),
            "cold": self.cold,
            # The label is shown because these lines are held out and it
            # is the only way a viewer can tell a confident match from a
            # confidently wrong one. A production queue has no truth
            # column; a demo that hides it is asking to be trusted.
            "truth": self.truth,
            "truth_name": self.truth_name,
            "correct": None if self.truth is None or top is None
                       else top.sku == self.truth,
            # Half the catalogue shares a name with another row. A pick
            # whose name is identical to the right answer's is not a
            # miss the ranker could have avoided — nothing in the data
            # separates them. Shown as its own outcome rather than
            # counted as correct: it is a weaker claim and it says so.
            "same_name": bool(
                top is not None and self.truth_name
                and top.sku != self.truth
                and top.name == self.truth_name),
        }


# Aito wraps matched terms in guillemets and paints an absent one red.
# Those sentinels are the interesting part of a highlight — they say
# WHICH words carried the match — so they are parsed rather than shown.
_MATCHED = re.compile(r"\u00ab(.+?)\u00bb")
_ABSENT = re.compile(r"<font[^>]*>(.*?)</font>")


def _terms(html: str) -> list[str]:
    """The terms Aito highlighted, in the order it highlighted them.

    Unescaped, because the highlight arrives as markup and a chip
    reading `L'Or&eacute;al` tells a viewer the demo is broken.
    """
    return [html_lib.unescape(t).strip()
            for t in _MATCHED.findall(html or "") if t.strip()]


def _proposition_terms(prop: object) -> list[tuple[str, str]]:
    """The (field, value) leaves of a `$why` proposition.

    Needed because `highlight` is not a reliable inventory of what a
    factor is about. Aito marks only some terms of a `$group` — for one
    real line it marked `cordial` out of `{cordial, Apple}` and marked
    nothing at all out of `{Konfektyr, Fazer}` — so a chip list built
    from the markers alone dropped a lift-26 factor entirely and left
    the match looking as if it had turned on one rare word.
    """
    out: list[tuple[str, str]] = []

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key.startswith("$"):
                walk(value)
            elif isinstance(value, dict):
                # {"description": {"$has": "cordial"}}
                for inner in value.values():
                    out.append((key, str(inner)))
            else:
                out.append((key, str(value)))

    walk(prop)
    return out


def _chip_terms(pairs: list[tuple[str, str]]) -> list[str]:
    """Render a factor's (field, value) leaves for one chip.

    A quoted word is self-explanatory when it came out of the
    description. Out of `quantity` it is the chip `"6"`, which tells
    nobody anything, so those carry their field — per LEAF, not per
    chip: a group can span columns, and labelling the whole group with
    the first field attributed values to columns they never came from.

    The linked prefix is written once. A vendor group names four
    `billing_supplier.*` columns, and repeating the prefix on each one
    made a chip so long it pushed the rest of the evidence off the row.
    """
    out: list[str] = []
    last_root: str | None = None
    for field, value in pairs:
        if field == "description":
            out.append(f'"{value}"')
            last_root = None
            continue
        root, _, leaf = field.partition(".")
        if leaf and root == last_root:
            out.append(f"{leaf.replace('_', ' ')} {value}")
        elif leaf:
            out.append(
                f"{root.replace('_', ' ')} {leaf.replace('_', ' ')} {value}")
            last_root = root
        else:
            out.append(f"{field.replace('_', ' ')} {value}")
            last_root = field
    return out


def _reasons(hit: dict, line: dict) -> list[dict]:
    """The case for one candidate, with each claim's provenance kept.

    `aito` — Aito's `$why` named this as evidence FOR the row. `against`
    — it named it as evidence against, which is worth showing because a
    shortlist where every entry looks equally endorsed is not a
    shortlist. `match` — it agrees with the invoice line, computed here
    and argued by nobody.

    Painting the three alike would credit the database with reasoning it
    did not do, which is the failure this repo is under a ticket about.
    """
    out: list[dict] = []
    processed = process_factors(hit.get("$why"), hit.get("$p", 0.0))
    for lift in processed.get("lifts", [])[:5]:
        terms, fields = [], []
        for highlight in lift.get("highlights") or []:
            found = _terms(highlight.get("html", ""))
            # One field PER TERM. It used to be one per highlight, which
            # left the two lists a different length, and the moment they
            # were zipped to label each value with its own column the
            # shorter one silently truncated the chip to its first term.
            terms.extend(found)
            fields.extend([highlight.get("field", "")] * len(found))
            if not found and _ABSENT.search(highlight.get("html", "")):
                fields.append(highlight.get("field", ""))
        # The proposition is the COMPLETE inventory of what a factor is
        # about; `highlight` is not. Aito marks only some members of a
        # group and sometimes none, so a chip built from the markers
        # rendered `{TV, ea, 55"}` as "unit of measure ea" and a
        # five-member vendor group as a single supplier name — the
        # factor was on screen and most of its content was not.
        #
        # Highlights still win on ties: where the two agree on how many
        # terms there are, the marked form is the one that shows WHICH
        # token in the description matched.
        leaves = _proposition_terms(lift.get("proposition"))
        if len(leaves) > len(terms):
            terms = [v for _, v in leaves]
            fields = [f for f, _ in leaves]
        if not terms and not fields:
            continue
        supports = lift.get("lift", 1.0) >= 1.0
        # A quoted word is self-explanatory when it came out of the
        # description. Out of `quantity` it is the chip `"6"`, which
        # tells nobody anything, so those carry their field.
        field = fields[0] if fields else ""
        if terms:
            text = " · ".join(_chip_terms(list(zip(fields, terms))[:4]))
        else:
            text = ", ".join(f.replace("_", " ") for f in fields if f)

        # A `prior` means Aito could not judge this candidate from its
        # own history and leaned on what it knows about rows sharing an
        # attribute — see BASED_ON. That is a different KIND of claim
        # from the factor it hangs under: a generalisation, not direct
        # evidence, and painting the two alike would credit the database
        # with having seen something it inferred. It is NESTED rather
        # than listed alongside because the two only mean anything
        # together; a flat list lets a wrap put "via supplier Berner Oy"
        # under a factor it has nothing to do with.
        priors = []
        for prior in (lift.get("prior") or {}).get("factors") or []:
            # A prior of 1.0 moved nothing. Same reason the near-1.0
            # lifts are dropped upstream: a chip reads as evidence, and
            # a fallback that changed no number is not evidence.
            value = prior.get("value")
            if not isinstance(value, (int, float)) or abs(value - 1.0) < 0.05:
                continue
            leaves = _proposition_terms(prior.get("proposition"))
            if not leaves:
                continue
            named = " · ".join(
                f"{f.replace('_', ' ')} {v}" for f, v in leaves[:2])
            priors.append({"text": f"via {named}", "lift": round(value, 3)})

        out.append({
            "kind": "aito" if supports else "against",
            "text": text,
            "field": field,
            "lift": lift.get("lift"),
            "priors": priors[:2],
        })

    # Computed here, not by Aito. Both are things a clerk checks by eye,
    # and neither is evidence the database put forward.
    if (hit.get("unit_of_measure")
            and hit["unit_of_measure"] == line.get("unit_of_measure")):
        out.append({"kind": "match", "text": f"unit {hit['unit_of_measure']}",
                    "field": "unit_of_measure", "lift": None,
                    "priors": []})

    list_price, invoiced = hit.get("unit_price"), line.get("unit_price_eur")
    if list_price and invoiced:
        drift = abs(float(invoiced) - float(list_price)) / float(list_price)
        if drift <= 0.15:
            out.append({"kind": "match", "field": "unit_price", "lift": None,
                        "priors": [],
                        "text": f"price within {drift:.0%} of list"})
    return out


def rank_line(client: AitoClient, line: dict, limit: int = 5,
              vendor: dict | None = None) -> tuple[list[Candidate], float]:
    """Rank catalogue SKUs for one invoice line. One query, no training.

    This is the whole matcher. `sku` links to `products.sku`, so the
    prediction traverses the link and hands back catalogue rows with
    their own columns — which is what lets the shortlist argue for
    itself rather than showing five bare identifiers.
    """
    where = {f: line[f] for f in LINE_FEATURES if line.get(f) is not None}
    # Linked-field clauses on the vendor. `billing_supplier` links to
    # `vendors`, so these are properties of WHO IS INVOICING, not of the
    # line — and they are the only thing a first-time vendor brings.
    for field in VENDOR_FEATURES:
        if vendor and vendor.get(field) is not None:
            where[f"billing_supplier.{field}"] = vendor[field]
    started = time.perf_counter()
    try:
        response = client.predict("invoice_lines", where, "sku", limit=limit,
                                  select_extra=CATALOGUE_FIELDS,
                                  ai=INFERENCE_PRESET,
                                  based_on=(BASED_ON
                                            if client.api_version == "v2"
                                            else None))
    except AitoError:
        return [], (time.perf_counter() - started) * 1000
    elapsed = (time.perf_counter() - started) * 1000

    candidates = []
    for hit in response.get("hits") or []:
        if hit.get("$value") is None:
            continue
        candidates.append(Candidate(
            sku=str(hit["$value"]),
            name=hit.get("name") or "",
            category=hit.get("category"),
            supplier=hit.get("supplier"),
            unit_price=hit.get("unit_price"),
            unit_of_measure=hit.get("unit_of_measure"),
            p=hit.get("$p", 0.0),
            reasons=_reasons(hit, line),
            why_raw=hit.get("$why"),
        ))
    return candidates, elapsed


@dataclass
class BatchResult:
    """What a queue run looks like from the outside."""
    lines: list[MatchedLine]
    wall_s: float
    workers: int
    server_ms_median: float

    def to_dict(self) -> dict:
        n = len(self.lines)
        rate = n / self.wall_s if self.wall_s else 0.0
        prefilled = sum(1 for line in self.lines
                        if line.decision == "prefilled")
        labelled = [line for line in self.lines if line.truth is not None]
        prefilled_labelled = [line for line in labelled
                              if line.decision == "prefilled"]
        top1 = sum(1 for line in labelled
                   if line.candidates and line.candidates[0].sku == line.truth)
        top5 = sum(1 for line in labelled
                   if line.truth in [c.sku for c in line.candidates[:5]])
        prefilled_right = sum(1 for line in prefilled_labelled
                              if line.candidates[0].sku == line.truth)
        return {
            "lines": [line.to_dict() for line in self.lines],
            "batch": {
                "n": n,
                "wall_s": round(self.wall_s, 1),
                "workers": self.workers,
                "rows_per_s": round(rate, 1),
                "rows_per_week": round(rate * 3600 * 24 * 7),
                "server_ms_median": round(self.server_ms_median),
                "prefilled": prefilled,
                "open": n - prefilled,
                "threshold": PRESELECT_THRESHOLD,
                # Scored on this batch only — a few hundred rows, so it
                # moves run to run. The stable figures are in
                # `./do match-eval` over the full held-out 2000.
                "top1": round(top1 / len(labelled), 3) if labelled else None,
                "top5": round(top5 / len(labelled), 3) if labelled else None,
                "prefill_precision": (
                    round(prefilled_right / len(prefilled_labelled), 3)
                    if prefilled_labelled else None),
            },
        }


def run_batch(client: AitoClient, lines: list[dict], workers: int = 8,
              cold_suppliers: frozenset[str] = frozenset(),
              names: dict[str, str] | None = None,
              vendors: dict[str, dict] | None = None) -> BatchResult:
    """Run the queue. Concurrency is the lever, because the constraint
    on this shape of work is throughput and not the latency of any one
    line — nobody is waiting at a screen for an overnight invoice run."""
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        ranked = list(pool.map(
            lambda line: rank_line(
                client, line,
                vendor=(vendors or {}).get(line["billing_supplier"])), lines))
    wall = time.perf_counter() - started

    matched = [
        MatchedLine(
            line_id=line["line_id"], invoice_id=line["invoice_id"],
            billing_supplier=line["billing_supplier"],
            description=line["description"], quantity=line["quantity"],
            unit_of_measure=line.get("unit_of_measure"),
            unit_price_eur=line.get("unit_price_eur"),
            line_amount_eur=line.get("line_amount_eur"),
            candidates=candidates, ms=ms, truth=line.get("sku"),
            truth_name=(names or {}).get(line.get("sku", "")),
            cold=line["billing_supplier"] in cold_suppliers,
        )
        for (candidates, ms), line in zip(ranked, lines)
    ]
    times = sorted(line.ms for line in matched) or [0.0]
    return BatchResult(lines=matched, wall_s=wall, workers=workers,
                       server_ms_median=times[len(times) // 2])


# ── The queue the view runs against ──────────────────────────────
#
# These lines were HELD OUT of the load. Nothing on this screen was in
# the database when the question was asked, which is the only way a
# confidence number on a demo means anything.

_QUEUE: dict[str, tuple[list[dict], frozenset[str], dict[str, str],
                        dict[str, dict]]] = {}


def queue_for(client: AitoClient, tenant: str
              ) -> tuple[list[dict], frozenset[str], dict[str, str],
                         dict[str, dict]]:
    """Held-out lines, which vendors are cold, SKU names, vendor master.

    Read from AITO, not from `data/`. The first version read the fixture
    files directly, which worked on a laptop and produced an empty queue
    in production: `data/` is gitignored, so a deployed container has no
    fixtures at all. Every other view in this demo gets its data from
    the database; this one now does too.

    The held-out rows live in `invoice_lines_holdout`, which is
    deliberately link-free — see the schema comment. They are storage
    the view reads, not evidence the ranker can reach, so scoring them
    still measures generalisation rather than recall.

    "Cold" is derived by comparing the two halves rather than declared,
    so it cannot drift out of step with the data.
    """
    if tenant in _QUEUE:
        return _QUEUE[tenant]

    def rows(table: str, limit: int) -> list[dict]:
        try:
            return client.search(table, {}, limit=limit).get("hits") or []
        except AitoError:
            return []

    held_out = rows("invoice_lines_holdout", 2000)
    if not held_out:
        # This tenant has no invoice lines — the view does not apply to
        # it and the nav hides it. A deep link gets an empty queue
        # rather than a 500.
        _QUEUE[tenant] = ([], frozenset(), {}, {})
        return _QUEUE[tenant]

    # Only the vendor column is needed from the training half, and it is
    # a small distinct set — but Aito has no DISTINCT, so this reads a
    # capped sample. A vendor that appears in 60000 training rows will
    # be in the first few thousand; one that is genuinely absent stays
    # absent, which is the only thing "cold" turns on.
    seen = {line.get("billing_supplier") for line in rows("invoice_lines", 4000)}
    cold = frozenset({line["billing_supplier"] for line in held_out} - seen)
    names = {p["sku"]: p.get("name", "")
             for p in rows("products", 4000) if p.get("sku")}
    vendors = {v["vendor"]: v for v in rows("vendors", 200) if v.get("vendor")}
    _QUEUE[tenant] = (held_out, cold, names, vendors)
    return _QUEUE[tenant]


# Measured by `./do match-eval` over the held-out split, 2026-09-06,
# on the reformulated corpus. Restated here because the view quotes
# them, and a screen quoting a number with no provenance is how a stale
# figure gets requoted after the thing it measured has changed.
#
# Split by engine ON PURPOSE. rep1 and rep2 answer this query
# differently — rep2 is ahead in every regime — so a single set of
# numbers would be wrong for whichever engine the demo is not running.
# Re-run the harness and update the matching block together, or not at
# all.
_MEASURED_SHARED = {
    "measured_on": "2026-09-14",
    # The engine AND the query the numbers below describe. Two of them
    # moved between builds this month, and `config.ai` / `basedOn` each
    # move them further than a build did — so a figure here without all
    # three attached is a figure nobody can check.
    "engine_build":
        '2.8.4 (6979ad71dfd5), config.ai=and, basedOn=["supplier"] on rep2',
    "n": 2000,
    "catalogue_skus": 3200,
    "labelled_lines_loaded": 60000,
    "baseline": 1 / 3200,
    # Zero, now. Every catalogue row has a distinct name, so nothing is
    # unanswerable by construction and the ceiling is 100%.
    "shared_name_share": 0.0,
    "ceiling_top1": 1.0,
    "ceiling_top5": 1.0,
    "floor_top1": 0.478,
    "floor_top5": 0.770,
    "note": (
        "3200 catalogue SKUs, not 20 000 — a real catalogue of that size "
        "is a harder problem and this number should not be read as "
        "covering it. Generic retail goods, not any customer's data."
    ),
}

MEASURED_BY_ENGINE: dict[str, dict] = {
    "v1": {
        "engine": "rep1 (v1)",
        "overall_top1": 0.808, "overall_top5": 0.928, "overall_top1_name": 0.808,
        "warm_top1": 0.905, "warm_top5": 0.981, "warm_top1_name": 0.905,
        "cold_top1": 0.613, "cold_top5": 0.823, "cold_top1_name": 0.613,
        "throughput_rows_per_s": 3.7, "throughput_workers": 10,
        "curve": [
            {"bar": 0.05, "coverage": 0.999, "precision": 0.808},
            {"bar": 0.10, "coverage": 0.998, "precision": 0.809},
            {"bar": 0.20, "coverage": 0.991, "precision": 0.814},
            {"bar": 0.35, "coverage": 0.964, "precision": 0.834},
            {"bar": 0.50, "coverage": 0.907, "precision": 0.865},
        ],
        "regimes": [
            {"overlap": "0%", "share": 0.057, "aito": 0.858, "tfidf": 0.0},
            {"overlap": "1-33%", "share": 0.010, "aito": 0.650, "tfidf": 0.0},
            {"overlap": "34-66%", "share": 0.224, "aito": 0.692, "tfidf": 0.112},
            {"overlap": "67-99%", "share": 0.229, "aito": 0.710, "tfidf": 0.391},
            {"overlap": "100%", "share": 0.480, "aito": 0.906, "tfidf": 0.757},
        ],
    },
    "v2": {
        "engine": "rep2 (v2)",
        "overall_top1": 0.788, "overall_top5": 0.899, "overall_top1_name": 0.788,
        "warm_top1": 0.931, "warm_top5": 0.979, "warm_top1_name": 0.931,
        "cold_top1": 0.501, "cold_top5": 0.739, "cold_top1_name": 0.501,
        "throughput_rows_per_s": 3.1, "throughput_workers": 8,
        "curve": [
            {"bar": 0.05, "coverage": 1.000, "precision": 0.788},
            {"bar": 0.10, "coverage": 0.996, "precision": 0.790},
            {"bar": 0.20, "coverage": 0.977, "precision": 0.803},
            {"bar": 0.35, "coverage": 0.909, "precision": 0.834},
            {"bar": 0.50, "coverage": 0.846, "precision": 0.868},
        ],
        "regimes": [
            {"overlap": "0%", "share": 0.057, "aito": 0.885, "tfidf": 0.0},
            {"overlap": "1-33%", "share": 0.010, "aito": 0.650, "tfidf": 0.0},
            {"overlap": "34-66%", "share": 0.224, "aito": 0.681, "tfidf": 0.112},
            {"overlap": "67-99%", "share": 0.229, "aito": 0.653, "tfidf": 0.391},
            {"overlap": "100%", "share": 0.480, "aito": 0.893, "tfidf": 0.757},
        ],
    },
}


def measured_for(api_version: str) -> dict:
    """The measured block for the engine actually answering the queries."""
    engine = MEASURED_BY_ENGINE.get(api_version) or MEASURED_BY_ENGINE["v1"]
    return {**_MEASURED_SHARED, **engine}


def batch(client: AitoClient, tenant: str, size: int = 40, workers: int = 8,
          offset: int = 0) -> dict:
    """One run of the queue, measured."""
    measured = measured_for(client.api_version)
    lines, cold, names, vendors = queue_for(client, tenant)
    if not lines:
        return {"lines": [], "batch": None, "measured": measured,
                "available": 0}
    window = lines[offset % max(len(lines), 1):][:size]
    result = run_batch(client, window, workers=workers, cold_suppliers=cold,
                       names=names, vendors=vendors)
    payload = result.to_dict()
    payload["measured"] = measured
    payload["available"] = len(lines)
    payload["cold_suppliers"] = sorted(cold)
    return payload

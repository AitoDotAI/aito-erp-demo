"""Measure invoice-line → catalogue-SKU matching, before demoing it.

    ./do match-eval [--limit=N] [--tenant=aurora]

The order is prototype → evaluate → demo, and it is deliberate. A demo
built first and measured afterwards is how a screen ships showing a
confident number nobody had checked. So this runs against a held-out
half that was never loaded into Aito, and it reports:

  * **top-1 and top-5** — table stakes. Whether the right catalogue row
    is the answer, and whether it is at least on the shortlist.
  * **cold start, as its own number** — accuracy on billing suppliers
    that appear nowhere in the loaded history. This is the argument.
    A supplier invoicing for the first time has no identifier history,
    so the match has to come from the description text against the
    product's own metadata. An overall figure that silently averages
    these in is a figure that flatters.
  * **a random baseline** — 1/|catalogue|. Accuracy means nothing
    without the number it has to beat.
  * **ambiguity** — how often the true SKU's name is shared by other
    catalogue rows. That is the ceiling on top-1, and it decides
    whether the honest output is an answer or a shortlist for a human.
  * **coverage and precision at a confidence bar** — the number the
    buying question is actually about. Not "how accurate is it" but
    "how much of this comes off a clerk's desk, and how wrong is it
    when it does". A matcher that is 25% accurate overall but 95%
    accurate on the quarter it is confident about is a useful matcher;
    a single blended figure hides exactly that.
  * **throughput** — rows per second at a given concurrency, because
    the delivery shape for this case is a queue and the constraint is
    throughput, not p50. Measured against `shared.aito.ai`: ~280 ms
    median for a single request, saturating at ~5.4 rows/s past four
    workers. Past that point per-request latency rises in proportion to
    the worker count, which is the signature of a server queue rather
    than of parallelism — so the lever is instance sizing, not
    concurrency, and a throughput claim should say which one it is.

No model is trained anywhere in this file. The rows were inserted; the
predictions are queries.
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from src.aito_client import AitoClient
from src.config import TenantId, load_config
from src.match_baseline import REGIMES, TfIdfCatalogue, ceiling, regime
from src.matching_service import Candidate, LINE_FEATURES, rank_line

DATA = Path(__file__).resolve().parent.parent / "data"

@dataclass
class Bucket:
    """Scores for one slice of the test set."""
    name: str
    n: int = 0
    top1: int = 0
    top1_name: int = 0
    top5: int = 0
    no_answer: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def add(self, ranked: list["Candidate"], truth: str, ms: float,
            truth_name: str | None = None) -> None:
        self.n += 1
        self.latencies_ms.append(ms)
        if not ranked:
            self.no_answer += 1
            return
        if ranked[0].sku == truth:
            self.top1 += 1
        # Half the catalogue shares a name with another row. When the
        # top pick is one of those twins, the matcher did not fail —
        # nothing in the data could have separated them, and a clerk
        # looking at two rows with the same name would not have either.
        # Scored separately, never blended into top-1: it is a weaker
        # claim and it has to be labelled as one.
        if truth_name and ranked[0].name == truth_name:
            self.top1_name += 1
        if truth in [c.sku for c in ranked[:5]]:
            self.top5 += 1

    def report(self) -> str:
        if not self.n:
            return f"  {self.name:34} (no rows)"
        ordered = sorted(self.latencies_ms)
        median = ordered[len(ordered) // 2]
        return (f"  {self.name:34} top-1 {self.top1 / self.n:6.1%}   "
                f"(+name {self.top1_name / self.n:5.1%})   "
                f"top-5 {self.top5 / self.n:6.1%}   "
                f"n={self.n:<5} median {median:5.0f} ms"
                + (f"   no answer {self.no_answer}" if self.no_answer else ""))


def _coverage_precision(scored: list[tuple[list[Candidate], str]]) -> list[str]:
    """What auto-posting at each confidence bar would actually cost.

    `coverage` is the share of lines whose top candidate clears the bar;
    `precision` is how often that candidate is right. This is the table
    the routing threshold is read off — raising the bar buys precision
    and pays for it in coverage, and the trade is the product decision.
    A demo that picks a threshold without printing this is picking one
    by taste.
    """
    rows = ["  auto-post bar    coverage   precision   lines auto   wrong"]
    total = len(scored)
    for bar in (0.02, 0.05, 0.10, 0.20, 0.35, 0.50):
        above = [(c, truth) for c, truth in scored if c and c[0].p >= bar]
        if not above:
            rows.append(f"  p ≥ {bar:<12.2f}      0.0%          —            0       0")
            continue
        right = sum(1 for c, truth in above if c[0].sku == truth)
        rows.append(f"  p ≥ {bar:<12.2f} {len(above) / total:6.1%}   "
                    f"{right / len(above):8.1%}   {len(above):9}   "
                    f"{len(above) - right:5}")
    return rows


def _ambiguity(products: list[dict]) -> tuple[int, float]:
    """How many catalogue rows share their name with another row.

    The ceiling on top-1: where two SKUs are called the same thing, no
    amount of description matching can separate them, and the honest
    output is a shortlist rather than an answer.
    """
    names = Counter(p["name"] for p in products if p.get("name"))
    shared = sum(count for count in names.values() if count > 1)
    return shared, shared / max(len(products), 1)


def run(tenant: TenantId = "aurora", limit: int | None = None,
        workers: int = 8) -> dict:
    config = load_config()
    creds = config.creds_for(tenant)
    client = AitoClient.from_creds(creds.api_url, creds.api_key,
                                   api_version=config.api_version)

    test = json.load(open(DATA / tenant / "invoice_lines_holdout.json"))
    train = json.load(open(DATA / tenant / "invoice_lines.json"))
    products = json.load(open(DATA / tenant / "products.json"))
    vendors = {v["vendor"]: v
               for v in json.load(open(DATA / tenant / "vendors.json"))}
    if limit:
        test = test[:limit]

    seen_suppliers = {line["billing_supplier"] for line in train}
    catalogue_size = len({p["sku"] for p in products})

    overall = Bucket("overall")
    warm = Bucket("supplier seen before")
    cold = Bucket("COLD START — supplier never seen")
    by_supplier: dict[str, Bucket] = {}

    # Run it the way it would actually run: a queue with workers, not a
    # row at a time. Throughput is the constraint for this case, and a
    # serial harness would report a number nobody would deploy.
    print(f"  scoring {len(test)} lines at {workers} workers…", flush=True)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(
            lambda line: (rank_line(client, line,
                                    vendor=vendors.get(line["billing_supplier"])),
                          line), test))
    wall = time.perf_counter() - started

    name_of = {p["sku"]: p.get("name") for p in products}
    for (ranked, ms), line in results:
        truth = line["sku"]
        truth_name = name_of.get(truth)
        supplier = line["billing_supplier"]
        overall.add(ranked, truth, ms, truth_name)
        bucket = warm if supplier in seen_suppliers else cold
        bucket.add(ranked, truth, ms, truth_name)
        by_supplier.setdefault(supplier, Bucket(supplier)).add(
            ranked, truth, ms, truth_name)

    scored = [(ranked, line["sku"]) for (ranked, _), line in results]
    shared, shared_share = _ambiguity(products)
    baseline = 1 / catalogue_size

    print()
    print(f"Invoice line → catalogue SKU, {tenant}")
    print(f"  catalogue {catalogue_size} SKUs · "
          f"{len(train)} labelled lines loaded · {len(test)} held out")
    print(f"  random baseline: {baseline:.2%}")
    print()
    print("  top-1 is the exact SKU. (+name) also counts a pick whose "
          "catalogue name is identical\n  to the right answer's — an "
          "ambiguity in the data, not a match the ranker made.")
    print()
    print(overall.report())
    print(warm.report())
    print(cold.report())
    print()
    print("  by billing supplier (cold marked *):")
    for name, bucket in sorted(by_supplier.items(),
                               key=lambda kv: -kv[1].top1 / max(kv[1].n, 1)):
        mark = " " if name in seen_suppliers else "*"
        print(f"  {mark}" + bucket.report()[2:])
    # The floor and the ceiling, both computed locally. A single
    # accuracy number is unreadable without them.
    index = TfIdfCatalogue(products)
    base1 = base5 = 0
    for line in test:
        ranked_names = index.rank(line["description"])
        if ranked_names and ranked_names[0] == line["sku"]:
            base1 += 1
        if line["sku"] in ranked_names[:5]:
            base5 += 1
    ceil1, ceil5 = ceiling(products, test)
    print()
    print(f"  {'CEILING — a perfect name matcher':34} "
          f"top-1 {ceil1:6.1%}   top-5 {ceil5:6.1%}")
    print(f"  {'FLOOR — TF-IDF over product names':34} "
          f"top-1 {base1 / len(test):6.1%}   top-5 {base5 / len(test):6.1%}")
    print("  The ceiling is where identical catalogue names stop anyone. "
          "The floor needs\n  no database at all. Aito has to sit above the "
          "floor to be earning its place.")
    # Per regime, because a blended figure over a corpus whose
    # composition we chose is worthless whichever way it points.
    names = {p["sku"]: p.get("name", "") for p in products}
    per: dict[str, list[bool]] = {r: [] for r in REGIMES}
    per_base: dict[str, list[bool]] = {r: [] for r in REGIMES}
    for (ranked, _), line in results:
        r = regime(line["description"], names.get(line["sku"], ""))
        per[r].append(bool(ranked) and ranked[0].sku == line["sku"])
        base = index.rank(line["description"])
        per_base[r].append(bool(base) and base[0] == line["sku"])
    print()
    print("  by regime — how much of the catalogue name survives into the line:")
    print(f"  {'overlap':10} {'n':>5} {'share':>7}   {'Aito':>7} {'TF-IDF':>7}")
    for r in REGIMES:
        hits = per[r]
        if not hits:
            continue
        print(f"  {r:10} {len(hits):>5} {len(hits) / len(test):>7.1%}   "
              f"{sum(hits) / len(hits):>7.1%} "
              f"{sum(per_base[r]) / len(per_base[r]):>7.1%}")
    print("  A 100% line is a LOOKUP and a text index should win it. The rows")
    print("  above it are where history is the only route to the answer.")
    print()
    for row in _coverage_precision(scored):
        print(row)
    print()
    print(f"  ceiling check: {shared} of {catalogue_size} catalogue rows "
          f"({shared_share:.1%}) share a name with another row — where two "
          f"SKUs\n  are called the same thing, top-1 cannot separate them and "
          f"a shortlist is the honest output.")
    if overall.n:
        print(f"  lift over random: {overall.top1 / overall.n / baseline:.0f}x")
    rate = len(test) / wall if wall else 0
    print(f"  throughput: {rate:.1f} rows/s at {workers} workers "
          f"({len(test)} rows in {wall:.0f}s) — "
          f"{rate * 3600 * 24 * 7 / 1000:.0f}k rows/week at this rate.")
    print("  One request at a time the median is ~280 ms (p95 ~430 ms). "
          "Throughput saturates at\n  ~5.4 rows/s past FOUR workers — beyond "
          "that, per-request latency grows in step\n  with the worker count "
          "(263 / 738 / 1476 / 2883 ms at 1 / 4 / 8 / 16), which is a queue,\n"
          "  not parallelism. More workers is not the lever; instance sizing "
          "is.")

    # Named for the run that produced it. A 400-row spot check
    # silently overwriting the full 2000-row dump is exactly the kind
    # of quiet substitution that makes a number untraceable later.
    dump = (DATA / tenant /
            f"match_eval_{config.api_version}_n{len(test)}.json")
    with open(dump, "w") as f:
        json.dump([{"line_id": line["line_id"], "truth": line["sku"],
                    "supplier": line["billing_supplier"],
                    "ranked": [{"sku": c.sku, "name": c.name, "p": c.p}
                               for c in ranked], "ms": ms}
                   for (ranked, ms), line in results], f)
    print(f"  raw run written to {dump.relative_to(DATA.parent)} — "
          f"a new metric should not cost another pass.")

    return {
        "overall_top1": overall.top1 / max(overall.n, 1),
        "cold_top1": cold.top1 / max(cold.n, 1),
        "baseline": baseline,
    }


def main() -> None:
    limit = None
    workers = 8
    tenant: TenantId = "aurora"
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
        elif arg.startswith("--workers="):
            workers = int(arg.split("=", 1)[1])
        elif arg.startswith("--tenant="):
            tenant = arg.split("=", 1)[1]  # type: ignore[assignment]
    run(tenant, limit, workers)


if __name__ == "__main__":
    main()

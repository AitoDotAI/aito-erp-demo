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
  * **throughput** — rows per second at a given concurrency, because
    the delivery shape for this case is a queue and the constraint is
    throughput, not p50. Wall-clock per row from a laptop is mostly
    network: measured against `shared.aito.ai`, Aito's own
    `x-aitoai-response-time` is ~420 ms while the round trip is
    ~1.6 s. The server figure is the one that scales with workers;
    the round trip is an artefact of where this is run from.

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

from src.aito_client import AitoClient, AitoError
from src.config import TenantId, load_config

DATA = Path(__file__).resolve().parent.parent / "data"

# The evidence a matcher actually has when a line arrives. Deliberately
# not the SKU, obviously, and deliberately not `invoice_id` — grouping
# would leak the answer from sibling lines on the same document, which
# is a real technique but a different claim from the one being measured.
LINE_FEATURES = ("description", "billing_supplier", "unit_of_measure",
                 "unit_price_eur", "quantity")


@dataclass
class Bucket:
    """Scores for one slice of the test set."""
    name: str
    n: int = 0
    top1: int = 0
    top5: int = 0
    no_answer: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def add(self, ranked: list[str], truth: str, ms: float) -> None:
        self.n += 1
        self.latencies_ms.append(ms)
        if not ranked:
            self.no_answer += 1
            return
        if ranked[0] == truth:
            self.top1 += 1
        if truth in ranked[:5]:
            self.top5 += 1

    def report(self) -> str:
        if not self.n:
            return f"  {self.name:34} (no rows)"
        ordered = sorted(self.latencies_ms)
        median = ordered[len(ordered) // 2]
        return (f"  {self.name:34} top-1 {self.top1 / self.n:6.1%}   "
                f"top-5 {self.top5 / self.n:6.1%}   "
                f"n={self.n:<5} median {median:5.0f} ms"
                + (f"   no answer {self.no_answer}" if self.no_answer else ""))


def _rank(client: AitoClient, line: dict, limit: int = 5) -> tuple[list[str], float]:
    """Rank catalogue SKUs for one invoice line.

    `sku` links to `products.sku`, so this traverses the link: Aito ranks
    catalogue ROWS and hands back their columns. One query, no training
    step, and the same call the view will make.
    """
    where = {f: line[f] for f in LINE_FEATURES if line.get(f) is not None}
    started = time.perf_counter()
    try:
        response = client.predict("invoice_lines", where, "sku", limit=limit)
    except AitoError:
        return [], (time.perf_counter() - started) * 1000
    elapsed = (time.perf_counter() - started) * 1000
    ranked = [str(hit.get("$value")) for hit in response.get("hits") or []
              if hit.get("$value") is not None]
    return ranked, elapsed


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

    test = json.load(open(DATA / tenant / "invoice_lines_test.json"))
    train = json.load(open(DATA / tenant / "invoice_lines.json"))
    products = json.load(open(DATA / tenant / "products.json"))
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
        results = list(pool.map(lambda line: (_rank(client, line), line), test))
    wall = time.perf_counter() - started

    for (ranked, ms), line in results:
        truth = line["sku"]
        supplier = line["billing_supplier"]
        overall.add(ranked, truth, ms)
        (warm if supplier in seen_suppliers else cold).add(ranked, truth, ms)
        by_supplier.setdefault(supplier, Bucket(supplier)).add(ranked, truth, ms)

    shared, shared_share = _ambiguity(products)
    baseline = 1 / catalogue_size

    print()
    print(f"Invoice line → catalogue SKU, {tenant}")
    print(f"  catalogue {catalogue_size} SKUs · "
          f"{len(train)} labelled lines loaded · {len(test)} held out")
    print(f"  random baseline: {baseline:.2%}")
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
    print("  Per-row wall time here is mostly network: Aito's own "
          "x-aitoai-response-time is ~420 ms\n  against a ~1.6 s round trip "
          "from a laptop. Co-located, throughput is a worker-count question.")

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

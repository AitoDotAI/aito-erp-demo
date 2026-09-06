"""The two numbers that tell you whether a matcher is any good.

An accuracy figure on its own is unreadable. 28% sounds bad next to 90%
and excellent next to a 0.03% random baseline, and neither comparison
is the useful one. The useful ones are:

  * **the ceiling** — what a PERFECT matcher would score on this data.
    Half this catalogue shares a name with another row, so even an
    oracle that identifies the right *name* every time still has to
    guess which SKU. That caps top-1 at 66%, and a number quoted
    without its ceiling invites the reader to compare it to 100%.

  * **the floor** — what a dumb string matcher gets for free. If a
    TF-IDF index over the catalogue beats the database, the database is
    not earning its place in the pipeline, and the honest thing is to
    know that before a prospect discovers it.

Neither needs Aito. Both run locally in about a second, and they are
why `./do match-eval` reports three numbers rather than one.
"""

import collections
import math
import re

# Split on anything that is not a letter or digit, Nordic vowels kept.
_TOKEN = re.compile(r"[^0-9a-zä-öA-ZÄ-Ö]+")


def tokens(text: str | None) -> list[str]:
    return [t for t in _TOKEN.split((text or "").lower()) if t]


class TfIdfCatalogue:
    """Rank catalogue rows by token overlap with a line's description.

    Deliberately the least clever thing that could work: no learning, no
    history, no supplier knowledge — just the invoice text against the
    product name. It is the floor, and its whole job is to be beaten.
    """

    def __init__(self, products: list[dict]) -> None:
        docs = [(p["sku"], tokens(p.get("name"))) for p in products]
        df: collections.Counter = collections.Counter()
        for _, ts in docs:
            df.update(set(ts))
        n = max(len(docs), 1)
        self._idf = {t: math.log(n / (1 + c)) for t, c in df.items()}
        self._postings: dict[str, list[tuple[str, float]]] = collections.defaultdict(list)
        self._norm: dict[str, float] = {}
        for sku, ts in docs:
            vec = {t: (1 + math.log(c)) * self._idf.get(t, 0.0)
                   for t, c in collections.Counter(ts).items()}
            self._norm[sku] = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            for t, v in vec.items():
                self._postings[t].append((sku, v))

    def rank(self, description: str, limit: int = 5) -> list[str]:
        query = {t: (1 + math.log(c)) * self._idf.get(t, 0.0)
                 for t, c in collections.Counter(tokens(description)).items()
                 if t in self._postings}
        if not query:
            return []
        scores: dict[str, float] = collections.defaultdict(float)
        for t, v in query.items():
            for sku, w in self._postings[t]:
                scores[sku] += v * w
        ordered = sorted(scores.items(),
                         key=lambda kv: -kv[1] / self._norm[kv[0]])
        return [sku for sku, _ in ordered[:limit]]


# How much of the catalogue name survives into the invoice description.
# The boundaries are arbitrary; what matters is that the SAME ones are
# used everywhere, because the whole point is comparing like with like.
REGIMES = ("0%", "1-33%", "34-66%", "67-99%", "100%")


def overlap(description: str, name: str) -> float:
    """Share of the catalogue name's tokens present in the description."""
    name_tokens = set(tokens(name))
    if not name_tokens:
        return 0.0
    return len(name_tokens & set(tokens(description))) / len(name_tokens)


def regime(description: str, name: str) -> str:
    """Which matching problem this line actually poses.

    A line that repeats the catalogue name verbatim is a LOOKUP, and a
    text index should win it. A line that shares no words with the name
    can only be answered from history. Blending the two into one
    accuracy figure averages a task the database is not needed for
    against the task it exists for — so every number this harness
    reports is also broken out this way.
    """
    share = overlap(description, name)
    if share == 0:
        return "0%"
    if share <= 0.33:
        return "1-33%"
    if share <= 0.66:
        return "34-66%"
    if share < 1.0:
        return "67-99%"
    return "100%"


def ceiling(products: list[dict], test: list[dict]) -> tuple[float, float]:
    """What an oracle that always identifies the right NAME would score.

    It still has to pick among the SKUs sharing that name, and it has no
    way to tell them apart, so its expected top-1 is the mean of
    1 / group-size. This is the number the measured top-1 should be read
    against — not 100%.
    """
    groups = collections.Counter(p["name"] for p in products if p.get("name"))
    names = {p["sku"]: p.get("name") for p in products}
    sizes = [groups.get(names.get(line["sku"]), 1) or 1 for line in test]
    if not sizes:
        return 0.0, 0.0
    top1 = sum(1 / s for s in sizes) / len(sizes)
    top5 = sum(min(5, s) / s for s in sizes) / len(sizes)
    return top1, top5

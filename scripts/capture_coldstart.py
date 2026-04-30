"""Capture the cold-start curve from a real Aito DB.

Reproduces `data/coldstart/results.json`:
  1. Subsample `data/metsa/purchases.json` to 50 / 500 / 5,000 rows
     (deterministic — seed=2026 — so reruns produce the same snapshot)
  2. For each subsample: drop+recreate the `purchases` table in the
     target Aito DB, upload the rows, run `_evaluate` for each of
     cost_center / account_code / approver, capture the cases payload
  3. Aggregate accuracy, baseline, the share of test cases falling in
     the ≥0.85 confidence band, and that band's accuracy
  4. Write the JSON snapshot

Run requires WRITE access to a target Aito DB — the public
`shared.aito.ai/db/aito-erp-demo-*` keys committed to .env.example
are read-only. Provision a sandbox DB and pass its URL+key:

    python scripts/capture_coldstart.py \\
        --aito-url https://shared.aito.ai/db/your-coldstart-sandbox \\
        --aito-key <write-key>

The `purchases` table in that DB will be dropped, recreated, and
filled three times. Don't aim this at a DB you care about.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# Make `from src.aito_client import …` work when invoked as a script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.aito_client import AitoClient  # noqa: E402
from src.data_loader import SCHEMAS  # noqa: E402

PURCHASES_FIXTURE = ROOT / "data" / "metsa" / "purchases.json"
OUT_PATH = ROOT / "data" / "coldstart" / "results.json"

SUBSAMPLE_SIZES = [50, 500, 5000]
FIELDS = ["cost_center", "account_code", "approver"]
FEATURE_FIELDS = ["supplier", "description", "amount_eur"]
HIGH_CONFIDENCE_THRESHOLD = 0.85
EVALUATE_TEST_LIMIT = 200


def subsample(rows: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    if n >= len(rows):
        return list(rows)
    return rng.sample(rows, n)


def reload_table(client: AitoClient, rows: list[dict]) -> None:
    """Drop, recreate, and bulk-upload the `purchases` table."""
    schema = SCHEMAS["purchases"]
    print(f"  drop+recreate purchases ({len(rows)} rows)...")
    client._request("DELETE", "/schema/purchases")
    client._request("PUT", "/schema/purchases", json=schema)
    batch = 100
    for i in range(0, len(rows), batch):
        client._request("POST", "/data/purchases/batch", json=rows[i : i + batch])


def evaluate_field(client: AitoClient, field: str) -> dict:
    """Run `_evaluate` for one target field and aggregate the cases."""
    response = client.evaluate_with_cases(
        table="purchases",
        predict_field=field,
        feature_fields=FEATURE_FIELDS,
        limit=EVALUATE_TEST_LIMIT,
    )
    cases = response.get("cases") or []
    total = len(cases)
    high = [c for c in cases
            if float((c.get("top") or {}).get("$p") or 0) >= HIGH_CONFIDENCE_THRESHOLD]
    high_correct = sum(1 for c in high if c.get("accurate"))
    return {
        "name": field,
        "accuracy": round(float(response.get("accuracy") or 0), 3),
        "base_accuracy": round(float(response.get("baseAccuracy") or 0), 3),
        "high_confidence_share": round(len(high) / total, 3) if total else 0.0,
        "high_confidence_accuracy": (
            round(high_correct / len(high), 3) if high else 0.0
        ),
    }


SNAPSHOT_LABELS = {
    50:    ("Brand-new tenant",
            "About one week of POs. Aito has barely seen each supplier; "
            "predictions are honest about it."),
    500:   ("Two months in",
            "Recurring suppliers settle into patterns; Aito's "
            "high-confidence band picks up most of the queue."),
    5000:  ("Mature tenant",
            "Long tail covered, calibration tight. Confident predictions "
            "are right almost all the time."),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aito-url", required=True,
                        help="Sandbox Aito DB URL with WRITE access.")
    parser.add_argument("--aito-key", required=True,
                        help="Write-enabled API key for that DB.")
    parser.add_argument("--out", type=Path, default=OUT_PATH,
                        help="Output JSON path (default: data/coldstart/results.json)")
    parser.add_argument("--seed", type=int, default=2026,
                        help="Subsample seed (default: 2026 — keeps reruns stable)")
    args = parser.parse_args()

    print(f"Loading metsa purchases from {PURCHASES_FIXTURE}...")
    with open(PURCHASES_FIXTURE) as f:
        all_rows: list[dict] = json.load(f)
    print(f"  {len(all_rows)} rows available.")

    client = AitoClient.from_creds(args.aito_url, args.aito_key)
    if not client.check_connectivity():
        print(f"Cannot reach {args.aito_url}", file=sys.stderr)
        sys.exit(1)

    snapshots: list[dict] = []
    for size in SUBSAMPLE_SIZES:
        sample = subsample(all_rows, size, seed=args.seed)
        print(f"\n=== Capturing snapshot for n={size} ===")
        reload_table(client, sample)
        per_field = [evaluate_field(client, f) for f in FIELDS]
        for f in per_field:
            print(f"  {f['name']:14}  acc={f['accuracy']:.3f}  base={f['base_accuracy']:.3f}  "
                  f"≥{HIGH_CONFIDENCE_THRESHOLD}: {f['high_confidence_share']*100:.0f}% "
                  f"@ {f['high_confidence_accuracy']*100:.0f}% accuracy")
        label, blurb = SNAPSHOT_LABELS[size]
        snapshots.append({
            "size": size,
            "label": label,
            "blurb": blurb,
            "fields": per_field,
        })

    payload = {
        "captured_at": __import__("time").strftime("%Y-%m-%d"),
        "captured_from": (
            f"metsa purchases fixture ({len(all_rows)} rows), randomly "
            f"subsampled at " + " / ".join(f"{n:,}" for n in SUBSAMPLE_SIZES) + " rows. "
            "Each subsample loaded into the target Aito DB; _evaluate run against each."
        ),
        "method": "scripts/capture_coldstart.py — see docs/cold-start.md for how to refresh.",
        "fields": FIELDS,
        "snapshots": snapshots,
        "note": (
            "Captured against a real Aito DB. The shape — accuracy rises, baseline "
            "stays flat, the high-confidence band's share grows while staying near-"
            "perfect — is the load-bearing claim. Specific values vary with the "
            "dataset's separability."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()

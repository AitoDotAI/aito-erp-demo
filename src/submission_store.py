"""In-memory store for newly submitted POs.

A real ERP would persist these. The demo keeps them in process memory
— the goal is to show the workflow loop ("Smart Entry submit →
appears in PO Queue → routes to Approval"), not to persist forever.

Public-demo hardening:
  - Each entry has a TTL; expired entries are pruned on every read so
    a forgotten submission can't linger in the live queue.
  - A per-process cap (`MAX_SUBMISSIONS`) bounds memory and prevents
    flooding a queue every other visitor sees.
  - String fields are length-clipped on insert so a script can't
    submit a megabyte of text.
"""

import threading
import time
from typing import Any

_lock = threading.Lock()
_submissions: list[dict] = []
_counter = 7900  # PO numbers start above the demo PO range

# Submissions older than this disappear from the queue. One hour gives
# a sales conversation enough time to walk through the workflow loop
# without leaving stale "Acme widget" entries for the next visitor.
TTL_SECONDS = 60 * 60

# Hard cap on concurrent submissions across all visitors. Once full,
# the oldest entry rotates out FIFO.
MAX_SUBMISSIONS = 50

# Per-field max length. Aito itself accepts longer strings, but this
# protects the in-memory queue and keeps the UI tidy.
_FIELD_LIMITS = {
    "supplier":     120,
    "description":  240,
    "category":     40,
    "cost_center":  40,
    "account_code": 16,
    "approver":     80,
    "project":      40,
    "source":       32,
}


def _now() -> float:
    return time.time()


def _clip(value: Any, limit: int) -> str:
    """Coerce to string and clip to limit. Strips control characters
    so a hostile submission can't pollute the rendered UI."""
    s = "" if value is None else str(value)
    s = "".join(c for c in s if c == "\n" or c == "\t" or c.isprintable())
    return s[:limit]


def _sanitize(record: dict) -> dict:
    """Sanitize a submission record into the persisted shape."""
    out: dict = {}
    for field, limit in _FIELD_LIMITS.items():
        if field in record and record[field] is not None:
            out[field] = _clip(record[field], limit)
    # Numeric: coerce explicitly; reject invalid.
    try:
        amount = float(record.get("amount_eur") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    out["amount_eur"] = max(0.0, min(amount, 1_000_000.0))  # 0 ≤ x ≤ 1M EUR
    return out


def _prune_locked() -> None:
    """Remove expired entries. Caller holds the lock."""
    cutoff = _now() - TTL_SECONDS
    keep = [e for e in _submissions if e.get("_ts", 0) > cutoff]
    if len(keep) > MAX_SUBMISSIONS:
        keep = keep[-MAX_SUBMISSIONS:]
    _submissions[:] = keep


def add_submission(record: dict) -> dict:
    """Append a submission, assigning a fresh PO number and timestamp."""
    global _counter
    with _lock:
        _counter += 1
        po_number = f"PO-{_counter}"
        clean = _sanitize(record)
        entry = {
            **clean,
            "purchase_id": po_number,
            "submitted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "_ts": _now(),
        }
        _submissions.append(entry)
        _prune_locked()
        # Don't leak the internal timestamp in the public response.
        return {k: v for k, v in entry.items() if k != "_ts"}


def list_submissions() -> list[dict]:
    """Return all submissions (newest first), pruning expired."""
    with _lock:
        _prune_locked()
        return [
            {k: v for k, v in e.items() if k != "_ts"}
            for e in reversed(_submissions)
        ]


def clear() -> None:
    """Reset (used by tests + ./do clear-cache)."""
    global _counter
    with _lock:
        _submissions.clear()
        _counter = 7900

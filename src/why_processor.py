"""Process Aito $why factor trees into UI-friendly explanation objects.

The Aito _predict response includes a $why structure with raw factors —
baseP, relatedPropositionLift, product (internal aggregations). This module
extracts the user-facing pieces: base probability, significant lifts, the
multiplicative chain, and token highlights mapped back to context fields.

Design notes:
- Drops near-1.0 lifts (|lift - 1| < 0.05) — they don't move the prediction.
- Skips internal "product" factors entirely.
- Sorts displayed lifts by |value - 1| descending so strongest first.
- Computes the normalizer; only surface it when |normalizer - 1| > 0.10.
- Highlight field names are stripped of "$context." or "<table>." prefixes,
  but the raw form is kept so the frontend can do cross-highlighting.
"""

from typing import Any


def process_factors(why: dict | None, final_p: float) -> dict:
    """Transform a $why object into a clean explanation payload.

    Returns:
        {
            "base_p": float,                 # historical rate
            "lifts": [                        # significant lifts, sorted strongest first
                {
                    "lift": float,
                    "highlights": [{"field": str, "raw_field": str, "html": str}],
                    "proposition_str": str,
                },
                ...
            ],
            "final_p": float,
            "normalizer": float | None,       # only when significant
            "context_fields": [str],          # names of input fields that contributed
        }
    """
    if not why or not isinstance(why, dict):
        return {
            "base_p": 0.0,
            "lifts": [],
            "final_p": final_p,
            "normalizer": None,
            "context_fields": [],
        }

    factors = why.get("factors") or []
    base_p = 0.0
    all_lifts_values: list[float] = []
    significant: list[dict] = []
    context_fields: set[str] = set()

    for f in factors:
        if not isinstance(f, dict):
            continue
        ftype = f.get("type")
        if ftype == "baseP":
            val = f.get("value", 0.0)
            if isinstance(val, (int, float)):
                base_p = float(val)
        elif ftype == "relatedPropositionLift":
            val = f.get("value", 1.0)
            if not isinstance(val, (int, float)):
                continue
            lift = float(val)
            all_lifts_values.append(lift)
            # Drop near-1.0 lifts from the visual list
            if abs(lift - 1.0) < 0.05:
                continue
            highlights = []
            for h in f.get("highlight") or []:
                if not isinstance(h, dict):
                    continue
                raw_field = h.get("field", "")
                html = h.get("highlight", "")
                # Strip "$context." or "<table>." prefix
                field = raw_field
                if "." in raw_field:
                    field = raw_field.split(".", 1)[1]
                if raw_field.startswith("$context."):
                    context_fields.add(field)
                highlights.append({
                    "field": field,
                    "raw_field": raw_field,
                    "html": html,
                })
            significant.append({
                "lift": round(lift, 3),
                "highlights": highlights,
                "proposition_str": _proposition_to_string(f.get("proposition")),
            })
        # Ignore "product" and unknown types

    # Math: use ALL lifts (including near-1.0) to derive the normalizer
    unnorm = base_p
    for v in all_lifts_values:
        unnorm *= v
    if unnorm > 0:
        normalizer = final_p / unnorm
    else:
        normalizer = 1.0
    show_normalizer = abs(normalizer - 1.0) > 0.10

    # Sort by |lift - 1| descending so strongest first
    significant.sort(key=lambda s: abs(s["lift"] - 1.0), reverse=True)
    # Cap at 5 — anything beyond is noise for the popover
    significant = significant[:5]

    return {
        "base_p": round(base_p, 4),
        "lifts": significant,
        "final_p": round(final_p, 4),
        "normalizer": round(normalizer, 3) if show_normalizer else None,
        "context_fields": sorted(context_fields),
    }


def _proposition_to_string(prop: Any) -> str:
    """Best-effort serialization of a proposition for fallback display.

    The proposition is a structured form like
        {"$and": [{"supplier": {"$has": "Telia"}}, {"category": {"$is": "telecom"}}]}
    We render it as 'supplier has Telia AND category is telecom'.
    """
    if prop is None:
        return ""
    if isinstance(prop, dict):
        # Boolean operators
        if "$and" in prop and isinstance(prop["$and"], list):
            parts = [_proposition_to_string(p) for p in prop["$and"]]
            return " AND ".join(p for p in parts if p)
        if "$or" in prop and isinstance(prop["$or"], list):
            parts = [_proposition_to_string(p) for p in prop["$or"]]
            return " OR ".join(p for p in parts if p)
        if "$not" in prop:
            inner = _proposition_to_string(prop["$not"])
            return f"NOT ({inner})" if inner else ""
        # Field clauses: { fieldName: { "$has" / "$is" / "$gt" / ...: value } }
        for field, clause in prop.items():
            if field.startswith("$"):
                continue
            if isinstance(clause, dict):
                for op, val in clause.items():
                    op_human = {
                        "$has": "has",
                        "$is": "is",
                        "$gt": ">",
                        "$lt": "<",
                        "$gte": "≥",
                        "$lte": "≤",
                    }.get(op, op)
                    return f"{field} {op_human} {val}"
            else:
                return f"{field} = {clause}"
    return str(prop)


def extract_alternatives(hits: list[dict], skip_top: bool = True, limit: int = 3) -> list[dict]:
    """Return alternative predictions from the hits list.

    Each alternative has: value, confidence, why (processed).
    The top hit is skipped by default since the caller usually treats
    it as the primary prediction.
    """
    alts: list[dict] = []
    start = 1 if skip_top else 0
    for hit in hits[start:start + limit]:
        if not isinstance(hit, dict):
            continue
        p = hit.get("$p", 0.0)
        alts.append({
            "value": str(hit.get("feature", "")),
            "confidence": round(p, 4),
            "why": process_factors(hit.get("$why"), p),
        })
    return alts

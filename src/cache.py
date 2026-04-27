"""Two-layer cache: in-memory for speed, Aito for persistence.

Layer 1: In-memory dict with TTL — instant reads, cleared on restart.
Layer 2: Aito prediction_cache table — survives restarts, analyzable
via _relate, and demonstrates Aito as both prediction engine and
prediction store.

In multi-tenant mode the cache is partitioned per tenant: each
tenant has its own AitoClient (registered via init_persistent_cache)
and its own keyspace (callers prefix keys with `<tenant>:`). This
prevents one tenant's cached prediction from being served to
another tenant's request even if the underlying key happens to
collide.

On get: check memory → check that tenant's Aito → miss.
On set: write to memory AND to that tenant's Aito (background).

PUBLIC_DEMO mode: the persistent layer is disabled entirely.
init_persistent_cache becomes a no-op so we never try to PUT a
schema with a read-only API key, and the in-memory TTL cache is
the only path. Trade-off: the cache is cold after every restart;
the warmup loop pays the predict cost again. Acceptable for a
public demo where we'd rather not write to Aito at all.
"""

import hashlib
import json
import os
import time
import threading
from typing import Any

from src.aito_client import AitoClient, AitoError

PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "").lower() in ("1", "true", "yes")

# ── Layer 1: In-memory TTL cache ──────────────────────────────────

_cache: dict[str, tuple[float, Any]] = {}
DEFAULT_TTL = 600  # 10 minutes

# ── Layer 2: Aito persistent cache (per tenant) ───────────────────

# Map of tenant_id → AitoClient. Single-tenant deployments register
# under the special key "_default".
_aito_clients: dict[str, AitoClient] = {}

CACHE_TABLE = "prediction_cache"
CACHE_SCHEMA = {
    "type": "table",
    "columns": {
        "cache_key": {"type": "String", "nullable": False},
        "endpoint": {"type": "String", "nullable": False},
        "response_json": {"type": "String", "nullable": False},
        "created_at": {"type": "String", "nullable": False},
    },
}


def init_persistent_cache(client: AitoClient, tenant: str = "_default") -> None:
    """Register an Aito client for a tenant and ensure its cache table
    exists. Call once per tenant at startup.

    No-op in PUBLIC_DEMO mode: registering would trip read-only API
    keys and writing the cache row on `set()` would fail anyway. The
    memory-only TTL cache handles a public demo's traffic shape fine.
    """
    if PUBLIC_DEMO:
        return

    _aito_clients[tenant] = client

    try:
        schema = client.get_schema()
        if CACHE_TABLE not in schema.get("schema", {}):
            client._request("PUT", f"/schema/{CACHE_TABLE}", json=CACHE_SCHEMA)
            print(f"  Created {CACHE_TABLE} table for tenant '{tenant}'.")
    except AitoError as e:
        print(f"  Could not create cache table for tenant '{tenant}': {e}")


def _client_for_key(key: str) -> AitoClient | None:
    """Resolve which tenant's AitoClient owns a given cache key.

    Convention: keys are prefixed with `<tenant>:` (set by callers via
    tenant_key() below). Unprefixed keys fall back to "_default", which
    matches single-tenant deployments unchanged.
    """
    tenant = key.split(":", 1)[0] if ":" in key else "_default"
    if tenant in _aito_clients:
        return _aito_clients[tenant]
    return _aito_clients.get("_default")


def tenant_key(tenant: str | None, key: str) -> str:
    """Build a tenant-scoped cache key.

    `tenant_key(None, "po_pending")`     → "po_pending"     (single-tenant)
    `tenant_key("metsa", "po_pending")` → "metsa:po_pending"
    """
    if not tenant:
        return key
    return f"{tenant}:{key}"


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def get(key: str) -> Any | None:
    """Check memory first, then the tenant's Aito."""
    # Layer 1: memory
    entry = _cache.get(key)
    if entry is not None:
        expires_at, value = entry
        if time.monotonic() <= expires_at:
            return value
        del _cache[key]

    # Layer 2: that tenant's Aito
    client = _client_for_key(key)
    if client is not None:
        try:
            result = client.search(
                CACHE_TABLE,
                {"cache_key": _key_hash(key)},
                limit=1,
            )
            hits = result.get("hits", [])
            if hits:
                value = json.loads(hits[0]["response_json"])
                _cache[key] = (time.monotonic() + DEFAULT_TTL, value)
                return value
        except (AitoError, json.JSONDecodeError, KeyError):
            pass

    return None


def set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    """Write to memory and persist to the tenant's Aito in background."""
    _cache[key] = (time.monotonic() + ttl, value)

    client = _client_for_key(key)
    if client is not None:
        def persist():
            try:
                import datetime
                record = {
                    "cache_key": _key_hash(key),
                    "endpoint": key.split(":")[0] if ":" in key else key,
                    "response_json": json.dumps(value, default=str),
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
                client._request("POST", f"/data/{CACHE_TABLE}", json=record)
            except AitoError:
                pass
        threading.Thread(target=persist, daemon=True).start()


def clear() -> None:
    """Clear in-memory cache. Aito caches persist intentionally."""
    _cache.clear()


def clear_all() -> None:
    """Clear in-memory cache + every registered tenant's Aito cache."""
    _cache.clear()
    for tenant, client in _aito_clients.items():
        try:
            client._request("DELETE", f"/schema/{CACHE_TABLE}")
            client._request("PUT", f"/schema/{CACHE_TABLE}", json=CACHE_SCHEMA)
            print(f"Cleared Aito prediction cache for tenant '{tenant}'.")
        except AitoError as e:
            print(f"Could not clear Aito cache for tenant '{tenant}': {e}")

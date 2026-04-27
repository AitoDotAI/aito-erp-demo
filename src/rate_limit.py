"""Three-tier in-memory rate limiter for the public demo API.

Three sliding-window counters protect against three different abuse
patterns:

  1. **Per-IP** — one client can't drown everyone else.
  2. **Per-tenant** — abusing one persona can't degrade the others.
     (In multi-tenant deployments the cap is per Aito DB, not the
     whole demo.)
  3. **Global** — a botnet hammering thousands of IPs each below the
     per-IP cap still hits the global ceiling and gets shed cleanly.

Burst tolerance: each tier allows brief spikes (real visitors click
through the demo quickly), but the steady-state limits are tight
enough that a scraper finishes the trial budget rather than the
Aito budget.

Trusted-source bypass: localhost / 127.0.0.1 traffic skips the
per-IP cap so screenshot/booktest tooling doesn't trip itself.
Production deployments shouldn't run the script tooling against the
public hostname anyway.
"""

import os
import time
from collections import defaultdict

# ── Config (tunable via env) ─────────────────────────────────────────


def _intenv(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


PER_IP_MAX = _intenv("RATE_LIMIT_PER_IP", 60)              # req / 60s / IP
PER_TENANT_MAX = _intenv("RATE_LIMIT_PER_TENANT", 600)     # req / 60s / tenant
GLOBAL_MAX = _intenv("RATE_LIMIT_GLOBAL", 1500)            # req / 60s total
WINDOW_SECONDS = 60

# Trusted IPs that bypass the per-IP cap. Tenant + global still apply.
_TRUSTED = {"127.0.0.1", "::1", "localhost"}


# ── Sliding-window state ─────────────────────────────────────────────

_per_ip: dict[str, list[float]] = defaultdict(list)
_per_tenant: dict[str, list[float]] = defaultdict(list)
_global: list[float] = []


def _trim(timestamps: list[float], cutoff: float) -> list[float]:
    """Drop timestamps older than the window. Returns a fresh list to
    avoid in-place mutation surprises across threads."""
    return [t for t in timestamps if t > cutoff]


def check_rate_limit(client_ip: str, tenant: str | None = None) -> tuple[bool, str | None]:
    """Return `(allowed, reason)` — `reason` is set when the request
    is rejected and tells the caller which tier tripped, so the API
    response can be specific without revealing internal thresholds.
    """
    now = time.monotonic()
    cutoff = now - WINDOW_SECONDS

    # Global tier — trim and check.
    global_now = _trim(_global, cutoff)
    if len(global_now) >= GLOBAL_MAX:
        _global[:] = global_now
        return False, "global"

    # Per-tenant tier (only when a tenant id is supplied).
    tenant_now: list[float] = []
    if tenant:
        tenant_now = _trim(_per_tenant[tenant], cutoff)
        if len(tenant_now) >= PER_TENANT_MAX:
            _per_tenant[tenant] = tenant_now
            _global[:] = global_now
            return False, "tenant"

    # Per-IP tier — skipped for trusted sources.
    ip_now: list[float] = []
    if client_ip not in _TRUSTED:
        ip_now = _trim(_per_ip[client_ip], cutoff)
        if len(ip_now) >= PER_IP_MAX:
            _per_ip[client_ip] = ip_now
            if tenant:
                _per_tenant[tenant] = tenant_now
            _global[:] = global_now
            return False, "ip"

    # Allowed — record the hit in every active tier.
    global_now.append(now)
    _global[:] = global_now
    if tenant:
        tenant_now.append(now)
        _per_tenant[tenant] = tenant_now
    if client_ip not in _TRUSTED:
        ip_now.append(now)
        _per_ip[client_ip] = ip_now
    return True, None


# Backwards-compat shim: existing callers expect a single bool. Keep
# them working until the middleware switches to the (allowed, reason)
# tuple form.
def check_rate_limit_legacy(client_ip: str) -> bool:
    allowed, _ = check_rate_limit(client_ip)
    return allowed

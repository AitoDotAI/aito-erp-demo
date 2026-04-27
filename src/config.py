"""Configuration loaded from environment variables.

Two modes — both work, you pick by what you put in `.env`:

  Single-tenant (the original / default)
  ──────────────────────────────────────
  AITO_API_URL=...
  AITO_API_KEY=...
  → All three demo personas point at the same Aito DB.

  Multi-tenant (one Aito DB per persona)
  ──────────────────────────────────────
  AITO_METSA_API_URL=...  / AITO_METSA_API_KEY=...
  AITO_AURORA_API_URL=... / AITO_AURORA_API_KEY=...
  AITO_STUDIO_API_URL=... / AITO_STUDIO_API_KEY=...
  → The backend builds one AitoClient per persona; each request
    routes to the right DB based on the X-Tenant header.

The two are not exclusive — if a per-tenant pair is missing, that
persona falls back to the single-tenant pair. Lets you ramp up one
persona at a time.

Fails loudly when no usable credentials exist anywhere.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


TenantId = Literal["metsa", "aurora", "studio"]
TENANT_IDS: tuple[TenantId, ...] = ("metsa", "aurora", "studio")
DEFAULT_TENANT: TenantId = "metsa"


@dataclass(frozen=True)
class AitoCreds:
    """One Aito DB's credentials."""
    api_url: str
    api_key: str


@dataclass(frozen=True)
class Config:
    # Default credentials — used when the request doesn't name a tenant
    # or that tenant has no per-tenant pair set. Always populated.
    aito_api_url: str
    aito_api_key: str
    # Per-tenant overrides. Each value falls through to the default
    # pair above when the tenant isn't separately configured.
    tenants: dict[TenantId, AitoCreds]

    def creds_for(self, tenant: TenantId | None) -> AitoCreds:
        """Return the AitoCreds to use for a given tenant id."""
        if tenant and tenant in self.tenants:
            return self.tenants[tenant]
        return AitoCreds(self.aito_api_url, self.aito_api_key)

    @property
    def is_multi_tenant(self) -> bool:
        """True if at least one tenant has a separate Aito DB configured."""
        return any(
            self.tenants[t].api_url != self.aito_api_url
            for t in self.tenants
        )


_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_TENANT_ENV_PREFIX = {
    "metsa":  "AITO_METSA",
    "aurora": "AITO_AURORA",
    "studio": "AITO_STUDIO",
}


def _read_pair(prefix: str) -> tuple[str, str]:
    """Read AITO_<PREFIX>_API_URL / _API_KEY."""
    url = os.environ.get(f"{prefix}_API_URL", "").rstrip("/")
    key = os.environ.get(f"{prefix}_API_KEY", "")
    return url, key


def load_config(*, use_dotenv: bool = True) -> Config:
    """Load config from environment, with .env file fallback.

    Set use_dotenv=False in tests to prevent .env from interfering
    with monkeypatched environment variables.
    """
    if use_dotenv:
        load_dotenv(_PROJECT_ROOT / ".env", override=True)

    default_url = os.environ.get("AITO_API_URL", "").rstrip("/")
    default_key = os.environ.get("AITO_API_KEY", "")

    # Per-tenant pairs (may be empty — those tenants fall through).
    per_tenant: dict[TenantId, AitoCreds] = {}
    for tenant_id in TENANT_IDS:
        url, key = _read_pair(_TENANT_ENV_PREFIX[tenant_id])
        if url and key:
            per_tenant[tenant_id] = AitoCreds(api_url=url, api_key=key)

    # If we have at least one per-tenant pair but no global default,
    # adopt the first per-tenant pair as the default.
    if not default_url and per_tenant:
        first = next(iter(per_tenant.values()))
        default_url, default_key = first.api_url, first.api_key

    if not default_url or not default_key:
        raise ValueError(
            "No Aito credentials found. Set AITO_API_URL + AITO_API_KEY "
            "(single-tenant) or at least one per-tenant pair "
            "(AITO_KONEPAJA_*, AITO_POHJOLA_*, AITO_STUDIO_*). "
            "Copy .env.example to .env to get started."
        )

    # Fill missing tenants with the default pair so .creds_for() always
    # returns something useful.
    fallback = AitoCreds(default_url, default_key)
    tenants_full: dict[TenantId, AitoCreds] = {
        t: per_tenant.get(t, fallback) for t in TENANT_IDS
    }

    return Config(
        aito_api_url=default_url,
        aito_api_key=default_key,
        tenants=tenants_full,
    )

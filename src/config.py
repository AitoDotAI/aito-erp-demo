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

  API version — v1 (default) or v2
  ────────────────────────────────
  AITO_API_VERSION=v2
  AITO_METSA_V2_API_URL=...  / AITO_METSA_V2_API_KEY=...
  → Every Aito call goes to /api/v2 against the `_V2_` credentials.

Aito's v2 surface is built for rep2 *collections*; the tables behind the
live demo are rep1. So v2 gets its own credential pair per tenant —
pointing at a `v2` environment that holds collection-shaped copies of
the same fixtures — instead of reusing the v1 URL. Both configurations
sit side by side in `.env` and `AITO_API_VERSION` picks one. Production
sets nothing and stays on v1.

Choosing v2 without a `_V2_` pair for a tenant is an error, not a
fallback: pointing /api/v2 at the v1 master env would query rep1 tables
and *half* work — basic filters fine, `$match` and friends rejected —
which is a slow, confusing failure instead of a fast, clear one.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


TenantId = Literal["metsa", "aurora", "studio"]
TENANT_IDS: tuple[TenantId, ...] = ("metsa", "aurora", "studio")
DEFAULT_TENANT: TenantId = "metsa"

ApiVersion = Literal["v1", "v2"]
API_VERSIONS: tuple[ApiVersion, ...] = ("v1", "v2")
DEFAULT_API_VERSION: ApiVersion = "v1"


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
    # Which Aito REST surface to talk to. "v1" is the production
    # default; "v2" routes every call to /api/v2 and to the v2
    # credential pairs below.
    api_version: ApiVersion = DEFAULT_API_VERSION
    # Per-tenant v2 credentials. Only populated (and only consulted)
    # when api_version == "v2".
    v2_tenants: dict[TenantId, AitoCreds] = field(default_factory=dict)

    def creds_for(self, tenant: TenantId | None) -> AitoCreds:
        """Return the AitoCreds to use for a given tenant id.

        On v2 there is no fall-through to the v1 pair — a tenant with
        no `_V2_` credentials raises rather than querying the wrong
        database (see the module docstring).
        """
        if self.api_version == "v2":
            key = tenant or DEFAULT_TENANT
            if key not in self.v2_tenants:
                raise ValueError(
                    f"AITO_API_VERSION=v2 but no v2 credentials for tenant "
                    f"'{key}'. Set {_TENANT_ENV_PREFIX[key]}_V2_API_URL and "
                    f"{_TENANT_ENV_PREFIX[key]}_V2_API_KEY (see .env.example), "
                    f"or run `./do env-init-v2` to create the v2 environment."
                )
            return self.v2_tenants[key]
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


def _read_api_version(override: str | None = None) -> ApiVersion:
    """Resolve the API version: explicit override, else AITO_API_VERSION,
    else the v1 default.

    Unset and empty both mean "default" — an empty `AITO_API_VERSION=`
    left in a `.env` is a placeholder, not a choice. But a *set*,
    unrecognised value is rejected rather than defaulted: a typo'd
    `AITO_API_VERSION=V2` silently serving v1 is exactly the kind of
    quiet wrong answer this project doesn't ship.
    """
    raw = (override if override is not None
           else os.environ.get("AITO_API_VERSION", "")).strip().lower()
    if not raw:
        return DEFAULT_API_VERSION
    if raw not in API_VERSIONS:
        raise ValueError(
            f"AITO_API_VERSION must be one of {', '.join(API_VERSIONS)}; got '{raw}'."
        )
    return raw  # type: ignore[return-value]


def v2_url_for(base_url: str, env_name: str) -> str:
    """Point a tenant's v1 URL at the v2 environment `env_name`.

    `master` is a SENTINEL, not an environment. The API refuses
    `/env/master/` outright — "Env 'master' is the default; use the
    unscoped /api/... path" — so the one name that cannot denote a
    branch is free to mean "no branch". That is the end state of a
    cutover: the branch is promoted into master and the app stops
    naming an environment. Without the sentinel, v2-against-master
    cannot be expressed at all.

    Derived from the v1 URL rather than configured separately so the
    cutover is one variable instead of six. Same convention the
    accounting demo uses (`AITO_V2_ENV`); see its
    docs/v2-cutover-runbook.md.
    """
    root = base_url.rstrip("/")
    if "/env/" in root:
        root = root.rsplit("/env/", 1)[0]
    return root if env_name == "master" else f"{root}/env/{env_name}"


def load_config(*, use_dotenv: bool = True,
                api_version: str | None = None) -> Config:
    """Load config from environment, with .env file fallback.

    Set use_dotenv=False in tests to prevent .env from interfering
    with monkeypatched environment variables.

    `api_version` overrides both `.env` and the process environment.
    `.env` is loaded with `override=True`, so a caller that only
    exported `AITO_API_VERSION` would be silently overruled by a value
    in the file — tools that mean a specific version (`./do
    load-data-v2`, `./do v2-check`) pass it here instead.
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

    # If we have at least one per-tenant pair but no usable global
    # default, adopt the first per-tenant pair as the default.
    #
    # "Usable" means BOTH halves are set. A half-set pair — an
    # `AITO_API_URL` exported in the ambient shell with no matching
    # `AITO_API_KEY`, say — used to defeat this fallback and fail the
    # whole config, because the URL alone was enough to skip it and
    # not enough to authenticate. Three perfectly good per-tenant
    # pairs would sit there unused while the app refused to start.
    if not (default_url and default_key) and per_tenant:
        first = next(iter(per_tenant.values()))
        default_url, default_key = first.api_url, first.api_key

    if not default_url or not default_key:
        raise ValueError(
            "No Aito credentials found. Set AITO_API_URL + AITO_API_KEY "
            "(single-tenant) or at least one per-tenant pair "
            "(AITO_KONEPAJA_*, AITO_POHJOLA_*, AITO_STUDIO_*). "
            "Copy .env.example to .env to get started."
        )

    resolved_version = _read_api_version(api_version)
    # Naming a v2 environment and still running v1 would be a config
    # that silently does nothing, so the presence of AITO_V2_ENV is
    # itself the switch. An explicit api_version argument still wins —
    # `./do load-data --api-version=v1` must mean v1 whatever .env says.
    if api_version is None and not os.environ.get("AITO_API_VERSION", "").strip() \
            and os.environ.get("AITO_V2_ENV", "").strip():
        resolved_version = "v2"

    # Per-tenant v2 pairs. Read unconditionally so `./do env-init-v2`
    # and the conformance probe can see them while the app itself is
    # still serving v1.
    v2_tenants: dict[TenantId, AitoCreds] = {}
    for tenant_id in TENANT_IDS:
        url, key = _read_pair(f"{_TENANT_ENV_PREFIX[tenant_id]}_V2")
        if url and key:
            v2_tenants[tenant_id] = AitoCreds(api_url=url, api_key=key)

    # `AITO_V2_ENV` names the v2 environment and derives the URLs from
    # each tenant's own v1 pair — one variable instead of six, so a
    # cutover is one line and a rollback is deleting it. An explicit
    # `_V2_` pair still wins, because someone who wrote six URLs meant
    # them.
    v2_env = os.environ.get("AITO_V2_ENV", "").strip()
    if v2_env:
        for tenant_id, creds in per_tenant.items():
            if tenant_id not in v2_tenants:
                v2_tenants[tenant_id] = AitoCreds(
                    api_url=v2_url_for(creds.api_url, v2_env),
                    api_key=creds.api_key)

    if resolved_version == "v2" and not v2_tenants:
        raise ValueError(
            "v2 selected but no v2 credentials are configured. Either set "
            "AITO_V2_ENV=<env name> (derives each tenant's v2 URL from its "
            "v1 pair — `master` means v2 with no /env/ segment), or add "
            "AITO_<TENANT>_V2_API_URL / _V2_API_KEY pairs (see .env.example)."
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
        api_version=resolved_version,
        v2_tenants=v2_tenants,
    )

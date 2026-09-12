"""Tests for configuration loading."""

import os
import pytest
from src.config import TENANT_IDS, load_config


def _clear_aito_env(monkeypatch):
    """Unset every Aito credential variable.

    `./do test` sources `.env` into the shell before running pytest, so
    `use_dotenv=False` is not enough on its own — the per-tenant pairs
    are already in `os.environ` and would satisfy a config the test
    means to leave unsatisfied.
    """
    for name in list(os.environ):
        if name.startswith("AITO_"):
            monkeypatch.delenv(name, raising=False)


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("AITO_API_URL", "https://test.aito.app")
    monkeypatch.setenv("AITO_API_KEY", "test-key-123")
    config = load_config(use_dotenv=False)
    assert config.aito_api_url == "https://test.aito.app"
    assert config.aito_api_key == "test-key-123"


def test_load_config_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("AITO_API_URL", "https://test.aito.app/")
    monkeypatch.setenv("AITO_API_KEY", "key")
    config = load_config(use_dotenv=False)
    assert config.aito_api_url == "https://test.aito.app"


def test_load_config_raises_on_missing_vars(monkeypatch):
    _clear_aito_env(monkeypatch)
    with pytest.raises(ValueError, match="AITO_API_URL"):
        load_config(use_dotenv=False)


# ── API version ──────────────────────────────────────────────────


def _single_tenant_env(monkeypatch):
    _clear_aito_env(monkeypatch)
    monkeypatch.setenv("AITO_API_URL", "https://test.aito.app")
    monkeypatch.setenv("AITO_API_KEY", "key")


def test_api_version_defaults_to_v1(monkeypatch):
    _single_tenant_env(monkeypatch)
    assert load_config(use_dotenv=False).api_version == "v1"


def test_empty_api_version_means_default(monkeypatch):
    """An empty `AITO_API_VERSION=` in .env is a placeholder, not a choice."""
    _single_tenant_env(monkeypatch)
    monkeypatch.setenv("AITO_API_VERSION", "")
    assert load_config(use_dotenv=False).api_version == "v1"


def test_unknown_api_version_is_rejected(monkeypatch):
    _single_tenant_env(monkeypatch)
    monkeypatch.setenv("AITO_API_VERSION", "v3")
    with pytest.raises(ValueError, match="AITO_API_VERSION"):
        load_config(use_dotenv=False)


def test_explicit_api_version_overrides_the_environment(monkeypatch):
    """`./do load-data-v2` must win over whatever .env says."""
    _single_tenant_env(monkeypatch)
    monkeypatch.setenv("AITO_API_VERSION", "v1")
    for tenant in TENANT_IDS:
        monkeypatch.setenv(f"AITO_{tenant.upper()}_V2_API_URL", "https://v2.aito.app/env/v2")
        monkeypatch.setenv(f"AITO_{tenant.upper()}_V2_API_KEY", "key")
    assert load_config(use_dotenv=False, api_version="v2").api_version == "v2"


def test_v2_without_credentials_raises(monkeypatch):
    """v2 against the v1 URL would half-work; that's worse than failing."""
    _single_tenant_env(monkeypatch)
    with pytest.raises(ValueError, match="no v2 credentials"):
        load_config(use_dotenv=False, api_version="v2")


def test_v2_creds_resolve_per_tenant(monkeypatch):
    _single_tenant_env(monkeypatch)
    for tenant in TENANT_IDS:
        monkeypatch.setenv(f"AITO_{tenant.upper()}_V2_API_URL",
                           f"https://{tenant}.aito.app/env/v2")
        monkeypatch.setenv(f"AITO_{tenant.upper()}_V2_API_KEY", f"{tenant}-key")
    config = load_config(use_dotenv=False, api_version="v2")
    assert config.creds_for("aurora").api_url == "https://aurora.aito.app/env/v2"
    # v1 credentials are still readable — the two sets coexist.
    assert config.aito_api_url == "https://test.aito.app"


def test_v2_missing_one_tenant_raises_for_that_tenant(monkeypatch):
    """No silent fall-through to the v1 database."""
    _single_tenant_env(monkeypatch)
    monkeypatch.setenv("AITO_METSA_V2_API_URL", "https://metsa.aito.app/env/v2")
    monkeypatch.setenv("AITO_METSA_V2_API_KEY", "metsa-key")
    config = load_config(use_dotenv=False, api_version="v2")
    assert config.creds_for("metsa").api_key == "metsa-key"
    with pytest.raises(ValueError, match="no v2 credentials for tenant 'studio'"):
        config.creds_for("studio")


def test_half_set_default_pair_falls_back_to_per_tenant(monkeypatch):
    """A URL with no key must not defeat the per-tenant fallback.

    An `AITO_API_URL` exported in the ambient shell with no matching
    key used to fail the whole config even with three complete
    per-tenant pairs configured.
    """
    _clear_aito_env(monkeypatch)
    monkeypatch.setenv("AITO_API_URL", "https://api.aito.ai")   # no _API_KEY
    for tenant in TENANT_IDS:
        monkeypatch.setenv(f"AITO_{tenant.upper()}_API_URL", f"https://{tenant}.aito.app")
        monkeypatch.setenv(f"AITO_{tenant.upper()}_API_KEY", f"{tenant}-key")
    config = load_config(use_dotenv=False)
    assert config.aito_api_url == "https://metsa.aito.app"
    assert config.creds_for("studio").api_key == "studio-key"


def test_half_set_default_pair_with_no_per_tenant_still_raises(monkeypatch):
    _clear_aito_env(monkeypatch)
    monkeypatch.setenv("AITO_API_URL", "https://api.aito.ai")
    with pytest.raises(ValueError, match="AITO_API_URL"):
        load_config(use_dotenv=False)


# ── AITO_V2_ENV: one variable for the whole v2 cutover ──────────────


def _three_tenants(monkeypatch):
    """A per-tenant v1 setup pointing at `/env/dev`, like production."""
    _clear_aito_env(monkeypatch)
    for prefix, db in (("METSA", "2"), ("AURORA", "3"), ("STUDIO", "4")):
        monkeypatch.setenv(f"AITO_{prefix}_API_URL",
                           f"https://shared.aito.ai/db/demo-{db}/env/dev")
        monkeypatch.setenv(f"AITO_{prefix}_API_KEY", f"key-{db}")


def test_v2_env_derives_every_tenant_url_from_its_v1_pair(monkeypatch):
    """The point of the variable: one line to cut over, not six URLs.

    Each tenant keeps its own database and key; only the environment
    segment moves.
    """
    _three_tenants(monkeypatch)
    monkeypatch.setenv("AITO_V2_ENV", "v2")
    config = load_config(use_dotenv=False)
    assert config.api_version == "v2"
    assert config.creds_for("aurora").api_url == "https://shared.aito.ai/db/demo-3/env/v2"
    assert config.creds_for("metsa").api_url == "https://shared.aito.ai/db/demo-2/env/v2"
    # The key travels with the tenant — same database, different env.
    assert config.creds_for("aurora").api_key == "key-3"


def test_master_means_v2_with_no_env_segment(monkeypatch):
    """`master` is a sentinel, not an environment.

    The API refuses `/env/master/` outright, so the one name that cannot
    denote a branch is free to mean "no branch" — which is the end state
    of a cutover, once the branch has been promoted.
    """
    _three_tenants(monkeypatch)
    monkeypatch.setenv("AITO_V2_ENV", "master")
    config = load_config(use_dotenv=False)
    assert config.api_version == "v2"
    assert config.creds_for("aurora").api_url == "https://shared.aito.ai/db/demo-3"


def test_unset_v2_env_means_v1(monkeypatch):
    """Rollback is deleting the line, so absence has to mean v1."""
    _three_tenants(monkeypatch)
    config = load_config(use_dotenv=False)
    assert config.api_version == "v1"
    assert config.creds_for("aurora").api_url.endswith("/env/dev")


def test_an_explicit_v2_pair_still_wins(monkeypatch):
    """Someone who wrote six URLs meant them. The derivation is a
    convenience, not a policy that overrides what was stated."""
    _three_tenants(monkeypatch)
    monkeypatch.setenv("AITO_V2_ENV", "v2")
    monkeypatch.setenv("AITO_AURORA_V2_API_URL", "https://elsewhere/db/x/env/special")
    monkeypatch.setenv("AITO_AURORA_V2_API_KEY", "other-key")
    config = load_config(use_dotenv=False)
    assert config.creds_for("aurora").api_url == "https://elsewhere/db/x/env/special"
    assert config.creds_for("aurora").api_key == "other-key"
    # The tenants without an explicit pair still derive.
    assert config.creds_for("metsa").api_url == "https://shared.aito.ai/db/demo-2/env/v2"


def test_an_explicit_api_version_still_overrides(monkeypatch):
    """`./do load-data --api-version=v1` has to mean v1 whatever the
    environment says — it is the guard that keeps a v1 load from
    rewriting the v2 environments."""
    _three_tenants(monkeypatch)
    monkeypatch.setenv("AITO_V2_ENV", "v2")
    assert load_config(use_dotenv=False, api_version="v1").api_version == "v1"


def test_v2_without_any_credentials_says_both_ways_out(monkeypatch):
    _clear_aito_env(monkeypatch)
    monkeypatch.setenv("AITO_API_URL", "https://x/db/d")
    monkeypatch.setenv("AITO_API_KEY", "k")
    monkeypatch.setenv("AITO_API_VERSION", "v2")
    with pytest.raises(ValueError, match="AITO_V2_ENV"):
        load_config(use_dotenv=False)

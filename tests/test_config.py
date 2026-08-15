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

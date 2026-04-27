"""Tests for configuration loading."""

import os
import pytest
from src.config import load_config


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
    monkeypatch.delenv("AITO_API_URL", raising=False)
    monkeypatch.delenv("AITO_API_KEY", raising=False)
    with pytest.raises(ValueError, match="AITO_API_URL"):
        load_config(use_dotenv=False)

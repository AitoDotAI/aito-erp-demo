"""Tests for the fixture loader's v1/v2 split.

The safety guard is the point here: on v2 a dropped `/env/<name>/` URL
segment targets production and succeeds, and this loader deletes every
table before recreating it.
"""

import pytest

from src.data_loader import SCHEMAS, _assert_env_scoped, schema_for


def test_v1_schemas_are_rep1_tables():
    assert schema_for("purchases", "v1")["type"] == "table"


def test_v2_schemas_are_collections():
    assert schema_for("purchases", "v2")["type"] == "collection"


def test_only_the_table_type_differs_between_versions():
    """Columns, links and nullability are shared — v2 kept v1's vocabulary."""
    for table in SCHEMAS:
        v1 = schema_for(table, "v1")
        v2 = schema_for(table, "v2")
        assert v1["columns"] == v2["columns"], table
        assert set(v1) == set(v2), table


def test_schema_for_does_not_mutate_the_shared_definition():
    schema_for("purchases", "v2")
    assert SCHEMAS["purchases"]["type"] == "table"


def test_env_scoped_url_is_accepted():
    _assert_env_scoped("metsa", "https://shared.aito.ai/db/aito-erp-demo-2/env/v2")


def test_master_url_is_refused():
    with pytest.raises(ValueError, match="refusing to load v2 fixtures into master"):
        _assert_env_scoped("metsa", "https://shared.aito.ai/db/aito-erp-demo-2")

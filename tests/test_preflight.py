"""The pre-deploy gate's red path.

A gate nobody has watched fail is a gate nobody should trust. The drift
check is the one that matters — it caught two personas serving a
`products` schema three days out of date while `./do v2-check` called
them green — so its failure mode is pinned here rather than discovered
on a deploy.
"""

from src.data_loader import SCHEMAS
from src.preflight import missing_columns


def test_a_column_this_build_expects_but_the_server_lacks_is_drift():
    """The real case: `origin` was added to `products` and the env was
    never reloaded. Every query kept returning 200 OK."""
    declared = {"columns": {"sku": {}, "name": {}, "origin": {}, "grade": {}}}
    loaded = {"columns": {"sku": {}, "name": {}}}
    assert missing_columns(declared, loaded) == ["grade", "origin"]


def test_a_matching_schema_is_not_drift():
    schema = {"columns": {"sku": {}, "name": {}}}
    assert missing_columns(schema, schema) == []


def test_extra_columns_on_the_server_are_not_drift():
    """The server having MORE than this build knows about is a stale
    deploy, not a stale database — a different problem, and not one a
    reload fixes. Reporting it here would send someone the wrong way."""
    declared = {"columns": {"sku": {}}}
    loaded = {"columns": {"sku": {}, "legacy_field": {}}}
    assert missing_columns(declared, loaded) == []


def test_an_unreadable_schema_reads_as_total_drift():
    """A 500 or a missing table leaves `loaded` empty. Every declared
    column is then missing, which is the loudest possible answer and the
    right one — core #1303 presented exactly this way."""
    declared = {"columns": {"sku": {}, "name": {}}}
    assert missing_columns(declared, None) == ["name", "sku"]


def test_the_gate_checks_the_schemas_this_build_actually_declares():
    """Guards against the check quietly narrowing: if `products` ever
    stops carrying the columns the matching case needs, the gate should
    be looking for them."""
    products = SCHEMAS["products"]["columns"]
    assert {"origin", "grade", "description"} <= set(products)

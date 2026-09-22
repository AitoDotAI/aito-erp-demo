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


def test_an_explicit_pair_is_named_when_it_overrides_the_env_var(monkeypatch):
    """`AITO_V2_ENV=master` with a stale `AITO_<T>_V2_API_URL` exported
    in a long-lived shell reported "api v2 (from AITO_V2_ENV=master)"
    directly above "env=v2", and nothing said why. The explicit pair
    winning is by design; it silently winning is not."""
    from src.preflight import _explicit_v2_url_var

    monkeypatch.setenv("AITO_AURORA_V2_API_URL", "https://example.invalid/env/v2")
    monkeypatch.setenv("AITO_AURORA_V2_API_KEY", "k")
    assert _explicit_v2_url_var("aurora") == "AITO_AURORA_V2_API_URL"


def test_a_half_set_pair_is_not_reported(monkeypatch):
    """`load_config` only takes an explicit pair when it has BOTH
    halves, so naming a URL with no key would point at a variable that
    is not in effect."""
    from src.preflight import _explicit_v2_url_var

    monkeypatch.setenv("AITO_AURORA_V2_API_URL", "https://example.invalid/env/v2")
    monkeypatch.delenv("AITO_AURORA_V2_API_KEY", raising=False)
    assert _explicit_v2_url_var("aurora") is None


def test_no_override_means_no_notice(monkeypatch):
    from src.preflight import _explicit_v2_url_var

    monkeypatch.delenv("AITO_METSA_V2_API_URL", raising=False)
    monkeypatch.delenv("AITO_METSA_V2_API_KEY", raising=False)
    assert _explicit_v2_url_var("metsa") is None

"""HTTP client for Aito's predictive database API.

Thin wrapper — each method maps directly to an Aito REST endpoint.
No abstraction beyond authentication, error handling, and the v1↔v2
response normalisation described below. An outside developer reading
this file should see exactly what HTTP calls are made and what response
shapes come back.

Aito API docs: https://aito.ai/docs/api/  ·  v2: https://aito.ai/docs/v2/

Two API versions
────────────────
`api_version` selects the REST surface: `v1` (the production default)
or `v2` (the rep2 engine, running against a tenant's `v2` environment).
The endpoints and query bodies are near-identical; a handful of response
shapes are not. Rather than teach eleven service modules two dialects,
this client normalises **both** versions onto one canonical shape, and
that shape is v2's — the destination, not the legacy:

  | Concept          | v1 wire shape                     | v2 wire shape        | canonical |
  |------------------|-----------------------------------|----------------------|-----------|
  | predicted value  | `hit["feature"]`                  | `hit["$value"]`      | `$value`  |
  | relate target    | `relate: "supplier"`              | `relate: ["supplier"]` | n/a (request) |
  | relate hit value | `related.supplier.$has`           | `related.supplier`   | `$has` unwrapped |
  | relate probs     | `ps: {p, pOnCondition, …}`        | *absent*             | derived from `fs` |
  | evaluate body    | flat `{accuracy, …}`              | `{kind, data: {…}}`  | flat      |

Each translation is explicit and one-directional (v1 → canonical, or
v2 → canonical); nothing is guessed or dropped. When v1 support is
retired, every `if self._api_version == "v1"` branch here goes with it
and the services need no further change.
"""

import time
from typing import Any

import httpx

from src.config import ApiVersion, Config, DEFAULT_API_VERSION
from src import timing


class AitoError(Exception):
    """Raised when an Aito API call fails.

    Includes the HTTP status and response body so the caller has enough
    context to diagnose without a debugger.
    """

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        self.status_code = status_code
        self.body = body
        super().__init__(message)


def _is_missing_table_error(exc: "AitoError", table: str) -> bool:
    """Detect Aito's "no such table" response, on either API version.

    Returned when a query targets a table that doesn't exist in the
    tenant's DB — a normal demo-life situation if data hasn't been
    loaded yet for that tenant. Letting it bubble up as a 500 makes
    the whole page break; treating it as "empty result" keeps the
    page renderable so visitors see structure, not a stack trace.

    v1 answers `400 failed to open '<table>'`; v2 answers a typed
    `{"code": "not_found", "message": "<table> not found"}`. Both are
    matched against the table name so an unrelated 400/404 still
    raises.
    """
    if not isinstance(exc, AitoError):
        return False
    if exc.status_code == 400 and f"failed to open '{table}'" in str(exc):
        return True
    return exc.status_code == 404 and f"{table} not found" in str(exc)


def _canonical_predicted_values(response: dict, api_version: ApiVersion) -> dict:
    """Rename v1's `feature` hit key to v2's `$value`.

    Mutates and returns the response. A v2 response already speaks the
    canonical vocabulary and is handed straight back. A v1 hit that
    carries neither key is left alone rather than patched with a
    placeholder — a shape we don't recognise should surface as a
    KeyError at the call site, not as an empty prediction.
    """
    if api_version == "v2":
        return response
    for hit in response.get("hits", []):
        if "feature" in hit:
            hit["$value"] = hit.pop("feature")
    return response


def _canonical_relate_hits(response: dict, api_version: ApiVersion) -> dict:
    """Normalise a `_relate` response onto the canonical shape.

    Two v1↔v2 differences, both in the hit body:

    * `related` — v1 wraps the matched value in the operator that
      matched it (`{"supplier": {"$has": "Neste Oyj"}}`); v2 returns the
      value directly (`{"supplier": "Neste Oyj"}`). We unwrap v1 so
      callers read one shape.
    * `ps` — v1 returns smoothed probabilities alongside the raw
      frequencies; v2 returns frequencies only. We recompute the three
      the demo reads (`p`, `pOnCondition`, `pOnNotCondition`) from `fs`
      so a v2 response can't silently render as 0.0. These are the plain
      empirical ratios, so they differ slightly from v1's smoothed
      values — a visible, documented difference rather than a hidden
      one. Filed as a core gap; see docs/v2-migration.md.
    """
    if api_version == "v1":
        for hit in response.get("hits", []):
            related = hit.get("related")
            if isinstance(related, dict):
                hit["related"] = {
                    field: (next(iter(matched.values())) if isinstance(matched, dict) else matched)
                    for field, matched in related.items()
                }
        return response

    for hit in response.get("hits", []):
        if "ps" in hit:
            continue
        fs = hit.get("fs", {})
        n = fs.get("n", 0.0)
        f_condition = fs.get("fCondition", 0.0)
        n_not_condition = n - f_condition
        hit["ps"] = {
            "p": (fs.get("f", 0.0) / n) if n else 0.0,
            "pOnCondition": (fs.get("fOnCondition", 0.0) / f_condition) if f_condition else 0.0,
            "pOnNotCondition": (fs.get("fOnNotCondition", 0.0) / n_not_condition)
                               if n_not_condition else 0.0,
        }
    return response


def _unwrap_v2_envelope(response: dict, api_version: ApiVersion, kind: str) -> dict:
    """Strip v2's `{"kind": …, "data": {…}}` envelope.

    `_evaluate` and `_estimate` are engine-dispatched on v2 and wrap
    their payload; v1 returns it flat. Asserts the envelope is the kind
    we asked for — a `kind` we didn't expect means the query did
    something other than what the caller thinks.
    """
    if api_version == "v1":
        return response
    if "kind" not in response:
        return response
    if response["kind"] != kind:
        raise AitoError(
            f"Expected a '{kind}' response from Aito v2, got '{response['kind']}': "
            f"{str(response)[:300]}"
        )
    return response["data"]


class AitoClient:
    """Synchronous client for the Aito REST API."""

    def __init__(self, config: Config) -> None:
        creds = config.creds_for(None)
        self._base_url = creds.api_url
        self._api_version: ApiVersion = config.api_version
        self._headers = {
            "x-api-key": creds.api_key,
            "content-type": "application/json",
        }
        # When set, missing-table errors return an empty canonical
        # response instead of raising. Enabled per-tenant in app.py.
        self._tolerate_missing = False
        # Pooled `httpx.Client` keeps the TCP+TLS connection alive
        # across requests. `httpx.request(...)` (used previously)
        # creates a fresh connection per call, paying ~150 ms of
        # TLS handshake on every request — which on a shared Aito
        # instance dominates the per-call wall-clock (~280 ms total
        # vs ~110 ms steady-state with pooling).
        self._client = httpx.Client(headers=self._headers, timeout=30.0)

    @classmethod
    def from_creds(cls, api_url: str, api_key: str,
                   tolerate_missing: bool = False,
                   api_version: ApiVersion = DEFAULT_API_VERSION) -> "AitoClient":
        """Build a client from raw credentials. Used by the multi-tenant
        resolver so we don't need a synthetic Config per tenant."""
        instance = cls.__new__(cls)
        instance._base_url = api_url.rstrip("/")
        instance._api_version = api_version
        instance._headers = {
            "x-api-key": api_key,
            "content-type": "application/json",
        }
        instance._tolerate_missing = tolerate_missing
        instance._client = httpx.Client(headers=instance._headers, timeout=30.0)
        return instance

    @property
    def api_version(self) -> ApiVersion:
        """Which Aito REST surface this client talks to."""
        return self._api_version

    def _url(self, path: str) -> str:
        return f"{self._base_url}/api/{self._api_version}{path}"

    def _request(self, method: str, path: str, json: dict | None = None) -> Any:
        """Make an HTTP request to Aito and return the parsed JSON response.

        Per-call timing is recorded onto the per-request timing context
        (when called inside a FastAPI handler) so the browser can render
        a latency pill from the `X-Aito-Calls` response header.

        We prefer Aito's own `x-aitoai-response-time` header (server-side
        processing time, in ms) over the httpx wall-clock, because the
        wall-clock includes server→Aito network round-trip which is not
        what the demo wants to surface as "this is what a query costs".
        We fall back to wall-clock when the header is absent (errors,
        connection failures, mocked responses).

        Raises AitoError on non-2xx status or connection failure.
        """
        start = time.perf_counter()
        try:
            # Timeout is set once on the pooled client (see __init__).
            response = self._client.request(method, self._url(path), json=json)
        except httpx.HTTPError as exc:
            # No response → no Aito-side time available. Wall-clock is
            # still useful telemetry (probably "I just timed out").
            timing.record_call(path, (time.perf_counter() - start) * 1000)
            raise AitoError(
                f"Aito request failed: {method} {path}: {exc}"
            ) from exc

        aito_ms_header = response.headers.get("x-aitoai-response-time")
        if aito_ms_header:
            try:
                ms = float(aito_ms_header)
            except ValueError:
                ms = (time.perf_counter() - start) * 1000
        else:
            ms = (time.perf_counter() - start) * 1000
        timing.record_call(path, ms)

        if response.status_code >= 400:
            raise AitoError(
                f"Aito returned {response.status_code} for {method} {path}: "
                f"{response.text[:500]}",
                status_code=response.status_code,
                body=response.text,
            )

        return response.json()

    def get_schema(self) -> dict:
        """Fetch the database schema. Returns table definitions."""
        return self._request("GET", "/schema")

    def check_connectivity(self) -> bool:
        """Return True if the Aito instance is reachable and authenticated."""
        try:
            self.get_schema()
            return True
        except AitoError:
            return False

    def _empty(self, kind: str) -> dict:
        """Canonical empty response per query type — used when
        tolerate_missing is on and the table doesn't exist."""
        if kind == "evaluate":
            return {"accuracy": None, "baseAccuracy": None, "n": 0}
        if kind == "recommend":
            return {"hits": []}
        return {"hits": [], "offset": 0, "total": 0}

    def predict(self, table: str, where: dict, predict_field: str, limit: int = 10) -> dict:
        """Run a _predict query.

        Example:
            client.predict(
                table="purchases",
                where={"supplier": "Elenia Oy", "description": "Electricity"},
                predict_field="account_code",
            )

        Returns hits like:
            {"$p": 0.94, "$value": "6110", "$why": {...}}

        Note: Aito returns the predicted value under a fixed key, not
        under one named after the field. v1 calls that key `feature`
        and v2 calls it `$value`; this method always hands back
        `$value` (see the module docstring).
        """
        # The predicted-value select token is the one piece of the query
        # body that differs between versions — v2 rejects `feature` with
        # `no such field 'feature'`.
        value_token = "$value" if self._api_version == "v2" else "feature"
        query = {
            "from": table,
            "where": where,
            "predict": predict_field,
            "select": [
                "$p",
                value_token,
                {
                    "$why": {
                        "highlight": {
                            # Sentinel tags — frontend splits and renders
                            # without dangerouslySetInnerHTML.
                            "posPreTag": "«",
                            "posPostTag": "»",
                        }
                    }
                },
            ],
            "limit": limit,
        }
        try:
            response = self._request("POST", "/_predict", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("predict")
            raise
        return _canonical_predicted_values(response, self._api_version)

    def evaluate(self, table: str, where: dict, predict_field: str) -> dict:
        """Run an _evaluate query to score how likely a field value is.

        Used for anomaly detection — low probability means the
        combination is unusual in the data.

        Example:
            client.evaluate(
                table="purchases",
                where={"supplier": "Fazer Food Services"},
                predict_field="account_code",
            )

        Returns: {"accuracy": ..., "baseAccuracy": ..., ...}
        """
        query = {
            "evaluate": {
                "from": table,
                "where": where,
                "predict": predict_field,
            },
        }
        try:
            response = self._request("POST", "/_evaluate", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("evaluate")
            raise
        return _unwrap_v2_envelope(response, self._api_version, "evaluation")

    def evaluate_with_cases(
        self,
        table: str,
        predict_field: str,
        feature_fields: list[str],
        test_where: dict | None = None,
        evaluate_extra_where: dict | None = None,
        limit: int = 200,
    ) -> dict:
        """Run a held-out `_evaluate` and return per-case results.

        For each row picked by `testSource`, Aito hides the target
        field, predicts it from `feature_fields` (read off the held-out
        row via `$get`), and compares to ground truth. Returns
        `accuracy`, `baseAccuracy`, `totalCases`, plus the per-case list
        — which the caller buckets by confidence band, surfaces failures,
        etc. (See guides/08 in aito-accounting-demo.)

        Example:
            client.evaluate_with_cases(
                table="purchases",
                predict_field="cost_center",
                feature_fields=["supplier", "description", "amount_eur"],
                limit=200,
            )
        """
        evaluate_where = {
            field: {"$get": field} for field in feature_fields
        }
        # Extra constraints applied on the *evaluate* side — for
        # cold-start simulation we add e.g. `order_month: {$lt: ...}`
        # to make Aito's conditional probabilities use only an early
        # slice of history. Caller is responsible for not picking a
        # field name that collides with `feature_fields`.
        if evaluate_extra_where:
            evaluate_where.update(evaluate_extra_where)
        test_source: dict = {"from": table, "limit": limit}
        if test_where:
            test_source["where"] = test_where

        query = {
            "testSource": test_source,
            "evaluate": {
                "from": table,
                "where": evaluate_where,
                "predict": predict_field,
            },
            "select": ["accuracy", "baseAccuracy", "cases"],
        }
        try:
            response = self._request("POST", "/_evaluate", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return {"accuracy": None, "baseAccuracy": None, "cases": []}
            raise
        result = _unwrap_v2_envelope(response, self._api_version, "evaluation")
        # Each case carries its own predicted value under the same key
        # that a predict hit does — normalise it the same way.
        for case in result.get("cases", []):
            for slot in ("top", "correct"):
                hit = case.get(slot)
                if isinstance(hit, dict) and "feature" in hit:
                    hit["$value"] = hit.pop("feature")
        return result

    def recommend(
        self,
        table: str,
        where: dict,
        recommend_field: str,
        goal: dict,
        select: list | None = None,
        limit: int = 8,
    ) -> dict:
        """Run a `_recommend` query — goal-driven ranking.

        For each candidate value of `recommend_field`, Aito returns the
        probability that `goal` is satisfied given `where`. The hits
        come back ranked by that probability.

        When `recommend_field` is a `link` column, Aito's default `select`
        already returns every column from the linked table on each hit
        — so the typical caller leaves `select=None` and reads
        `hit["name"]`, `hit["category"]`, etc. straight off the result.
        Passing an explicit `select` is mostly useful when you want to
        narrow the payload or pull `$why`.

        Example:
            client.recommend(
                table="impressions",
                where={"prev_product_id": "SKU-1234"},
                recommend_field="product_id",
                goal={"clicked": True},
                limit=8,
            )
            # hit fields: $p + every column of products.* including sku
        """
        query: dict = {
            "from": table,
            "where": where,
            "recommend": recommend_field,
            "goal": goal,
            "limit": limit,
        }
        if select is not None:
            query["select"] = select
        try:
            return self._request("POST", "/_recommend", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("recommend")
            raise

    def relate(self, table: str, where: dict, relate_field: str) -> dict:
        """Run a _relate query to discover feature relationships.

        Example:
            client.relate(
                table="purchases",
                where={"delivery_late": True},
                relate_field="supplier",
            )

        Returns hits with statistics:
            {
              "related": {"supplier": "Neste Oyj"},
              "lift": 2.4,
              "fs": {"f": 33, "fOnCondition": 18, ...},
              "ps": {"p": 0.14, "pOnCondition": 0.95}
            }
        """
        query = {
            "from": table,
            "where": where,
            # v1 takes a bare field name; v2 takes a list of fields and
            # rejects the string form ("field 'relate' must be of type
            # 'Null|<object>'"). One field either way here.
            "relate": [relate_field] if self._api_version == "v2" else relate_field,
        }
        try:
            response = self._request("POST", "/_relate", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("relate")
            raise
        return _canonical_relate_hits(response, self._api_version)

    def search(self, table: str, where: dict, limit: int = 10) -> dict:
        """Run a _search query to retrieve matching rows."""
        query = {
            "from": table,
            "where": where,
            "limit": limit,
        }
        try:
            return self._request("POST", "/_search", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("search")
            raise

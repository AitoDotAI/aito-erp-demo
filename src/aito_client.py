"""HTTP client for Aito's predictive database API.

Thin wrapper — each method maps to one Aito operation. No abstraction
beyond authentication, error handling, and the v1↔v2 response
normalisation described below. An outside developer reading this file
should see exactly what calls are made and what shapes come back.

Aito API docs: https://aito.ai/docs/api/  ·  v2: https://aito.ai/docs/v2/

Two API versions, two transports
────────────────────────────────
`api_version` selects the REST surface: `v1` (the production default)
or `v2` (the rep2 engine, running against a tenant's `v2` environment).

**v1 is hand-rolled `httpx` here. v2 goes through the published SDK**
(`aitoai`'s `aito.client.v2.AitoClientV2`), which is the supported client
path and is where the v2 wire details now live — the enforced named
endpoints, the structured error codes, the `warnings` channel, and the
fact that `_evaluate`'s payload is enveloped for a collection but flat
for a legacy table. `self._v2` is the switch: `None` means v1, and every
method below reads it.

The v1 branches remain because the demo still ships on v1 by default.
When it flips, they go, and this file becomes a thin adapter over the SDK
— the services above it never see the difference either way.

The endpoints and query bodies are near-identical between versions; a
handful of response shapes are not. Rather than teach eleven service
modules two dialects, this client normalises **both** versions onto one
canonical shape, and that shape is v2's — the destination, not the legacy:

  | Concept          | v1 wire shape                     | v2 wire shape        | canonical |
  |------------------|-----------------------------------|----------------------|-----------|
  | predicted value  | `$value` (also `feature`)         | `hit["$value"]`      | `$value`  |
  | relate target    | `relate: "supplier"`              | `relate: ["supplier"]` | n/a (request) |
  | relate hit value | `related.supplier.$has`           | `related.supplier`   | `$has` unwrapped |
  | relate probs     | `ps: {p, pOnCondition, …}` smoothed | `ps` empirical     | as sent   |
  | evaluate body    | flat `{accuracy, …}`              | `{kind, data: {…}}`  | flat      |

Each translation is explicit and one-directional (v1 → canonical, or
v2 → canonical); nothing is guessed or dropped. When v1 support is
retired, every `if self._api_version == "v1"` branch here goes with it
and the services need no further change.
"""

import time
from typing import Any

import httpx
from aito.client.v2 import AitoClientV2, AitoV2Error

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


class _TimedAitoClientV2(AitoClientV2):
    """`AitoClientV2` that reports each call to the per-request timing context.

    The SDK has no timing hook, and it hands back parsed JSON rather than the
    response object, so the `x-aitoai-response-time` header the v1 path prefers
    is not reachable through it. That costs nothing here: v2 does not send that
    header anyway (docs/v2-migration.md §8), so this path was already measuring
    wall-clock. `request()` is the one seam every SDK call funnels through,
    which makes overriding it enough to keep the latency pill working.
    """

    def request(self, method: str, path: str, query: Any = None,
                timeout: float | None = None) -> Any:
        start = time.perf_counter()
        try:
            return super().request(method, path, query, timeout=timeout)
        finally:
            # Recorded even when the call raised: a request that took 30 s and
            # then failed is exactly the one worth seeing in the timings.
            timing.record_call(path, (time.perf_counter() - start) * 1000)


def _is_missing_table_error(exc: "AitoError", table: str) -> bool:
    """Detect Aito's "no such table" response, on either API version.

    Returned when a query targets a table that doesn't exist in the
    tenant's DB — a normal demo-life situation if data hasn't been
    loaded yet for that tenant. Letting it bubble up as a 500 makes
    the whole page break; treating it as "empty result" keeps the
    page renderable so visitors see structure, not a stack trace.

    v1 answers `400 failed to open '<table>'`. The message is matched
    against the table name so an unrelated 400 still raises. (v2 has its
    own path: the SDK raises a typed error and `_v2_result` reads its
    `is_not_found`.)
    """
    if not isinstance(exc, AitoError):
        return False
    return exc.status_code == 400 and f"failed to open '{table}'" in str(exc)


def _canonical_predicted_values(response: dict, api_version: ApiVersion) -> dict:
    """Fold a legacy `feature` hit key into the canonical `$value`.

    `predict` now selects `$value` on both API versions, so a predict
    response never carries `feature` at all. This still runs because
    v2's `_match` returns both keys as back-compat aliases of the same
    value — and because a hit that carries neither is left alone rather
    than patched with a placeholder: a shape we don't recognise should
    surface as a KeyError at the call site, not as an empty prediction.
    """
    for hit in response.get("hits", []):
        if "feature" in hit:
            legacy = hit.pop("feature")
            # v2's `_match` returns BOTH keys as aliases of one value.
            # Never let the legacy one overwrite the canonical one.
            hit.setdefault("$value", legacy)
    return response


def _canonical_relate_hits(response: dict, api_version: ApiVersion) -> dict:
    """Normalise a `_relate` response onto the canonical shape.

    Two v1↔v2 differences, both in the hit body:

    * `related` — v1 wraps the matched value in the operator that
      matched it (`{"supplier": {"$has": "Neste Oyj"}}`); v2 returns the
      value directly (`{"supplier": "Neste Oyj"}`). We unwrap v1 so
      callers read one shape.
    * `ps` — core `38a234a6` returns it on v2 too, so the loop below
      leaves it alone (`if "ps" in hit`). Builds before that returned
      `fs` only, and the demo reads `ps.pOnCondition` for a headline
      percentage — a missing key renders as `0.0`, a plausible number
      that is silently wrong. The derivation stays as the fallback that
      makes that failure impossible rather than quiet. It computes the
      same plain empirical ratios v2 now sends (v1's are smoothed and
      differ slightly). See docs/v2-migration.md §3.
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
        self._v2 = self._make_v2()

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
        instance._v2 = instance._make_v2()
        return instance

    def _make_v2(self) -> "_TimedAitoClientV2 | None":
        """The SDK client backing the v2 path, or None when talking v1.

        `None` is the version switch: every method below reads `self._v2` to
        decide, so the v1 branches stay exactly as they were and there is one
        place that knows which surface is live.

        The v2 credential's `api_url` already carries its `/env/<name>` segment,
        so the SDK is pointed at it whole rather than told the env separately.
        `check_credentials=False` keeps construction free of a network call --
        the multi-tenant resolver builds one of these per tenant per request.
        """
        if self._api_version != "v2":
            return None
        return _TimedAitoClientV2(
            self._base_url,
            self._headers["x-api-key"],
            timeout=30.0,
            check_credentials=False,
            # A warning means the server answered a broader query than we sent.
            # Worth a log line; not worth blanking a panel in a demo.
            on_warning="log",
        )

    def _v2_result(self, kind: str, table: str, call, extract=lambda resp: resp.json):
        """Run one SDK call and hand back the shape the services expect.

        Two things the SDK does not do for us, both handled once here rather
        than at fifty-eight call sites:

        * `AitoV2Error` is not our `AitoError`, and twenty-two modules catch
          ours. Untranslated, every existing `except AitoError` would stop
          catching Aito failures the moment the demo moved to v2 -- a silent
          loss of error handling, which is worse than a loud break.
        * `is_not_found` says *something* was missing, not *what*. The table
          name is still matched so `tolerate_missing` cannot swallow an
          unrelated 404 -- the same guard the v1 path has always had.
        """
        try:
            return extract(call())
        except AitoV2Error as exc:
            if (self._tolerate_missing and exc.is_not_found
                    and f"{table} not found" in str(exc)):
                return self._empty(kind)
            raise AitoError(str(exc), status_code=exc.status_code,
                            body=exc.body) from exc

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
        if self._v2 is not None:
            try:
                return self._v2.get_schema()
            except AitoV2Error as exc:
                raise AitoError(str(exc), status_code=exc.status_code,
                                body=exc.body) from exc
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
        if kind == "evaluate_cases":
            return {"accuracy": None, "baseAccuracy": None, "cases": []}
        if kind == "recommend":
            return {"hits": []}
        return {"hits": [], "offset": 0, "total": 0}

    def predict(self, table: str, where: dict, predict_field: str,
                limit: int = 10,
                select_extra: list[str] | None = None) -> dict:
        """Run a _predict query.

        `select_extra` adds field names to the projection. It exists for
        LINK targets: when `predict_field` links to another table, Aito
        will return the matched row's columns — but only if you ask for
        them. With no `select` at all it returns them by default; the
        moment this client names a `select` (which it must, for `$why`),
        that default is replaced. So a caller predicting `person` passes
        `["title", "skills", "site"]` and gets the ranking and the
        matched person's profile from one call instead of two.

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
        # Sentinel highlight tags — the frontend splits on them and renders
        # without dangerouslySetInnerHTML.
        why_select = {"$why": {"highlight": {"posPreTag": "«", "posPostTag": "»"}}}

        if self._v2 is not None:
            return self._v2_result("predict", table, lambda: self._v2.predict(
                from_table=table, where=where, predict=predict_field,
                select=["$p", "$value", why_select, *(select_extra or [])],
                limit=limit))

        # `$value` on BOTH versions. v1 also answers to `feature`, which
        # is what this used to send — but only for a plain column. Ask
        # for `feature` when the predicted field is a LINK and v1 fails
        # the whole query with `field 'feature' not found`, because the
        # predicted value there is a linked row rather than a column of
        # this table. `$value` is accepted for String, Boolean and link
        # targets alike, so there is one spelling and no shim.
        query = {
            "from": table,
            "where": where,
            "predict": predict_field,
            "select": ["$p", "$value", why_select, *(select_extra or [])],
            "limit": limit,
        }
        try:
            response = self._request("POST", "/_predict", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("predict")
            raise
        return _canonical_predicted_values(response, self._api_version)

    def estimate(self, table: str, where: dict, estimate_field: str) -> dict:
        """Run an `_estimate` query — a numeric value from neighbours.

        Returns `{"estimate": <number>, "why": {...}}`. The `why` is a
        `weightedAverage` whose components are `neighborContext` entries
        — the comparable rows and how much each counted — so an estimate
        can be shown next to the projects it came from rather than as a
        number from nowhere.

        Example:
            client.estimate(
                table="projects",
                where={"project_type": "implementation",
                       "scope_clarity": "unclear"},
                estimate_field="actual_cost_eur",
            )
        """
        query = {"from": table, "where": where, "estimate": estimate_field}
        if self._v2 is not None:
            return self._v2_result("estimate", table,
                                   lambda: self._v2.estimate(query),
                                   extract=lambda resp: resp.data)
        try:
            return self._request("POST", "/_estimate", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return {}
            raise

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
        if self._v2 is not None:
            # `.data` is the SDK's unwrapped payload. It is doing the work
            # `_unwrap_v2_envelope` used to do below — and doing it more
            # carefully, because the envelope is only present when the target
            # is a v2 collection (see docs/v2-migration.md §4).
            return self._v2_result("evaluate", table,
                                   lambda: self._v2.evaluate(query),
                                   extract=lambda resp: resp.data)
        try:
            response = self._request("POST", "/_evaluate", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("evaluate")
            raise
        return response

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
        if self._v2 is not None:
            result = self._v2_result("evaluate_cases", table,
                                     lambda: self._v2.evaluate(query),
                                     extract=lambda resp: resp.data)
        else:
            try:
                response = self._request("POST", "/_evaluate", json=query)
            except AitoError as exc:
                if self._tolerate_missing and _is_missing_table_error(exc, table):
                    return self._empty("evaluate_cases")
                raise
            result = response
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
        if self._v2 is not None:
            return self._v2_result("recommend", table, lambda: self._v2.recommend(
                from_table=table, where=where, recommend=recommend_field,
                goal=goal, select=select, limit=limit))

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
        if self._v2 is not None:
            # The SDK wraps a bare field name into the list v2 requires.
            response = self._v2_result("relate", table, lambda: self._v2.relate(
                from_table=table, where=where, relate=relate_field))
            return _canonical_relate_hits(response, self._api_version)

        query = {
            "from": table,
            "where": where,
            # v1 takes a bare field name; v2 takes a list of fields.
            "relate": relate_field,
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
        if self._v2 is not None:
            return self._v2_result("search", table, lambda: self._v2.search(
                from_table=table, where=where, limit=limit))
        try:
            return self._request("POST", "/_search", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("search")
            raise

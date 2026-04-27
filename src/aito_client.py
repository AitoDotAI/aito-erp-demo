"""HTTP client for Aito's predictive database API.

Thin wrapper — each method maps directly to an Aito REST endpoint.
No abstraction beyond authentication and error handling. An outside
developer reading this file should see exactly what HTTP calls are
made and what response shapes come back.

Aito API docs: https://aito.ai/docs/api/
"""

from typing import Any

import httpx

from src.config import Config


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
    """Detect Aito's `failed to open '<table>'` 400 response.

    Returned when a query targets a table that doesn't exist in the
    tenant's DB — a normal demo-life situation if data hasn't been
    loaded yet for that tenant. Letting it bubble up as a 500 makes
    the whole page break; treating it as "empty result" keeps the
    page renderable so visitors see structure, not a stack trace.
    """
    if not isinstance(exc, AitoError) or exc.status_code != 400:
        return False
    return f"failed to open '{table}'" in str(exc)


class AitoClient:
    """Synchronous client for the Aito REST API."""

    def __init__(self, config: Config) -> None:
        self._base_url = config.aito_api_url
        self._headers = {
            "x-api-key": config.aito_api_key,
            "content-type": "application/json",
        }
        # When set, missing-table errors return an empty canonical
        # response instead of raising. Enabled per-tenant in app.py.
        self._tolerate_missing = False

    @classmethod
    def from_creds(cls, api_url: str, api_key: str,
                   tolerate_missing: bool = False) -> "AitoClient":
        """Build a client from raw credentials. Used by the multi-tenant
        resolver so we don't need a synthetic Config per tenant."""
        instance = cls.__new__(cls)
        instance._base_url = api_url.rstrip("/")
        instance._headers = {
            "x-api-key": api_key,
            "content-type": "application/json",
        }
        instance._tolerate_missing = tolerate_missing
        return instance

    def _url(self, path: str) -> str:
        return f"{self._base_url}/api/v1{path}"

    def _request(self, method: str, path: str, json: dict | None = None) -> Any:
        """Make an HTTP request to Aito and return the parsed JSON response.

        Raises AitoError on non-2xx status or connection failure.
        """
        try:
            response = httpx.request(
                method,
                self._url(path),
                headers=self._headers,
                json=json,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise AitoError(
                f"Aito request failed: {method} {path}: {exc}"
            ) from exc

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
        return {"hits": [], "offset": 0, "total": 0}

    def predict(self, table: str, where: dict, predict_field: str, limit: int = 10) -> dict:
        """Run a _predict query.

        Example:
            client.predict(
                table="purchases",
                where={"supplier": "Elenia Oy", "description": "Electricity"},
                predict_field="account_code",
            )

        Returns Aito response with hits like:
            {"$p": 0.94, "feature": "6110", "$why": {...}}

        Note: Aito returns the predicted value in "feature", not in a
        key named after the field.
        """
        query = {
            "from": table,
            "where": where,
            "predict": predict_field,
            "select": [
                "$p",
                "feature",
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
            return self._request("POST", "/_predict", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("predict")
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
        try:
            return self._request("POST", "/_evaluate", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("evaluate")
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
              "related": {"supplier": {"$has": "Neste Oyj"}},
              "lift": 2.4,
              "fs": {"f": 33, "fOnCondition": 18, ...},
              "ps": {"p": 0.14, "pOnCondition": 0.95, ...}
            }
        """
        query = {
            "from": table,
            "where": where,
            "relate": relate_field,
        }
        try:
            return self._request("POST", "/_relate", json=query)
        except AitoError as exc:
            if self._tolerate_missing and _is_missing_table_error(exc, table):
                return self._empty("relate")
            raise

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

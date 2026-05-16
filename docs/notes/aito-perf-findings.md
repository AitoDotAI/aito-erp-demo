# Aito performance findings

Slow paths and gotchas surfaced while making the demo responsive on
a shared Aito instance. New findings should land here so future
iterations don't regress and the sibling demos
(`aito-accounting-demo`, `aito-ecommerce-demo`) can apply the same
fixes — they share much of the same code shape.

---

## 1. `httpx.request(...)` per call repeats TLS handshake every request

### Symptom

Every `_recommend` / `_search` / `_predict` call paid 200-300 ms of
"network overhead" on top of Aito's server-side time. Same payload,
same client process — the overhead repeated per call.

### Diagnosis

Aito returns server-side execution time in the
`x-aitoai-response-time` response header. Splitting client wall-clock
against that header isolated the network/proxy cost cleanly:

```
requests.post() — fresh connection each call:
  #1: client=1533ms  server=1300ms  net=232ms
  #2: client=219ms   server=37ms    net=182ms
  #3: client=196ms   server=36ms    net=160ms

requests.Session() — pooled keep-alive connection:
  #1: client=249ms   server=38ms    net=211ms   ← TLS handshake
  #2: client=99ms    server=42ms    net=57ms    ← pooled
  #3: client=92ms    server=35ms    net=57ms
```

Pooled connection ⇒ network overhead drops from ~200 ms to ~57 ms
(pure RTT). The 150 ms difference is the TLS handshake, paid once
on the first call and never again.

`src/aito_client.py` was using `httpx.request(...)` — a top-level
helper that opens a fresh `httpx.Client` (and a fresh TCP+TLS
connection) per call. Every call paid the handshake.

### Workaround

Hold a single `httpx.Client` on the `AitoClient` instance and use
its `.request(...)` method. Both constructor paths (`__init__` and
`from_creds` for the multi-tenant resolver) initialise the pool:

```python
class AitoClient:
    def __init__(self, config):
        # ...existing fields...
        self._client = httpx.Client(headers=self._headers, timeout=30.0)

    @classmethod
    def from_creds(cls, api_url, api_key, tolerate_missing=False):
        instance = cls.__new__(cls)
        # ...existing fields...
        instance._client = httpx.Client(headers=instance._headers, timeout=30.0)
        return instance

    def _request(self, method, path, json=None):
        response = self._client.request(method, self._url(path), json=json)
```

Measured on the live shared Aito instance after the fix:
~280 ms client-side per call → **~110 ms steady-state** (~3× faster,
identical request payloads).

### Cross-demo applicability

Same bug existed in `aito-accounting-demo/src/aito_client.py` and
`aito-ecommerce-demo/src/aito_client.py`; all three fixed in parallel
PRs. `aito-demo` (JS) is fine — `fetch()` in modern Node pools via
the global undici agent.

### What we'd hope from core

Nothing API-side — this is purely a client-side fix. But the official
Python SDK (when it exists) should default to a pooled client, and
the docs' Python examples should not show `httpx.request(...)` per
call.

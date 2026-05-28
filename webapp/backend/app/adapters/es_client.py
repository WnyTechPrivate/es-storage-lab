"""Per-connection Elasticsearch HTTP client.

Replaces the env-var based `scripts/config.py` `es()` with a class that takes
host/user/pass at runtime, so the UI can drive multiple clusters in one
process. TLS verification is always disabled per product requirement.
"""
from __future__ import annotations
import urllib3
import requests
from typing import Any, Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ESClient:
    def __init__(self, host: str, user: str, password: str, timeout: int = 120):
        self.host = host.rstrip("/")
        self.user = user
        self.password = password
        self.timeout = timeout
        self._sess: Optional[requests.Session] = None

    def session(self) -> requests.Session:
        if self._sess is None:
            s = requests.Session()
            s.auth = (self.user, self.password)
            s.verify = False
            s.headers.update({"Content-Type": "application/json"})
            self._sess = s
        return self._sess

    def request(self, method: str, path: str, **kw) -> Any:
        url = f"{self.host}{path}"
        try:
            r = self.session().request(method, url, timeout=self.timeout, **kw)
        except requests.RequestException as e:
            # transport errors (DNS, refused, TLS, timeout) → uniform RuntimeError
            raise RuntimeError(f"{method} {path} -> connection error: {e}") from e
        if not r.ok:
            raise RuntimeError(f"{method} {path} -> {r.status_code}\n{r.text[:500]}")
        if not r.content:
            return None
        try:
            return r.json()
        except Exception:
            return r.text

    def get(self, path: str, **kw):    return self.request("GET", path, **kw)
    def post(self, path: str, **kw):   return self.request("POST", path, **kw)
    def put(self, path: str, **kw):    return self.request("PUT", path, **kw)
    def delete(self, path: str, **kw): return self.request("DELETE", path, **kw)

    def info(self) -> dict:
        """GET / — version, cluster_name, etc."""
        return self.get("/")

    def license(self) -> dict:
        return self.get("/_license")

    def ping(self) -> bool:
        try:
            self.info()
            return True
        except Exception:
            return False

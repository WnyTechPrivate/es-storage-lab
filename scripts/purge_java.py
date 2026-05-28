"""One-shot purge of java-dataset resources from a cluster.

Deletes:
- data streams      : logs-baseline-java, logs-{case}.{...}-java (24 cases)
- index templates   : tpl-baseline-java, tpl-{case}.{...}-java
- ingest pipelines  : raw_ingest_java, parsing2_full_java, parsing3_parsed_only_java

Usage (set ES_HOST/ES_USER/ES_PASS as env vars first):
    py purge_java.py
"""
from __future__ import annotations
import os
import urllib3
import requests
from itertools import product

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HOST = os.environ.get("ES_HOST", "https://192.168.200.71:9200")
USER = os.environ.get("ES_USER", "elastic")
PASS = os.environ.get("ES_PASS", "")

if not PASS:
    raise SystemExit("Set ES_PASS env var first.")

S = requests.Session()
S.auth = (USER, PASS)
S.verify = False
S.headers["Content-Type"] = "application/json"

MODES   = ("std", "ldb")
SOURCES = ("str", "syn")
CODECS  = ("lz4", "zstd")
PARSING = ("p1", "p2", "p3")
PIPELINES = ("raw_ingest_java", "parsing2_full_java", "parsing3_parsed_only_java")


def case_names():
    for m, s, c, p in product(MODES, SOURCES, CODECS, PARSING):
        yield f"{m}.{s}.{c}.if.df.{p}"


def safe_delete(label: str, url: str) -> None:
    r = S.delete(url, timeout=30)
    if r.status_code == 200:
        print(f"  [OK]    {label}")
    elif r.status_code == 404:
        print(f"  [skip]  {label}  (not found)")
    else:
        print(f"  [FAIL]  {label}  -> {r.status_code} {r.text[:200]}")


def main() -> None:
    print(f"target cluster: {HOST}\n")

    print("== data streams ==")
    safe_delete("logs-baseline-java", f"{HOST}/_data_stream/logs-baseline-java")
    for c in case_names():
        ds = f"logs-{c}-java"
        safe_delete(ds, f"{HOST}/_data_stream/{ds}")

    print("\n== index templates ==")
    safe_delete("tpl-baseline-java", f"{HOST}/_index_template/tpl-baseline-java")
    for c in case_names():
        name = f"tpl-{c}-java"
        safe_delete(name, f"{HOST}/_index_template/{name}")

    print("\n== ingest pipelines ==")
    for p in PIPELINES:
        safe_delete(p, f"{HOST}/_ingest/pipeline/{p}")

    print("\nDone.")


if __name__ == "__main__":
    main()

"""Collect storage metrics for baseline + each case.

Mirrors scripts/04_measure.py. Key change: raw_size_bytes is supplied by the
caller (the run's raw input — what the user generated or selected), not the
fixed `data/raw_sample.log` file size.
"""
from __future__ import annotations
import time
from typing import Iterable, Optional
from ..adapters.es_client import ESClient
from ..adapters.cases import CaseSpec


def _backing_index(client: ESClient, ds_name: str) -> Optional[str]:
    j = client.get(f"/_data_stream/{ds_name}")
    streams = j.get("data_streams", [])
    if not streams:
        return None
    idxs = streams[0]["indices"]
    return idxs[-1]["index_name"] if idxs else None


def _cat_index(client: ESClient, idx: str) -> dict:
    rows = client.get(
        f"/_cat/indices/{idx}?format=json&bytes=b&h=index,docs.count,pri.store.size,store.size"
    )
    return rows[0] if rows else {}


def _disk_usage(client: ESClient, idx: str) -> dict:
    return client.post(f"/{idx}/_disk_usage?run_expensive_tasks=true")


def _af_bytes(af: dict, name: str) -> int:
    v = af.get(f"{name}_in_bytes")
    if v is not None:
        return v
    sub = af.get(name)
    if isinstance(sub, dict):
        return sub.get("total_in_bytes", 0)
    return 0


def _field_bytes(d) -> int:
    if not isinstance(d, dict):
        return 0
    return d.get("total_in_bytes", 0)


def measure_one(client: ESClient, case_name: str, ds_name: str, raw_size_bytes: int) -> Optional[dict]:
    # Stabilize before measuring: force a refresh and give Lucene a moment
    # to finish any post-merge bookkeeping that can flicker store size.
    try:
        client.post(f"/{ds_name}/_refresh")
        time.sleep(0.4)
    except Exception:
        pass
    idx = _backing_index(client, ds_name)
    if not idx:
        return None
    cat = _cat_index(client, idx)
    du = _disk_usage(client, idx)
    body = du.get(idx, {})
    af = body.get("all_fields", {})
    fields = body.get("fields", {}) or {}
    ig = fields.get("_ignored_source") or fields.get("_ignored") or {}

    docs = int(cat.get("docs.count", 0) or 0)
    pri  = int(cat.get("pri.store.size", 0) or 0)
    return {
        "case":              case_name,
        "datastream":        ds_name,
        "backing_index":     idx,
        "docs":              docs,
        "raw_bytes":         raw_size_bytes,
        "pri_store_bytes":   pri,
        "ratio_pri_over_raw": (pri / raw_size_bytes) if raw_size_bytes else None,
        "inverted_index_b":  _af_bytes(af, "inverted_index"),
        "doc_values_b":      _af_bytes(af, "doc_values"),
        "stored_fields_b":   _af_bytes(af, "stored_fields"),
        "points_b":          _af_bytes(af, "points"),
        "norms_b":           _af_bytes(af, "norms"),
        "term_vectors_b":    _af_bytes(af, "term_vectors"),
        "knn_vectors_b":     _af_bytes(af, "knn_vectors"),
        "ignored_source_b":  _field_bytes(ig),
    }


def measure_all(client: ESClient, specs: Iterable[CaseSpec], raw_size_bytes: int,
                baseline_ds: str = "logs-baseline-default") -> list[dict]:
    """Measure baseline + every case."""
    rows: list[dict] = []
    baseline = measure_one(client, "baseline", baseline_ds, raw_size_bytes)
    if baseline:
        rows.append(baseline)
    for spec in specs:
        try:
            r = measure_one(client, spec.name, spec.datastream, raw_size_bytes)
            if r:
                rows.append(r)
        except Exception as e:
            rows.append({"case": spec.name, "datastream": spec.datastream,
                         "error": str(e)[:300]})
    return rows

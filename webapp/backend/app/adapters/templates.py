"""Build ES index templates for the 36-case matrix (std × ldb × tsds).

Per-case differences live in `settings` (mode / source / codec /
default_pipeline). For TSDS additionally:
  - `index.mode: "time_series"`
  - `index.routing_path: [...]`     ← dataset-specific dimension fields
  - `index.look_back_time / look_ahead_time` widened so reindex works
And the case template's `mappings.properties` merges in `dimension_overrides`
for that dataset, regardless of mode (std/ldb keep the same shape so the
comparison stays fair; `time_series_dimension` is a no-op outside TSDS).

`dataset` selects which ingest pipeline triplet is used for p2/p3 and which
baseline data stream the template attaches to.
"""
from __future__ import annotations
from copy import deepcopy
from .cases import CaseSpec, baseline_ds, baseline_template_name, namespace_of

DATASET_PIPELINES = {
    "firewall": {"p2": "parsing2_full",         "p3": "parsing3_parsed_only",
                 "raw": "raw_ingest"},
    "web":      {"p2": "parsing2_full_service", "p3": "parsing3_parsed_only_service",
                 "raw": "raw_ingest_service"},
    "snmp":     {"p2": "parsing2_full_snmp",    "p3": "parsing3_parsed_only_snmp",
                 "raw": "raw_ingest_snmp"},
}

# dataset → TSDS routing path + dimension/metric field overrides
DATASET_DIMENSIONS: dict[str, dict] = {
    "firewall": {
        "routing_path": ["source.ip", "destination.ip"],
        "dimension_overrides": {
            "source":      {"properties": {"ip": {"type": "ip", "time_series_dimension": True}}},
            "destination": {"properties": {"ip": {"type": "ip", "time_series_dimension": True}}},
        },
    },
    "web": {
        "routing_path": ["host.name", "service.name"],
        "dimension_overrides": {
            "host":    {"properties": {"name": {"type": "keyword", "time_series_dimension": True}}},
            "service": {"properties": {"name": {"type": "keyword", "time_series_dimension": True}}},
        },
    },
    "snmp": {
        "routing_path": ["observer.id_num", "snmp.metric_code"],
        "dimension_overrides": {
            "observer": {"properties": {
                "id_num":      {"type": "long", "time_series_dimension": True},
                "vendor_code": {"type": "long", "time_series_dimension": True},
                "type_code":   {"type": "long", "time_series_dimension": True},
            }},
            "snmp": {"properties": {
                "metric_code": {"type": "long", "time_series_dimension": True},
                "value":       {"type": "long", "time_series_metric": "gauge"},
            }},
            "network": {"properties": {"interface": {"properties": {
                "index": {"type": "long", "time_series_dimension": True}
            }}}}
        },
    },
}

EVENT_ORIGINAL_IGNORE_ABOVE = 8192

# TSDS reindex needs the doc timestamps to land inside the index's window.
# ES caps these at 7d (default cluster setting); the generators only emit
# within the last few hours so 7d is plenty.
TSDS_LOOK_BACK  = "7d"
TSDS_LOOK_AHEAD = "7d"


def _mode_setting(mode: str) -> str:
    if mode == "ldb":  return "logsdb"
    if mode == "tsds": return "time_series"
    return "standard"


def _settings(spec: CaseSpec, dataset: str) -> dict:
    s = {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "mapping": {"source": {"mode": "synthetic" if spec.src == "syn" else "stored"}},
            "codec": "best_compression" if spec.codec == "zstd" else "default",
            "mode": _mode_setting(spec.mode),
            "refresh_interval": "30s",
        }
    }
    pipes = DATASET_PIPELINES[dataset]
    if spec.parsing == "p2":
        s["index"]["default_pipeline"] = pipes["p2"]
    elif spec.parsing == "p3":
        s["index"]["default_pipeline"] = pipes["p3"]

    if spec.mode == "tsds":
        dims = DATASET_DIMENSIONS.get(dataset, {})
        s["index"]["routing_path"]    = list(dims.get("routing_path", []))
        s["index"]["look_back_time"]  = TSDS_LOOK_BACK
        s["index"]["look_ahead_time"] = TSDS_LOOK_AHEAD

    return s


def _deep_merge(dst: dict, src: dict) -> dict:
    """Recursively merge `src` into `dst` (dst is mutated and returned)."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _mappings(spec: CaseSpec, dataset: str) -> dict:
    # event.original stays disabled (index=false, doc_values=false — same as
    # ecs@mappings default) with ignore_above pinned for observability.
    props: dict = {
        "@timestamp": {"type": "date"},
        "event": {
            "properties": {
                "original": {
                    "type": "keyword",
                    "ignore_above": EVENT_ORIGINAL_IGNORE_ABOVE,
                    "index": False,
                    "doc_values": False,
                }
            }
        },
    }
    # Apply dataset's dimension/metric mappings to ALL modes so std/ldb/tsds
    # stay comparable. `time_series_dimension` / `time_series_metric` only
    # take effect under index.mode=time_series; elsewhere they're ignored.
    dims = DATASET_DIMENSIONS.get(dataset, {})
    for top_key, sub in dims.get("dimension_overrides", {}).items():
        existing = props.setdefault(top_key, {})
        _deep_merge(existing, deepcopy(sub))
    return {"properties": props}


def build_template(spec: CaseSpec, dataset: str = "firewall") -> dict:
    return {
        "name": spec.template_name,
        "body": {
            "index_patterns": [spec.datastream],
            "data_stream": {},
            "priority": 500,
            "composed_of": ["ecs@mappings"],
            "template": {
                "settings": _settings(spec, dataset),
                "mappings": _mappings(spec, dataset),
            },
            "_meta": {
                "case": spec.name,
                "dataset": dataset, "namespace": spec.namespace,
                "mode": spec.mode, "source": spec.src, "codec": spec.codec,
                "index": spec.idx, "doc_values": spec.dv, "parsing": spec.parsing,
            },
        },
    }


def build_baseline_template(dataset: str = "firewall") -> dict:
    """Baseline stays standard mode (reindex source). One per dataset."""
    ds = baseline_ds(dataset)
    pipes = DATASET_PIPELINES[dataset]
    return {
        "name": baseline_template_name(dataset),
        "body": {
            "index_patterns": [ds],
            "data_stream": {},
            "priority": 500,
            "composed_of": ["ecs@mappings"],
            "template": {
                "settings": {
                    "index": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                        "mapping": {"source": {"mode": "stored"}},
                        "codec": "default",
                        "mode": "standard",
                        "refresh_interval": "30s",
                        "default_pipeline": pipes["raw"],
                    }
                },
                "mappings": {
                    "properties": {
                        "@timestamp": {"type": "date"},
                        "event": {
                            "properties": {
                                "original": {
                                    "type": "keyword",
                                    "ignore_above": EVENT_ORIGINAL_IGNORE_ABOVE,
                                    "index": True,
                                    "doc_values": True,
                                }
                            }
                        },
                    }
                },
            },
            "_meta": {"role": "baseline", "dataset": dataset,
                      "namespace": namespace_of(dataset)},
        },
    }

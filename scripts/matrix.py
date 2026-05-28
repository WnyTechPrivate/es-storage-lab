"""Build the 96-case index-template matrix."""
from config import (
    MODES, SOURCES, CODECS, IDX_OPTS, DV_OPTS, PARSINGS,
    case_name, datastream_of,
)


def _settings(mode, src, codec, parsing):
    s = {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "mapping": {"source": {"mode": "synthetic" if src == "syn" else "stored"}},
            "codec": "best_compression" if codec == "zstd" else "default",
            "mode": "logsdb" if mode == "ldb" else "standard",
            "refresh_interval": "30s",
        }
    }
    if parsing == "p2":
        s["index"]["default_pipeline"] = "parsing2_full"
    elif parsing == "p3":
        s["index"]["default_pipeline"] = "parsing3_parsed_only"
    return s


def _dyn_templates(idx_opt, dv_opt):
    idx_b = idx_opt == "it"
    dv_b  = dv_opt  == "dt"
    str_map = {
        "type": "keyword",
        "ignore_above": 8192,
        "index": idx_b,
        "doc_values": dv_b,
    }
    num_map = {"type": "long", "index": idx_b, "doc_values": dv_b}
    flt_map = {"type": "double", "index": idx_b, "doc_values": dv_b}
    bool_map = {"type": "boolean", "index": idx_b, "doc_values": dv_b}
    return [
        {"strings_as_keyword": {
            "match_mapping_type": "string",
            "unmatch": ["@timestamp"],
            "mapping": str_map,
        }},
        {"longs":   {"match_mapping_type": "long",    "mapping": num_map}},
        {"doubles": {"match_mapping_type": "double",  "mapping": flt_map}},
        {"bools":   {"match_mapping_type": "boolean", "mapping": bool_map}},
    ]


def _mappings(idx_opt, dv_opt, parsing):
    props = {
        "@timestamp": {"type": "date"},
        "event": {
            "properties": {
                "original": {"type": "keyword", "ignore_above": 8192, "doc_values": True, "index": True},
                "category": {"type": "keyword"},
                "duration": {"type": "long"},
            }
        },
        "source":      {"properties": {"ip": {"type": "ip"}}},
        "destination": {"properties": {"ip": {"type": "ip"}}},
        "client":      {"properties": {"ip": {"type": "ip"}}},
        "server":      {"properties": {"ip": {"type": "ip"}}},
    }
    # parsing3 drops event.original → keep mapping anyway, no harm if absent
    return {
        "dynamic_templates": _dyn_templates(idx_opt, dv_opt),
        "properties": props,
    }


def build_template(mode, src, codec, idx_opt, dv_opt, parsing):
    case = case_name(mode, src, codec, idx_opt, dv_opt, parsing)
    ds = datastream_of(case)
    return {
        "name": f"tpl-{case}",
        "body": {
            "index_patterns": [ds],
            "data_stream": {},
            "priority": 500,
            "template": {
                "settings": _settings(mode, src, codec, parsing),
                "mappings": _mappings(idx_opt, dv_opt, parsing),
            },
            "_meta": {
                "case": case,
                "mode": mode, "source": src, "codec": codec,
                "index": idx_opt, "doc_values": dv_opt, "parsing": parsing,
            },
        },
    }


def build_baseline_template():
    return {
        "name": "tpl-baseline",
        "body": {
            "index_patterns": ["logs-baseline-default"],
            "data_stream": {},
            "priority": 500,
            "template": {
                "settings": {
                    "index": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                        "mapping": {"source": {"mode": "stored"}},
                        "codec": "default",
                        "mode": "standard",
                        "refresh_interval": "30s",
                        "default_pipeline": "raw_ingest",
                    }
                },
                "mappings": {
                    "dynamic_templates": [
                        {"strings_as_keyword": {
                            "match_mapping_type": "string",
                            "unmatch": ["@timestamp"],
                            "mapping": {"type": "keyword", "ignore_above": 8192},
                        }},
                    ],
                    "properties": {
                        "@timestamp": {"type": "date"},
                        "event": {"properties": {"original": {"type": "keyword", "ignore_above": 8192, "doc_values": True, "index": True}}},
                    },
                },
            },
            "_meta": {"role": "baseline"},
        },
    }


def all_templates():
    out = [build_baseline_template()]
    for m in MODES:
        for s in SOURCES:
            for c in CODECS:
                for i in IDX_OPTS:
                    for d in DV_OPTS:
                        for p in PARSINGS:
                            out.append(build_template(m, s, c, i, d, p))
    return out

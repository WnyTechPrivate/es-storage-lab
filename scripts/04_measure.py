"""Collect storage metrics for baseline + 96 cases."""
import csv
import json
import time
from config import es, RESULT_DIR, all_cases, datastream_of, DATA_DIR

BASELINE_DS = "logs-baseline-default"
CSV_PATH    = RESULT_DIR / "measurements.csv"
JSON_PATH   = RESULT_DIR / "disk_usage_raw.json"


def backing_index(ds_name):
    j = es("GET", f"/_data_stream/{ds_name}")
    streams = j.get("data_streams", [])
    if not streams:
        return None
    idxs = streams[0]["indices"]
    return idxs[-1]["index_name"] if idxs else None


def cat_index(idx):
    rows = es("GET", f"/_cat/indices/{idx}?format=json&bytes=b&h=index,docs.count,pri.store.size,store.size")
    return rows[0] if rows else {}


def disk_usage(idx):
    return es("POST", f"/{idx}/_disk_usage?run_expensive_tasks=true")


def measure(case_name, ds_name, raw_size_bytes):
    idx = backing_index(ds_name)
    if not idx:
        return None, None
    cat = cat_index(idx)
    du = disk_usage(idx)
    body = du.get(idx, {})
    af = body.get("all_fields", {})
    fields = body.get("fields", {}) or {}
    ig = fields.get("_ignored_source") or fields.get("_ignored") or {}

    def af_bytes(name):
        v = af.get(f"{name}_in_bytes")
        if v is not None:
            return v
        sub = af.get(name)
        if isinstance(sub, dict):
            return sub.get("total_in_bytes", 0)
        return 0

    def field_bytes(d):
        if not isinstance(d, dict):
            return 0
        if "total_in_bytes" in d:
            return d.get("total_in_bytes", 0)
        return d.get("total_in_bytes", 0)

    docs = int(cat.get("docs.count", 0) or 0)
    pri  = int(cat.get("pri.store.size", 0) or 0)
    return {
        "case":              case_name,
        "datastream":        ds_name,
        "backing_index":     idx,
        "docs":              docs,
        "raw_bytes":         raw_size_bytes,
        "pri_store_bytes":   pri,
        "ratio_pri_over_raw":(pri / raw_size_bytes) if raw_size_bytes else None,
        "inverted_index_b":  af_bytes("inverted_index"),
        "doc_values_b":      af_bytes("doc_values"),
        "stored_fields_b":   af_bytes("stored_fields"),
        "points_b":          af_bytes("points"),
        "norms_b":           af_bytes("norms"),
        "term_vectors_b":    af_bytes("term_vectors"),
        "knn_vectors_b":     af_bytes("knn_vectors"),
        "ignored_source_b":  field_bytes(ig),
    }, body


def main():
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    raw_size = (DATA_DIR / "raw_sample.log").stat().st_size

    cases = [("baseline", BASELINE_DS)] + [(c, datastream_of(c)) for c in all_cases()]
    rows = []
    raw_disk_dump = {}
    for i, (case, ds) in enumerate(cases, 1):
        try:
            r, body = measure(case, ds, raw_size)
            if r:
                rows.append(r)
                raw_disk_dump[case] = body
                print(f"[{i:3d}/{len(cases)}] {case}: docs={r['docs']} pri={r['pri_store_bytes']} ratio={r['ratio_pri_over_raw']:.3f}")
            else:
                print(f"[{i:3d}/{len(cases)}] {case}: NO BACKING INDEX")
        except Exception as e:
            print(f"[{i:3d}/{len(cases)}] {case}: ERR {str(e)[:120]}")

    if not rows:
        print("no rows collected.")
        return

    keys = list(rows[0].keys())
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    JSON_PATH.write_text(json.dumps(raw_disk_dump, indent=2), encoding="utf-8")
    print(f"\nwrote {CSV_PATH} ({len(rows)} rows)")
    print(f"wrote {JSON_PATH}")


if __name__ == "__main__":
    main()

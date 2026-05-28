"""Delete all matrix + baseline data streams, templates, and pipelines (for re-runs)."""
from config import es, all_cases, datastream_of


def safe(method, path):
    try:
        es(method, path)
        return True
    except Exception as e:
        msg = str(e)
        if "404" in msg or "not_found" in msg:
            return False
        print(f"  {method} {path} -> {msg[:120]}")
        return False


def main():
    cases = ["baseline"] + all_cases()
    for c in cases:
        ds = "logs-baseline-default" if c == "baseline" else datastream_of(c)
        if safe("DELETE", f"/_data_stream/{ds}"):
            print(f"  deleted ds {ds}")
    for c in cases:
        name = "tpl-baseline" if c == "baseline" else f"tpl-{c}"
        if safe("DELETE", f"/_index_template/{name}"):
            print(f"  deleted tpl {name}")
    for p in ("raw_ingest", "parsing2_full", "parsing3_parsed_only"):
        if safe("DELETE", f"/_ingest/pipeline/{p}"):
            print(f"  deleted pipeline {p}")


if __name__ == "__main__":
    main()

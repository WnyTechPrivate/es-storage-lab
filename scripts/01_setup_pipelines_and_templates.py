"""Register ingest pipelines + 97 index templates (1 baseline + 96 matrix)."""
import json
from config import es, PIPE_DIR
from matrix import all_templates


def register_pipelines():
    for name in ("raw_ingest", "parsing2_full", "parsing3_parsed_only"):
        body = json.loads((PIPE_DIR / f"{name}.json").read_text(encoding="utf-8"))
        es("PUT", f"/_ingest/pipeline/{name}", json=body)
        print(f"  pipeline {name}: OK")


def register_templates():
    tpls = all_templates()
    print(f"applying {len(tpls)} index templates...")
    ok, fail = 0, 0
    for t in tpls:
        try:
            es("PUT", f"/_index_template/{t['name']}", json=t["body"])
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  FAIL {t['name']}: {e}")
    print(f"templates: ok={ok} fail={fail}")


if __name__ == "__main__":
    print("=== pipelines ===")
    register_pipelines()
    print("=== templates ===")
    register_templates()

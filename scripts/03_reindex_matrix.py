"""Reindex baseline -> 96 matrix data streams, then refresh + force_merge each."""
import json
import time
from config import es, RESULT_DIR, all_cases, datastream_of

SOURCE = "logs-baseline-default"
LOG = RESULT_DIR / "reindex_log.jsonl"


def reindex_one(case):
    dst = datastream_of(case)
    body = {
        "source": {"index": SOURCE},
        "dest":   {"index": dst, "op_type": "create"},
    }
    t0 = time.time()
    try:
        r = es("POST", "/_reindex?wait_for_completion=true&refresh=true", json=body)
        dur = time.time() - t0
        took = r.get("took", 0)
        created = r.get("created", 0)
        failures = r.get("failures", [])
        es("POST", f"/{dst}/_forcemerge?max_num_segments=1&wait_for_completion=true")
        es("POST", f"/{dst}/_refresh")
        return {
            "case": case, "ok": True, "created": created,
            "took_ms": took, "wall_s": round(dur, 2),
            "failures": failures[:3], "n_failures": len(failures),
        }
    except Exception as e:
        return {"case": case, "ok": False, "error": str(e)[:500]}


def main():
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    cases = all_cases()
    print(f"reindex baseline -> {len(cases)} targets")
    ok, fail = 0, 0
    with LOG.open("w", encoding="utf-8") as f:
        for i, case in enumerate(cases, 1):
            r = reindex_one(case)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if r["ok"]:
                ok += 1
                tag = "OK"
                extra = f"created={r['created']} took={r['took_ms']}ms"
            else:
                fail += 1
                tag = "FAIL"
                extra = r["error"][:120]
            print(f"[{i:3d}/{len(cases)}] {tag} {case}  {extra}")
    print(f"\ndone: ok={ok} fail={fail}")


if __name__ == "__main__":
    main()

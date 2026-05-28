"""Reindex baseline -> p2/p3 cases only (64 of them)."""
import json
import time
from config import es, RESULT_DIR, all_cases, datastream_of

SOURCE = "logs-baseline-default"
LOG = RESULT_DIR / "reindex_p2p3_log.jsonl"


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
        es("POST", f"/{dst}/_forcemerge?max_num_segments=1&wait_for_completion=true")
        es("POST", f"/{dst}/_refresh")
        return {"case": case, "ok": True, "created": r.get("created", 0),
                "took_ms": r.get("took", 0), "wall_s": round(dur, 2),
                "n_failures": len(r.get("failures", []))}
    except Exception as e:
        return {"case": case, "ok": False, "error": str(e)[:300]}


def main():
    cases = [c for c in all_cases() if c.endswith(".p2") or c.endswith(".p3")]
    print(f"reindex {len(cases)} p2/p3 targets")
    ok = fail = 0
    with LOG.open("w", encoding="utf-8") as f:
        for i, case in enumerate(cases, 1):
            r = reindex_one(case)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if r["ok"]:
                ok += 1
                extra = f"created={r['created']} took={r['took_ms']}ms"
            else:
                fail += 1
                extra = r["error"][:120]
            print(f"[{i:3d}/{len(cases)}] {'OK' if r['ok'] else 'FAIL'} {case}  {extra}")
    print(f"\ndone: ok={ok} fail={fail}")


if __name__ == "__main__":
    main()

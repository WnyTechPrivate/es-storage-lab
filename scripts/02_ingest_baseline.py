"""Ingest raw_sample.log into baseline data stream via _bulk."""
import json
import time
from config import es, DATA_DIR, session, ES_HOST

DS = "logs-baseline-default"
BATCH = 500
LOG = DATA_DIR / "raw_sample.log"


def bulk(lines):
    body = []
    for line in lines:
        body.append('{"create":{}}')
        body.append(json.dumps({"message": line.rstrip("\n")}, ensure_ascii=False))
    body.append("")
    payload = "\n".join(body)
    s = session()
    r = s.post(
        f"{ES_HOST}/{DS}/_bulk",
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        timeout=120,
    )
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        err_count = sum(1 for it in j["items"] if "error" in it.get("create", {}))
        print(f"  bulk errors: {err_count}/{len(lines)}")
        for it in j["items"][:3]:
            if "error" in it.get("create", {}):
                print(f"    sample: {it['create']['error']}")


def main():
    print(f"reading {LOG}")
    t0 = time.time()
    sent = 0
    batch = []
    with LOG.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            batch.append(line)
            if len(batch) >= BATCH:
                bulk(batch)
                sent += len(batch)
                batch = []
                if sent % 5000 == 0:
                    print(f"  sent {sent} docs")
        if batch:
            bulk(batch)
            sent += len(batch)
    dt = time.time() - t0
    print(f"ingested {sent} docs in {dt:.1f}s")
    print("refresh + forcemerge baseline...")
    es("POST", f"/{DS}/_refresh")
    es("POST", f"/{DS}/_forcemerge?max_num_segments=1&wait_for_completion=true")
    es("POST", f"/{DS}/_refresh")
    j = es("GET", f"/_data_stream/{DS}")
    ds = j["data_streams"][0]
    print(f"baseline backing indices: {[i['index_name'] for i in ds['indices']]}")


if __name__ == "__main__":
    main()

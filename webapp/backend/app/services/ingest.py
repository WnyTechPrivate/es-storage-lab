"""Bulk-ingest a raw log file into a baseline data stream.

Supports two payload shapes:
  - text-line  : each line becomes `{"message": "<line>"}`   (firewall syslog)
  - ndjson     : each line is already a JSON doc, sent as-is (web — message
                 plus pre-attached agent/host/log/ecs meta)
"""
from __future__ import annotations
from pathlib import Path
import json
from typing import Callable, Optional
from ..adapters.es_client import ESClient

ProgressCB = Callable[[int, int], None]   # (docs_sent, total_lines_estimate)


def _bulk(client: ESClient, baseline_ds: str, lines: list[str], ndjson: bool) -> dict:
    body: list[str] = []
    for line in lines:
        body.append('{"create":{}}')
        if ndjson:
            body.append(line.rstrip("\n"))
        else:
            body.append(json.dumps({"message": line.rstrip("\n")}, ensure_ascii=False))
    body.append("")
    payload = "\n".join(body).encode("utf-8")
    s = client.session()
    r = s.post(
        f"{client.host}/{baseline_ds}/_bulk",
        data=payload,
        headers={"Content-Type": "application/x-ndjson"},
        timeout=client.timeout,
    )
    r.raise_for_status()
    return r.json()


def count_lines(path: Path) -> int:
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def ingest_baseline(
    client: ESClient,
    log_path: Path,
    baseline_ds: str,
    batch_size: int = 500,
    progress: Optional[ProgressCB] = None,
    total_lines: Optional[int] = None,
    ndjson: bool = False,
) -> dict:
    """Stream a file into `baseline_ds` line-by-line.

    ndjson=False → wrap each line as {"message": line}
    ndjson=True  → forward each line as a full JSON doc
    """
    if total_lines is None:
        total_lines = count_lines(log_path)
    sent = 0
    errors = 0
    batch: list[str] = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            batch.append(line)
            if len(batch) >= batch_size:
                j = _bulk(client, baseline_ds, batch, ndjson)
                sent += len(batch)
                if j.get("errors"):
                    errors += sum(1 for it in j["items"] if "error" in it.get("create", {}))
                batch.clear()
                if progress:
                    progress(sent, total_lines)
        if batch:
            j = _bulk(client, baseline_ds, batch, ndjson)
            sent += len(batch)
            if j.get("errors"):
                errors += sum(1 for it in j["items"] if "error" in it.get("create", {}))
    if progress:
        progress(sent, total_lines)

    client.post(f"/{baseline_ds}/_refresh")
    fm = client.post(
        f"/{baseline_ds}/_forcemerge?max_num_segments=1&wait_for_completion=false"
    )
    fm_task = fm.get("task") if isinstance(fm, dict) else None
    if fm_task:
        from .reindex import poll_task
        poll_task(client, fm_task, on_progress=None, poll_interval=1.0)
    client.post(f"/{baseline_ds}/_refresh")
    return {"docs_sent": sent, "errors": errors}

"""Reindex baseline -> each case data stream, with task polling for progress.

Differs from scripts/03_reindex_matrix.py in two ways:
- runs reindex asynchronously (wait_for_completion=false) so we can poll
  `/_tasks/{task_id}` for `created/total` progress, then force-merge.
- progress is emitted per-case via callback.
"""
from __future__ import annotations
import time
from typing import Callable, Optional
from ..adapters.es_client import ESClient
from ..adapters.cases import CaseSpec

# (case_index, total_cases, case_name, phase, created, total) -> None
CaseProgressCB = Callable[[int, int, str, str, int, int], None]


def _start_reindex_async(client: ESClient, spec: CaseSpec, source_ds: str) -> str:
    body = {
        "source": {"index": source_ds},
        "dest":   {"index": spec.datastream, "op_type": "create"},
    }
    r = client.post("/_reindex?wait_for_completion=false&refresh=true", json=body)
    return r["task"]


def poll_task(
    client: ESClient,
    task_id: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    poll_interval: float = 0.5,
) -> dict:
    """Poll /_tasks/<task_id> until `completed=true`. Reports best-effort
    created/total (only reindex tasks expose those; force_merge reports 0)."""
    while True:
        info = client.get(f"/_tasks/{task_id}")
        status = info.get("task", {}).get("status", {}) or {}
        created = int(status.get("created", 0) or 0)
        total   = int(status.get("total", 0) or 0)
        if on_progress is not None:
            on_progress(created, total)
        if info.get("completed"):
            return info
        time.sleep(poll_interval)


def reindex_one(
    client: ESClient,
    spec: CaseSpec,
    case_index: int,
    total_cases: int,
    source_ds: str,
    progress: Optional[CaseProgressCB] = None,
    poll_interval: float = 0.5,
) -> dict:
    """Reindex a single case, then force-merge. Returns metadata dict."""
    t0 = time.time()
    if progress:
        progress(case_index, total_cases, spec.name, "reindex_start", 0, 0)
    try:
        task_id = _start_reindex_async(client, spec, source_ds)
        def _on(created: int, total: int):
            if progress:
                progress(case_index, total_cases, spec.name, "reindex", created, total)
        info = poll_task(client, task_id, _on, poll_interval=poll_interval)
        resp = info.get("response", {}) or {}
        created  = int(resp.get("created", 0) or 0)
        failures = resp.get("failures", []) or []

        if progress:
            progress(case_index, total_cases, spec.name, "forcemerge", 0, 0)
        fm = client.post(
            f"/{spec.datastream}/_forcemerge?max_num_segments=1&wait_for_completion=false"
        )
        fm_task = fm.get("task") if isinstance(fm, dict) else None
        if fm_task:
            def _fm_on(_c: int, _t: int):
                if progress:
                    progress(case_index, total_cases, spec.name, "forcemerge", 0, 0)
            poll_task(client, fm_task, _fm_on, poll_interval=max(poll_interval, 1.0))
        client.post(f"/{spec.datastream}/_refresh")

        if progress:
            progress(case_index, total_cases, spec.name, "done", created, created)
        return {
            "case": spec.name, "ok": True,
            "created": created, "wall_s": round(time.time() - t0, 2),
            "failures_sample": failures[:3], "n_failures": len(failures),
        }
    except Exception as e:
        return {"case": spec.name, "ok": False, "error": str(e)[:500]}


def reindex_all(
    client: ESClient,
    specs: list[CaseSpec],
    source_ds: str,
    progress: Optional[CaseProgressCB] = None,
    poll_interval: float = 0.5,
) -> list[dict]:
    out = []
    total = len(specs)
    for i, spec in enumerate(specs, 1):
        out.append(reindex_one(client, spec, i, total, source_ds,
                               progress=progress, poll_interval=poll_interval))
    return out

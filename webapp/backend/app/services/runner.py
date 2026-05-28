"""Orchestrate one storage-efficiency comparison run on a background thread.

Phases:
  1. generate / locate raw input file
  2. (optional) cleanup any existing data streams that would conflict
  3. setup pipelines + index templates (baseline + selected cases)
  4. bulk ingest into baseline data stream
  5. reindex baseline -> each case data stream, with force_merge
  6. measure store size + disk_usage per case
  7. persist results to SQLite, emit "done" event

Runs are serialized via a single worker thread.
"""
from __future__ import annotations
import threading
import traceback
from pathlib import Path
from typing import Optional

from ..adapters.cases import CaseSpec, baseline_ds
from ..adapters.es_client import ESClient
from ..paths import RUNS_DIR
from ..db import store
from . import (
    events, setup as setup_svc, ingest as ingest_svc, reindex as reindex_svc,
    measure as measure_svc, cleanup as cleanup_svc,
    generator as fw_gen, web_generator as web_gen, snmp_generator as snmp_gen,
)

# Datasets that ship as NDJSON (each line is a JSON doc, agent meta attached).
NDJSON_DATASETS = {"web"}
# Generators per dataset. All return (docs, message_bytes).
_GENERATORS = {
    "firewall": fw_gen.generate,
    "web":      web_gen.generate,
    "snmp":     snmp_gen.generate,
}
# Raw output filename per dataset.
_RAW_FILENAMES = {
    "firewall": "raw.log",
    "web":      "raw.ndjson",
    "snmp":     "raw.log",
}


class RunSpec:
    def __init__(
        self,
        run_id: str,
        es: ESClient,
        specs: list[CaseSpec],
        ingest_mode: str,                     # 'generated' | 'path'
        dataset: str = "firewall",            # 'firewall' | 'web'
        target_bytes: Optional[int] = None,
        seed: int = 42,
        log_path: Optional[Path] = None,
        cleanup_first: bool = True,
    ):
        self.run_id = run_id
        self.es = es
        self.specs = specs
        self.ingest_mode = ingest_mode
        self.dataset = dataset
        self.target_bytes = target_bytes
        self.seed = seed
        self.log_path = log_path
        self.cleanup_first = cleanup_first


_WORKER: Optional[threading.Thread] = None
_LOCK = threading.Lock()
_QUEUE: list[RunSpec] = []
_CURRENT: Optional[str] = None


def submit(rs: RunSpec) -> None:
    global _WORKER
    with _LOCK:
        _QUEUE.append(rs)
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="run-worker", daemon=True)
            _WORKER.start()


def current_run_id() -> Optional[str]:
    return _CURRENT


def _worker_loop() -> None:
    while True:
        with _LOCK:
            if not _QUEUE:
                return
            rs = _QUEUE.pop(0)
        _execute(rs)


def _generate_raw(rs: RunSpec, run_id: str) -> tuple[Path, int, int, bool]:
    """Returns (path, docs, message_bytes, is_ndjson)."""
    filename = _RAW_FILENAMES.get(rs.dataset, "raw.log")
    raw_path = RUNS_DIR / run_id / filename

    def _gp(written: int, target: int):
        pct = (written / target * 100) if target else 0
        events.emit(run_id, "generate_progress", written=written, target=target, pct=pct)

    target = rs.target_bytes or (10 * 1024 * 1024)
    gen = _GENERATORS.get(rs.dataset)
    if gen is None:
        raise RuntimeError(f"no generator for dataset={rs.dataset!r}")
    n_docs, n_bytes = gen(raw_path, target_bytes=target, seed=rs.seed, progress=_gp)
    return raw_path, n_docs, n_bytes, rs.dataset in NDJSON_DATASETS


def _execute(rs: RunSpec) -> None:
    global _CURRENT
    _CURRENT = rs.run_id
    run_id = rs.run_id
    try:
        store.set_status(run_id, "running")
        events.emit(run_id, "run_started", cases=[s.name for s in rs.specs],
                    dataset=rs.dataset)

        source_ds = baseline_ds(rs.dataset)

        # ---- 1. raw input ----
        if rs.ingest_mode == "generated":
            events.emit(run_id, "phase", phase="generate",
                        message=f"generating synthetic {rs.dataset} logs")
            raw_path, n_docs, n_bytes, is_ndjson = _generate_raw(rs, run_id)
        else:
            raw_path = rs.log_path
            if raw_path is None or not raw_path.exists():
                raise RuntimeError(f"log path not found: {raw_path}")
            n_bytes = raw_path.stat().st_size
            n_docs  = ingest_svc.count_lines(raw_path)
            is_ndjson = rs.dataset in NDJSON_DATASETS
            events.emit(run_id, "phase", phase="locate", message=f"using {raw_path}")

        store.update_run(run_id, raw_size_bytes=n_bytes, raw_docs=n_docs)
        events.emit(run_id, "raw_ready", path=str(raw_path), bytes=n_bytes, docs=n_docs)

        # ---- 2. cleanup (optional) ----
        if rs.cleanup_first:
            events.emit(run_id, "phase", phase="cleanup",
                        message="dropping any pre-existing data streams")
            cleanup_svc.cleanup(rs.es, rs.specs, dataset=rs.dataset,
                                drop_pipelines=False, drop_baseline=True)

        # ---- 3. setup ----
        events.emit(run_id, "phase", phase="setup",
                    message="registering pipelines + index templates")
        setup_svc.setup(rs.es, rs.specs, dataset=rs.dataset,
                        logger=lambda m: events.emit(run_id, "log", message=m))

        # ---- 4. ingest baseline ----
        events.emit(run_id, "phase", phase="ingest",
                    message=f"bulk ingesting into {source_ds}")

        def _ip(sent: int, total: int):
            pct = (sent / total * 100) if total else 0
            events.emit(run_id, "ingest_progress", sent=sent, total=total, pct=pct)

        ingest_result = ingest_svc.ingest_baseline(
            rs.es, raw_path, baseline_ds=source_ds,
            batch_size=500, progress=_ip, total_lines=n_docs, ndjson=is_ndjson,
        )
        events.emit(run_id, "ingest_done", **ingest_result)

        # ---- 5. reindex per case ----
        events.emit(run_id, "phase", phase="reindex",
                    message=f"reindex into {len(rs.specs)} cases")

        def _rp(case_index: int, total_cases: int, case_name: str,
                phase: str, created: int, total: int):
            events.emit(
                run_id, "case_progress",
                case_index=case_index, total_cases=total_cases,
                case=case_name, sub_phase=phase,
                created=created, total=total,
            )

        per_case = reindex_svc.reindex_all(rs.es, rs.specs, source_ds=source_ds,
                                           progress=_rp, poll_interval=0.5)
        events.emit(run_id, "reindex_done", results=per_case)

        # ---- 6. measure ----
        events.emit(run_id, "phase", phase="measure",
                    message="collecting store size + disk_usage")
        rows = measure_svc.measure_all(rs.es, rs.specs, raw_size_bytes=n_bytes,
                                       baseline_ds=source_ds)
        store.upsert_measurements(run_id, rows)
        events.emit(run_id, "measure_done", n_rows=len(rows))

        # ---- 7. finalize ----
        store.set_status(run_id, "done")
        events.emit(run_id, "run_done")
    except Exception as e:
        tb = traceback.format_exc()
        store.set_status(run_id, "failed", error=f"{e}\n{tb}"[:4000])
        events.emit(run_id, "run_failed", error=str(e), traceback=tb[-2000:])
    finally:
        events.mark_done(run_id)
        _CURRENT = None

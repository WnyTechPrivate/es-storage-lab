"""Tiny SQLite layer for run metadata + per-case measurements.

One connection per call so threading just works. WAL is enabled so reads from
the SSE handler don't block writes from the worker thread.
"""
from __future__ import annotations
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Iterable, Optional
from ..paths import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id              TEXT PRIMARY KEY,
  label           TEXT,
  created_at      REAL NOT NULL,
  finished_at     REAL,
  status          TEXT NOT NULL,           -- queued | running | done | failed | cancelled
  cluster_host    TEXT,
  cluster_version TEXT,
  cluster_license TEXT,
  ingest_mode     TEXT,                    -- 'generated' | 'path'
  dataset         TEXT,                    -- 'firewall' | 'web'
  raw_size_bytes  INTEGER,
  raw_docs        INTEGER,
  cases_json      TEXT,                    -- list of case names
  error           TEXT
);

CREATE TABLE IF NOT EXISTS measurements (
  run_id            TEXT NOT NULL,
  case_name         TEXT NOT NULL,
  datastream        TEXT,
  backing_index     TEXT,
  docs              INTEGER,
  raw_bytes         INTEGER,
  pri_store_bytes   INTEGER,
  ratio_pri_over_raw REAL,
  inverted_index_b  INTEGER,
  doc_values_b      INTEGER,
  stored_fields_b   INTEGER,
  points_b          INTEGER,
  norms_b           INTEGER,
  term_vectors_b    INTEGER,
  knn_vectors_b     INTEGER,
  ignored_source_b  INTEGER,
  PRIMARY KEY (run_id, case_name),
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_meas_run ON measurements(run_id);
"""


@contextmanager
def conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        # idempotent migrations for older DBs
        cols = {r["name"] for r in c.execute("PRAGMA table_info(runs)")}
        if "dataset" not in cols:
            c.execute("ALTER TABLE runs ADD COLUMN dataset TEXT")


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def create_run(
    *,
    label: Optional[str],
    cluster_host: str,
    cluster_version: Optional[str],
    cluster_license: Optional[str],
    ingest_mode: str,
    dataset: str,
    cases: list[str],
) -> str:
    run_id = new_run_id()
    with conn() as c:
        c.execute(
            """INSERT INTO runs
            (id, label, created_at, status, cluster_host, cluster_version,
             cluster_license, ingest_mode, dataset, cases_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_id, label, time.time(), "queued", cluster_host,
             cluster_version, cluster_license, ingest_mode, dataset, json.dumps(cases)),
        )
    return run_id


def update_run(run_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields.keys())
    with conn() as c:
        c.execute(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), run_id))


def set_status(run_id: str, status: str, error: Optional[str] = None) -> None:
    fields: dict = {"status": status}
    if status in ("done", "failed", "cancelled"):
        fields["finished_at"] = time.time()
    if error is not None:
        fields["error"] = error
    update_run(run_id, **fields)


def get_run(run_id: str) -> Optional[dict]:
    with conn() as c:
        row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(limit: int = 100) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT id, label, created_at, finished_at, status, cluster_host, "
            "ingest_mode, dataset, raw_size_bytes, raw_docs, cases_json "
            "FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_measurements(run_id: str, rows: Iterable[dict]) -> None:
    cols = (
        "run_id", "case_name", "datastream", "backing_index", "docs",
        "raw_bytes", "pri_store_bytes", "ratio_pri_over_raw",
        "inverted_index_b", "doc_values_b", "stored_fields_b", "points_b",
        "norms_b", "term_vectors_b", "knn_vectors_b", "ignored_source_b",
    )
    placeholders = ",".join(["?"] * len(cols))
    with conn() as c:
        for r in rows:
            if "error" in r:
                continue
            payload = (
                run_id,
                r.get("case"),
                r.get("datastream"),
                r.get("backing_index"),
                r.get("docs"),
                r.get("raw_bytes"),
                r.get("pri_store_bytes"),
                r.get("ratio_pri_over_raw"),
                r.get("inverted_index_b"),
                r.get("doc_values_b"),
                r.get("stored_fields_b"),
                r.get("points_b"),
                r.get("norms_b"),
                r.get("term_vectors_b"),
                r.get("knn_vectors_b"),
                r.get("ignored_source_b"),
            )
            c.execute(
                f"INSERT OR REPLACE INTO measurements ({','.join(cols)}) VALUES ({placeholders})",
                payload,
            )


def get_measurements(run_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM measurements WHERE run_id=? ORDER BY ratio_pri_over_raw ASC",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_run(run_id: str) -> bool:
    """Delete a run + its measurements (cascade). Returns True if a row was deleted."""
    with conn() as c:
        cur = c.execute("DELETE FROM runs WHERE id=?", (run_id,))
        return cur.rowcount > 0

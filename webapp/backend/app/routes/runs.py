"""Start / list / inspect runs."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from ..schemas import (
    StartRunRequest, StartRunResponse, RunSummary, MeasurementRow,
    ClusterCreds,
)
from ..adapters.es_client import ESClient
from ..adapters.cases import expand, CaseSpec, parse_case, namespace_of
from ..db import store
from ..services import runner, events as ev
from ..services import measure as measure_svc

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _build_specs(axes, dataset: str = "firewall") -> list[CaseSpec]:
    return expand(
        modes=axes.modes,
        sources=axes.sources,
        codecs=axes.codecs,
        parsings=axes.parsings,
        dataset=dataset,
    )


@router.post("", response_model=StartRunResponse)
def start_run(req: StartRunRequest) -> StartRunResponse:
    dataset = req.ingest.dataset
    specs = _build_specs(req.cases, dataset=dataset)
    if not specs:
        raise HTTPException(400, "no cases selected")

    client = ESClient(req.cluster.host, req.cluster.user, req.cluster.password)
    cluster_version = None
    license_type    = None
    try:
        info = client.info()
        cluster_version = (info.get("version", {}) or {}).get("number")
    except Exception as e:
        raise HTTPException(400, f"cluster unreachable: {e}")
    try:
        lic = client.license()
        license_type = (lic.get("license", {}) or {}).get("type")
    except Exception:
        pass

    run_id = store.create_run(
        label=req.label,
        cluster_host=req.cluster.host,
        cluster_version=cluster_version,
        cluster_license=license_type,
        ingest_mode=req.ingest.mode,
        dataset=dataset,
        cases=[s.name for s in specs],
    )

    if req.ingest.mode == "generated":
        rs = runner.RunSpec(
            run_id=run_id, es=client, specs=specs,
            ingest_mode="generated", dataset=dataset,
            target_bytes=req.ingest.target_bytes, seed=req.ingest.seed,
            cleanup_first=req.cleanup_first,
        )
    else:
        rs = runner.RunSpec(
            run_id=run_id, es=client, specs=specs,
            ingest_mode="path", dataset=dataset,
            log_path=Path(req.ingest.path),
            cleanup_first=req.cleanup_first,
        )

    runner.submit(rs)
    return StartRunResponse(run_id=run_id, cases=[s.name for s in specs], queued_position=0)


@router.get("", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    rows = store.list_runs()
    out = []
    for r in rows:
        out.append(RunSummary(
            id=r["id"], label=r["label"],
            created_at=r["created_at"], finished_at=r["finished_at"],
            status=r["status"], cluster_host=r["cluster_host"],
            ingest_mode=r["ingest_mode"], dataset=r.get("dataset"),
            raw_size_bytes=r["raw_size_bytes"], raw_docs=r["raw_docs"],
            cases=json.loads(r["cases_json"] or "[]"),
        ))
    return out


@router.get("/current")
def current_run():
    rid = runner.current_run_id()
    return {"run_id": rid}


@router.get("/{run_id}", response_model=RunSummary)
def get_run(run_id: str) -> RunSummary:
    r = store.get_run(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return RunSummary(
        id=r["id"], label=r["label"],
        created_at=r["created_at"], finished_at=r["finished_at"],
        status=r["status"], cluster_host=r["cluster_host"],
        ingest_mode=r["ingest_mode"], dataset=r.get("dataset"),
        raw_size_bytes=r["raw_size_bytes"], raw_docs=r["raw_docs"],
        cases=json.loads(r["cases_json"] or "[]"),
    )


@router.get("/{run_id}/measurements", response_model=list[MeasurementRow])
def get_measurements(run_id: str) -> list[MeasurementRow]:
    if not store.get_run(run_id):
        raise HTTPException(404, "run not found")
    rows = store.get_measurements(run_id)
    return [MeasurementRow(**r) for r in rows]


@router.post("/{run_id}/remeasure", response_model=list[MeasurementRow])
def remeasure_run(run_id: str, cluster: ClusterCreds) -> list[MeasurementRow]:
    """Re-run measurement against the existing data streams of a finished run.

    Does NOT reindex — assumes the data streams created by this run are still
    in the cluster. Useful when the recorded numbers diverged from reality
    (e.g. because measurement happened mid force_merge).
    """
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    if run["status"] in ("queued", "running"):
        raise HTTPException(409, "cannot re-measure while the run is still in progress")

    cases = json.loads(run["cases_json"] or "[]")
    if not cases:
        raise HTTPException(400, "this run has no recorded cases")

    dataset = run.get("dataset") or "firewall"
    ns = namespace_of(dataset)
    try:
        specs = [parse_case(c, namespace=ns) for c in cases]
    except ValueError as e:
        raise HTTPException(500, f"corrupt case names in DB: {e}")

    raw_size = int(run["raw_size_bytes"] or 0)
    client = ESClient(cluster.host, cluster.user, cluster.password)

    from ..adapters.cases import baseline_ds as _baseline_ds
    try:
        rows = measure_svc.measure_all(client, specs, raw_size_bytes=raw_size,
                                        baseline_ds=_baseline_ds(dataset))
    except RuntimeError as e:
        raise HTTPException(502, f"cluster error: {e}")

    store.upsert_measurements(run_id, rows)
    refreshed = store.get_measurements(run_id)
    return [MeasurementRow(**r) for r in refreshed]


@router.delete("/{run_id}")
def delete_run(run_id: str) -> dict:
    r = store.get_run(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    if r["status"] in ("queued", "running"):
        raise HTTPException(409, "cannot delete a run that is still queued or running")
    ok = store.delete_run(run_id)
    return {"deleted": ok}


@router.get("/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    if not store.get_run(run_id):
        raise HTTPException(404, "run not found")

    async def gen():
        cursor = 0
        ticks_since_emit = 0
        while True:
            if await request.is_disconnected():
                break
            new_events, cursor, done = ev.snapshot(run_id, cursor)
            for item in new_events:
                yield ev.sse_format(item)
            if new_events:
                ticks_since_emit = 0
            else:
                ticks_since_emit += 1
                if ticks_since_emit >= 60:   # ~15s with 250ms poll → keepalive
                    yield ":ping\n\n"
                    ticks_since_emit = 0
            if done:
                yield ev.sse_format({"kind": "_end", "t": __import__("time").time()})
                break
            await asyncio.sleep(0.25)

    return EventSourceResponse(gen())

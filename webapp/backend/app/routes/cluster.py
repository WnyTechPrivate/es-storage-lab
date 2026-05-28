"""Cluster connect / verify + data-stream maintenance."""
from __future__ import annotations
import fnmatch
from fastapi import APIRouter, HTTPException
from ..adapters.es_client import ESClient
from ..schemas import (
    ClusterCreds, ClusterTestResponse,
    DataStreamInfo, ListDatastreamsRequest,
    DeleteDatastreamsRequest, DeleteDatastreamsResponse, DeleteResultItem,
)

router = APIRouter(prefix="/api/cluster", tags=["cluster"])

# Hard-coded prefix to keep deletes scoped to this lab's naming convention.
SAFE_PREFIX = "logs-"

# Datastreams this lab creates: case names always start with mode = ldb|std,
# plus the temporary baseline. Anything else is out of scope and never shown.
FIXED_LIST_PATTERNS = (
    "logs-ldb*-*",       # all logsdb cases across every namespace
    "logs-std*-*",       # all standard cases across every namespace
    "logs-tsds*-*",      # all TSDS cases across every namespace
    "logs-baseline-*",   # baseline for every namespace
)


def _version_tuple(v: str) -> tuple[int, ...]:
    out = []
    for part in v.split("-")[0].split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


@router.post("/test", response_model=ClusterTestResponse)
def test_connection(creds: ClusterCreds) -> ClusterTestResponse:
    client = ESClient(creds.host, creds.user, creds.password, timeout=15)
    try:
        info = client.info()
    except Exception as e:
        return ClusterTestResponse(ok=False, error=str(e)[:500])

    version = (info.get("version", {}) or {}).get("number")
    lucene  = (info.get("version", {}) or {}).get("lucene_version")
    name    = info.get("name")
    cname   = info.get("cluster_name")

    license_type = None
    license_status = None
    try:
        lic = client.license()
        license_type   = (lic.get("license", {}) or {}).get("type")
        license_status = (lic.get("license", {}) or {}).get("status")
    except Exception:
        pass

    synthetic_ok = None
    if license_type:
        synthetic_ok = license_type.lower() in ("enterprise", "trial", "platinum")
    zstd_ok = None
    if version:
        zstd_ok = _version_tuple(version) >= (8, 19, 0)

    return ClusterTestResponse(
        ok=True,
        name=name,
        cluster_name=cname,
        version=version,
        lucene_version=lucene,
        license_type=license_type,
        license_status=license_status,
        synthetic_source_supported=synthetic_ok,
        zstd_codec_supported=zstd_ok,
    )


@router.post("/datastreams", response_model=list[DataStreamInfo])
def list_datastreams(req: ListDatastreamsRequest) -> list[DataStreamInfo]:
    """List data streams created by this lab (logs-ldb*, logs-std*, logs-baseline)."""
    pattern_csv = ",".join(FIXED_LIST_PATTERNS)
    client = ESClient(req.cluster.host, req.cluster.user, req.cluster.password, timeout=20)

    try:
        ds_resp = client.get(f"/_data_stream/{pattern_csv}")
    except RuntimeError as e:
        msg = str(e)
        if "404" in msg or "not_found" in msg or "index_not_found" in msg:
            return []
        raise HTTPException(502, msg[:500])

    streams = ds_resp.get("data_streams", []) or []
    if not streams:
        return []

    # Build a map of backing index -> stats via one /_cat/indices call.
    backings: list[str] = []
    for s in streams:
        for idx in s.get("indices", []) or []:
            backings.append(idx["index_name"])

    stats_by_idx: dict[str, dict] = {}
    if backings:
        try:
            rows = client.get(
                "/_cat/indices/" + ",".join(backings)
                + "?format=json&bytes=b&h=index,docs.count,pri.store.size,store.size"
            )
            for r in rows or []:
                stats_by_idx[r["index"]] = r
        except Exception:
            stats_by_idx = {}

    out: list[DataStreamInfo] = []
    for s in streams:
        name = s.get("name", "")
        if not name.startswith(SAFE_PREFIX):
            continue  # belt-and-suspenders
        idxs = s.get("indices", []) or []
        total_docs = 0
        total_bytes = 0
        for idx in idxs:
            r = stats_by_idx.get(idx["index_name"])
            if r:
                try: total_docs  += int(r.get("docs.count") or 0)
                except (TypeError, ValueError): pass
                try: total_bytes += int(r.get("pri.store.size") or 0)
                except (TypeError, ValueError): pass
        out.append(DataStreamInfo(
            name=name,
            backing_count=len(idxs),
            docs=total_docs,
            store_bytes=total_bytes,
            generation=s.get("generation"),
            template=s.get("template"),
        ))
    # Largest first — easier to spot leftovers.
    out.sort(key=lambda x: x.store_bytes, reverse=True)
    return out


@router.post("/datastreams/delete", response_model=DeleteDatastreamsResponse)
def delete_datastreams(req: DeleteDatastreamsRequest) -> DeleteDatastreamsResponse:
    """Delete the named data streams. Each name MUST start with the safe prefix."""
    client = ESClient(req.cluster.host, req.cluster.user, req.cluster.password, timeout=30)
    results: list[DeleteResultItem] = []
    for raw in req.names:
        name = (raw or "").strip()
        if not name.startswith(SAFE_PREFIX):
            results.append(DeleteResultItem(
                name=name, deleted=False,
                error=f"refused: name must start with '{SAFE_PREFIX}'",
            ))
            continue
        if "*" in name or "?" in name:
            results.append(DeleteResultItem(
                name=name, deleted=False, error="refused: wildcards not allowed in delete",
            ))
            continue
        try:
            client.delete(f"/_data_stream/{name}")
            results.append(DeleteResultItem(name=name, deleted=True))
        except RuntimeError as e:
            msg = str(e)
            if "404" in msg or "not_found" in msg:
                results.append(DeleteResultItem(name=name, deleted=False, error="not found"))
            else:
                results.append(DeleteResultItem(name=name, deleted=False, error=msg[:300]))
    return DeleteDatastreamsResponse(results=results)

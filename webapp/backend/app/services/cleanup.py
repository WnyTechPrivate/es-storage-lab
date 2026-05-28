"""Delete data streams + index templates + ingest pipelines created by a run."""
from __future__ import annotations
from typing import Iterable
from ..adapters.es_client import ESClient
from ..adapters.cases import CaseSpec, baseline_ds, baseline_template_name
from .setup import PIPELINES_BY_DATASET


def _safe(client: ESClient, method: str, path: str) -> bool:
    try:
        client.request(method, path)
        return True
    except Exception as e:
        msg = str(e)
        if "404" in msg or "not_found" in msg:
            return False
        return False


def cleanup(
    client: ESClient,
    specs: Iterable[CaseSpec],
    dataset: str = "firewall",
    drop_pipelines: bool = True,
    drop_baseline: bool = True,
) -> dict:
    deleted_ds = 0
    deleted_tpl = 0
    deleted_pipe = 0
    specs = list(specs)
    for spec in specs:
        if _safe(client, "DELETE", f"/_data_stream/{spec.datastream}"):
            deleted_ds += 1
        if _safe(client, "DELETE", f"/_index_template/{spec.template_name}"):
            deleted_tpl += 1
    if drop_baseline:
        if _safe(client, "DELETE", f"/_data_stream/{baseline_ds(dataset)}"):
            deleted_ds += 1
        if _safe(client, "DELETE", f"/_index_template/{baseline_template_name(dataset)}"):
            deleted_tpl += 1
    if drop_pipelines:
        for p in PIPELINES_BY_DATASET.get(dataset, ()):
            if _safe(client, "DELETE", f"/_ingest/pipeline/{p}"):
                deleted_pipe += 1
    return {"data_streams": deleted_ds, "templates": deleted_tpl, "pipelines": deleted_pipe}

"""Pydantic request / response models."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ClusterCreds(BaseModel):
    host: str = Field(..., examples=["https://192.168.200.71:9200"])
    user: str = Field(..., examples=["elastic"])
    password: str


class ClusterTestResponse(BaseModel):
    ok: bool
    error: Optional[str] = None
    name: Optional[str] = None
    cluster_name: Optional[str] = None
    version: Optional[str] = None
    lucene_version: Optional[str] = None
    license_type: Optional[str] = None
    license_status: Optional[str] = None
    synthetic_source_supported: Optional[bool] = None
    zstd_codec_supported: Optional[bool] = None


class DataStreamInfo(BaseModel):
    name: str
    backing_count: int
    docs: int
    store_bytes: int
    generation: Optional[int] = None
    template: Optional[str] = None


class ListDatastreamsRequest(BaseModel):
    cluster: ClusterCreds


class DeleteDatastreamsRequest(BaseModel):
    cluster: ClusterCreds
    names: list[str] = Field(..., min_length=1, max_length=500)


class DeleteResultItem(BaseModel):
    name: str
    deleted: bool
    error: Optional[str] = None


class DeleteDatastreamsResponse(BaseModel):
    results: list[DeleteResultItem]


class IngestGenerated(BaseModel):
    mode: Literal["generated"] = "generated"
    dataset: Literal["firewall", "web", "snmp"] = "firewall"
    target_bytes: int = Field(..., ge=1024)
    seed: int = 42


class IngestPath(BaseModel):
    mode: Literal["path"] = "path"
    dataset: Literal["firewall", "web", "snmp"] = "firewall"
    path: str


class CaseAxes(BaseModel):
    """4 axes — modes / sources / codecs / parsings → 24 cases when all on.
    event.original.index / .doc_values are pinned to false (ECS default),
    so the previous `scenarios` axis is gone."""
    modes:    list[Literal["std", "ldb", "tsds"]] = ["std", "ldb", "tsds"]
    sources:  list[Literal["str", "syn"]] = ["str", "syn"]
    codecs:   list[Literal["lz4", "zstd"]] = ["lz4", "zstd"]
    parsings: list[Literal["p1", "p2", "p3"]] = ["p1", "p2", "p3"]


class StartRunRequest(BaseModel):
    label: Optional[str] = None
    cluster: ClusterCreds
    ingest: IngestGenerated | IngestPath
    cases: CaseAxes = CaseAxes()
    cleanup_first: bool = True


class StartRunResponse(BaseModel):
    run_id: str
    cases: list[str]
    queued_position: int


class RunSummary(BaseModel):
    id: str
    label: Optional[str]
    created_at: float
    finished_at: Optional[float]
    status: str
    cluster_host: Optional[str]
    ingest_mode: Optional[str]
    dataset: Optional[str]
    raw_size_bytes: Optional[int]
    raw_docs: Optional[int]
    cases: list[str]


class MeasurementRow(BaseModel):
    case_name: str
    datastream: Optional[str]
    backing_index: Optional[str]
    docs: Optional[int]
    raw_bytes: Optional[int]
    pri_store_bytes: Optional[int]
    ratio_pri_over_raw: Optional[float]
    inverted_index_b: Optional[int]
    doc_values_b: Optional[int]
    stored_fields_b: Optional[int]
    points_b: Optional[int]
    norms_b: Optional[int]
    term_vectors_b: Optional[int]
    knn_vectors_b: Optional[int]
    ignored_source_b: Optional[int]

"""Register ingest pipelines + index templates for one run.

Equivalent to scripts/01_setup_pipelines_and_templates.py, but parameterized
to (a) the set of CaseSpec objects the user actually selected and (b) the
dataset (firewall vs web), which picks the right pipeline triplet."""
from __future__ import annotations
import json
from typing import Iterable, Callable, Optional
from ..adapters.es_client import ESClient
from ..adapters.cases import CaseSpec
from ..adapters.templates import build_template, build_baseline_template
from ..paths import PIPELINE_DIR

PIPELINES_BY_DATASET = {
    "firewall": ("raw_ingest",         "parsing2_full",         "parsing3_parsed_only"),
    "web":      ("raw_ingest_service", "parsing2_full_service", "parsing3_parsed_only_service"),
    "snmp":     ("raw_ingest_snmp",    "parsing2_full_snmp",    "parsing3_parsed_only_snmp"),
}

Logger = Optional[Callable[[str], None]]


def _log(logger: Logger, msg: str) -> None:
    if logger:
        logger(msg)


def check_ecs_mappings(client: ESClient, logger: Logger = None) -> None:
    """Fail fast if the ecs@mappings component template is missing.

    M2 case templates compose_of this one, so without it index creation
    blows up with a confusing 'component template not found' error.
    """
    try:
        client.get("/_component_template/ecs@mappings")
        _log(logger, "ecs@mappings: present")
    except RuntimeError as e:
        msg = str(e)
        if "404" in msg or "not_found" in msg:
            raise RuntimeError(
                "ecs@mappings component template 이 클러스터에 없습니다. "
                "이 매트릭스는 ES 8.x+ 의 stack templates 가 활성화된 상태를 가정합니다. "
                "Stack Monitoring / Fleet 셋업을 한 번 진행해 ECS 매핑을 등록해 주세요."
            ) from e
        raise


def register_pipelines(client: ESClient, dataset: str = "firewall",
                       logger: Logger = None) -> None:
    names = PIPELINES_BY_DATASET.get(dataset)
    if not names:
        raise ValueError(f"unknown dataset for pipelines: {dataset!r}")
    for name in names:
        body = json.loads((PIPELINE_DIR / f"{name}.json").read_text(encoding="utf-8"))
        client.put(f"/_ingest/pipeline/{name}", json=body)
        _log(logger, f"pipeline {name}: OK")


def register_templates(client: ESClient, specs: Iterable[CaseSpec],
                       dataset: str = "firewall",
                       logger: Logger = None) -> tuple[int, int]:
    specs = list(specs)
    templates = [build_baseline_template(dataset)] + [build_template(s, dataset=dataset) for s in specs]
    ok = fail = 0
    for t in templates:
        try:
            client.put(f"/_index_template/{t['name']}", json=t["body"])
            ok += 1
        except Exception as e:
            fail += 1
            _log(logger, f"FAIL template {t['name']}: {str(e)[:200]}")
    _log(logger, f"templates: ok={ok} fail={fail} (incl. baseline)")
    return ok, fail


def setup(client: ESClient, specs: Iterable[CaseSpec], dataset: str = "firewall",
          logger: Logger = None) -> None:
    _log(logger, "checking ecs@mappings...")
    check_ecs_mappings(client, logger=logger)
    _log(logger, f"registering pipelines (dataset={dataset})...")
    register_pipelines(client, dataset=dataset, logger=logger)
    _log(logger, f"registering index templates (dataset={dataset})...")
    register_templates(client, specs, dataset=dataset, logger=logger)

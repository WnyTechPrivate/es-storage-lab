"""Case-name + datastream-name helpers.

Naming:
    case        = "{mode}.{src}.{codec}.{idx}.{dv}.{parsing}"
    datastream  = "logs-{case}-{namespace}"        ← namespace varies by dataset

M2.1 matrix (24 cases — event.original.index/doc_values pinned to false):
    mode    ∈ {std, ldb}
    src     ∈ {str, syn}
    codec   ∈ {lz4, zstd}
    parsing ∈ {p1, p2, p3}
    idx     = "if"   (always)
    dv      = "df"   (always)

Datasets:
    firewall → namespace "default"   (Fortinet traffic, original)
    web      → namespace "service"   (access / req / error mixed)
"""
from __future__ import annotations
from typing import Iterable, NamedTuple, Literal

MODES    = ("std", "ldb", "tsds")
SOURCES  = ("str", "syn")
CODECS   = ("lz4", "zstd")
IDX_OPTS = ("it", "if")
DV_OPTS  = ("dt", "df")
PARSINGS = ("p1", "p2", "p3")

DATASET_PREFIX = "logs-"

Dataset = Literal["firewall", "web", "snmp"]

# dataset → namespace (also used as the data-stream suffix)
DATASET_NAMESPACE: dict[str, str] = {
    "firewall": "default",
    "web":      "service",
    "snmp":     "snmp",
}


def namespace_of(dataset: str) -> str:
    if dataset not in DATASET_NAMESPACE:
        raise ValueError(f"unknown dataset: {dataset!r}")
    return DATASET_NAMESPACE[dataset]


def baseline_ds(dataset: str) -> str:
    return f"{DATASET_PREFIX}baseline-{namespace_of(dataset)}"


def baseline_template_name(dataset: str) -> str:
    """One baseline template per namespace; same logical role."""
    return f"tpl-baseline-{namespace_of(dataset)}"


class CaseSpec(NamedTuple):
    mode: str        # std | ldb
    src:  str        # str | syn
    codec: str       # lz4 | zstd
    idx:  str        # it | if
    dv:   str        # dt | df
    parsing: str     # p1 | p2 | p3
    namespace: str = "default"

    @property
    def name(self) -> str:
        return f"{self.mode}.{self.src}.{self.codec}.{self.idx}.{self.dv}.{self.parsing}"

    @property
    def datastream(self) -> str:
        return f"{DATASET_PREFIX}{self.name}-{self.namespace}"

    @property
    def template_name(self) -> str:
        # template names are namespace-scoped so two datasets can coexist
        return f"tpl-{self.name}-{self.namespace}"


def case_name(mode, src, codec, idx, dv, parsing) -> str:
    return f"{mode}.{src}.{codec}.{idx}.{dv}.{parsing}"


def datastream_of(case: str, namespace: str = "default") -> str:
    return f"{DATASET_PREFIX}{case}-{namespace}"


def parse_case(name: str, namespace: str = "default") -> CaseSpec:
    parts = name.split(".")
    if len(parts) != 6:
        raise ValueError(f"invalid case name: {name!r}")
    return CaseSpec(*parts, namespace=namespace)


def basic(dataset: str = "firewall") -> list[CaseSpec]:
    """Default matrix per dataset.

    With MODES=(std, ldb, tsds), SOURCES=(str, syn), CODECS=(lz4, zstd),
    PARSINGS=(p1, p2, p3) → 3 * 2 * 2 * 3 = 36 cases.
    """
    return expand(MODES, SOURCES, CODECS, PARSINGS, dataset=dataset)


# Backwards-compatible alias for callers that still import the old name.
basic_24 = basic


def expand(
    modes: Iterable[str] = MODES,
    sources: Iterable[str] = SOURCES,
    codecs: Iterable[str] = CODECS,
    parsings: Iterable[str] = PARSINGS,
    dataset: str = "firewall",
) -> list[CaseSpec]:
    ns = namespace_of(dataset)
    out: list[CaseSpec] = []
    for m in modes:
        for s in sources:
            for c in codecs:
                for p in parsings:
                    out.append(CaseSpec(m, s, c, "if", "df", p, namespace=ns))
    return out


# --- Legacy single-namespace constants (kept for callers that still hardcode) ---
BASELINE_DS = baseline_ds("firewall")    # logs-baseline-default

"""Common config + ES client factory."""
import os
import urllib3
import requests
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ES_HOST = os.environ.get("ES_HOST", "https://192.168.200.71:9200")
ES_USER = os.environ.get("ES_USER", "elastic")
ES_PASS = os.environ.get("ES_PASS", "")
VERIFY  = False
TIMEOUT = 120

ROOT       = Path(__file__).resolve().parent.parent
DATA_DIR   = ROOT / "data"
PIPE_DIR   = ROOT / "pipelines"
TPL_DIR    = ROOT / "templates"
RESULT_DIR = ROOT / "results"

DATASET_PREFIX = "logs-"
NAMESPACE      = "default"
BASELINE_TAG   = "baseline"

PARSINGS = ("p1", "p2", "p3")
MODES    = ("std", "ldb")
SOURCES  = ("str", "syn")
CODECS   = ("lz4", "zstd")
IDX_OPTS = ("it", "if")
DV_OPTS  = ("dt", "df")


def case_name(mode, src, codec, idx, dv, parsing):
    return f"{mode}.{src}.{codec}.{idx}.{dv}.{parsing}"


def datastream_of(case):
    return f"{DATASET_PREFIX}{case}-{NAMESPACE}"


def all_cases():
    out = []
    for m in MODES:
        for s in SOURCES:
            for c in CODECS:
                for i in IDX_OPTS:
                    for d in DV_OPTS:
                        for p in PARSINGS:
                            out.append(case_name(m, s, c, i, d, p))
    return out


def session():
    s = requests.Session()
    s.auth = (ES_USER, ES_PASS)
    s.verify = VERIFY
    s.headers.update({"Content-Type": "application/json"})
    return s


def es(method, path, **kw):
    url = f"{ES_HOST}{path}"
    r = session().request(method, url, timeout=TIMEOUT, **kw)
    if not r.ok:
        raise RuntimeError(f"{method} {path} -> {r.status_code}\n{r.text}")
    if r.content:
        try:
            return r.json()
        except Exception:
            return r.text
    return None

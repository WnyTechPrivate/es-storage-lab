"""Common path resolution for the webapp backend.

Resolves repo root (the `R&D/` folder) regardless of where uvicorn is launched,
and exposes pre-existing subfolders used by the original scripts.
"""
from pathlib import Path

# webapp/backend/app/paths.py -> webapp/backend/app -> webapp/backend -> webapp -> R&D
REPO_ROOT = Path(__file__).resolve().parents[3]

DATA_DIR     = REPO_ROOT / "data"
PIPELINE_DIR = REPO_ROOT / "pipelines"
TEMPLATE_DIR = REPO_ROOT / "templates"
RESULT_DIR   = REPO_ROOT / "results"
SCRIPTS_DIR  = REPO_ROOT / "scripts"

WEBAPP_DIR     = REPO_ROOT / "webapp"
BACKEND_DIR    = WEBAPP_DIR / "backend"
RUNS_DIR       = BACKEND_DIR / "runs"
DB_PATH        = BACKEND_DIR / "app" / "db" / "store.sqlite"

for p in (DATA_DIR, RESULT_DIR, RUNS_DIR, DB_PATH.parent):
    p.mkdir(parents=True, exist_ok=True)

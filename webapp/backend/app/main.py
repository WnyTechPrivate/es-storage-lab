"""FastAPI entrypoint for the ES storage-efficiency comparison UI."""
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .db import store
from .routes import cluster as cluster_routes, runs as runs_routes
from .paths import WEBAPP_DIR

FRONTEND_DIST = WEBAPP_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    yield


app = FastAPI(title="ES Storage Efficiency UI", version="0.1.0", lifespan=lifespan)

# CORS for vite dev (npm run dev on :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cluster_routes.router)
app.include_router(runs_routes.router)


@app.get("/api/health")
def health():
    return {"ok": True}


# In production, serve the built React app at /. (Index fallback for SPA routes.)
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")

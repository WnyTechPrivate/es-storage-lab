"""Per-run event log for SSE.

Worker threads only append to an in-memory list under a Lock; the SSE handler
polls that list with a per-connection cursor. This avoids the cross-thread
asyncio.Queue wakeup problem (the event loop and the worker live in different
threads, so put_nowait() doesn't reliably wake awaiting consumers).
"""
from __future__ import annotations
import json
import threading
import time
from collections import defaultdict, deque
from typing import Any

_LOCK = threading.Lock()
_HISTORY: dict[str, deque] = defaultdict(lambda: deque(maxlen=4000))
_DONE: set[str] = set()


def emit(run_id: str, kind: str, **payload: Any) -> None:
    """Called from the worker thread to append a new event."""
    ev = {"t": time.time(), "kind": kind, **payload}
    with _LOCK:
        _HISTORY[run_id].append(ev)


def mark_done(run_id: str) -> None:
    with _LOCK:
        _DONE.add(run_id)


def is_done(run_id: str) -> bool:
    with _LOCK:
        return run_id in _DONE


def snapshot(run_id: str, cursor: int) -> tuple[list[dict], int, bool]:
    """Return (new events since cursor, new cursor, done flag)."""
    with _LOCK:
        hist = list(_HISTORY[run_id])
        done = run_id in _DONE
    new = hist[cursor:]
    return new, len(hist), done


def sse_format(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

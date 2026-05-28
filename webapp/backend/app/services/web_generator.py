"""Synthetic web log generator — access / req / error mixed.

`target_bytes` measures the **message-only** size (i.e. what nginx writes to
its access.log on disk), NOT the NDJSON file size — so that a user-specified
"10 MB" matches the firewall dataset semantically. Agent meta (host / agent
/ log / ecs / data_stream) is added on top per doc.

Mix ratio (fixed): access 70%, req 25%, error 5%.
"""
from __future__ import annotations
import random
import datetime as dt
import json
from pathlib import Path
from typing import Callable, Optional, Iterable

MIX_ACCESS  = 0.70
MIX_REQUEST = 0.25
MIX_ERROR   = 0.05

PATHS_PUBLIC = ["/", "/product/2", "/product/15", "/cart", "/checkout",
                "/category/electronics", "/category/home", "/account", "/orders"]
PATHS_API    = ["/api/_search", "/api/cart", "/api/checkout", "/api/user/me",
                "/api/orders", "/api/product"]
KEYWORDS     = ["keyboard", "monitor", "mouse", "headphone", "cable", "battery",
                "speaker", "router", "laptop", "ssd"]
QUERIES      = ["product", "category:electronics", "category:home", "promo:2026",
                "free-shipping", "deal", "review:5stars"]
COUNTRIES    = ["KR", "JP", "US", "TW", "VN", "DE", "FR", "GB", "SG"]
CITIES       = ["Seoul", "Busan", "Incheon", "Daegu", "Tokyo", "Osaka",
                "Los Angeles", "New York", "Taipei", "Hanoi", "Berlin"]
DEVICES      = ["desktop", "mobile", "tablet"]
OSES         = ["Windows", "macOS", "iOS", "Android", "Linux"]
BROWSERS     = ["Chrome", "Safari", "Edge", "Firefox", "Opera"]
AUTH_METHODS = ["session", "oauth", "jwt", "sso"]
ERROR_TYPES  = ["api_timeout", "db_failure", "auth_expired", "rate_limited",
                "upstream_5xx", "validation"]
ERROR_CATS   = ["payment", "checkout", "search", "auth", "infra", "third_party"]
USER_AGENTS  = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]
REFERERS = [
    "https://shopping-demo.wnytech.co.kr/",
    "https://shopping-demo.wnytech.co.kr/category/electronics",
    "https://shopping-demo.wnytech.co.kr/product/2",
    "https://www.google.com/",
]


def _ip(rnd: random.Random) -> str:
    # Mostly Korean IP-like ranges, plus some random
    if rnd.random() < 0.7:
        return f"{rnd.choice([121, 211, 175, 218])}.{rnd.randint(100, 250)}.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}"
    return f"{rnd.randint(1, 223)}.{rnd.randint(0, 255)}.{rnd.randint(0, 255)}.{rnd.randint(1, 254)}"


def _username(rnd: random.Random, uid: int) -> str:
    surnames = ["kim", "lee", "park", "choi", "jung", "kang", "yoon", "han", "shin"]
    given    = ["jiwon", "minjun", "seoyeon", "haeun", "jihu", "doyun", "sieun", "rina", "jisoo"]
    return f"{rnd.choice(surnames)}.{rnd.choice(given)}"


def _ts(now: dt.datetime) -> str:
    """[06/May/2026:08:05:51 +0000]"""
    return now.strftime("%d/%b/%Y:%H:%M:%S +0000")


def _kv_pairs(pairs: list[tuple[str, str]]) -> str:
    return " ".join(f"{k}={v}" for k, v in pairs)


def _access_line(rnd: random.Random, now: dt.datetime, uid: int) -> str:
    ip = _ip(rnd)
    path = rnd.choice(PATHS_PUBLIC)
    status = 200 if rnd.random() < 0.96 else rnd.choice([301, 304, 404])
    kv = [
        ("user.id",          f"u{uid:05d}"),
        ("user.name",        _username(rnd, uid)),
        ("src.ip",           ip),
        ("src.geo.country",  rnd.choice(COUNTRIES)),
        ("src.geo.city",     rnd.choice(CITIES)),
        ("device.type",      rnd.choice(DEVICES)),
        ("os.name",          rnd.choice(OSES)),
        ("browser.name",     rnd.choice(BROWSERS)),
        ("auth.method",      rnd.choice(AUTH_METHODS)),
        ("service",          "home-shopping"),
    ]
    return f"{ip} - - [{_ts(now)}] Access \"GET {path} HTTP/1.1\" {status} {_kv_pairs(kv)}"


def _request_line(rnd: random.Random, now: dt.datetime) -> str:
    ip = _ip(rnd)
    path = rnd.choice(PATHS_API)
    status = 200 if rnd.random() < 0.97 else rnd.choice([400, 401, 403])
    method = rnd.choice(["POST", "GET", "PUT"])
    # build optional kv for typical search/request
    extra: list[tuple[str, str]] = []
    if "_search" in path:
        extra.append(("query", rnd.choice(QUERIES)))
        if rnd.random() < 0.5:
            extra.append(("keyword", rnd.choice(KEYWORDS)))
    extra.append(("service", "home-shopping"))
    return f"{ip} - - [{_ts(now)}] Req \"{method} {path} HTTP/1.1\" {status} {_kv_pairs(extra)}"


def _error_line(rnd: random.Random, now: dt.datetime) -> str:
    ip = _ip(rnd)
    path = rnd.choice(PATHS_API)
    status = rnd.choice([500, 502, 503, 504])
    bytes_ = rnd.randint(40, 1024)
    referer = rnd.choice(REFERERS)
    ua = rnd.choice(USER_AGENTS)
    method = rnd.choice(["POST", "GET", "PUT"])
    rt = round(rnd.uniform(0.5, 30.0), 6)
    upstream = f"192.168.0.{rnd.randint(10, 200)}:{rnd.choice([5000, 8080, 9000, 3000])}"
    kv = [
        ("rt",              f"{rt}"),
        ("upstream_addr",   upstream),
        ("service",         "home-shopping"),
        ("trace.id",        f"{rnd.getrandbits(128):032x}"),
        ("transaction.id",  f"{rnd.getrandbits(64):016x}"),
        ("issue_type",      rnd.choice(ERROR_TYPES)),
        ("error_category",  rnd.choice(ERROR_CATS)),
    ]
    return (
        f"{ip} - - [{_ts(now)}] Error \"{method} {path} HTTP/1.1\" {status} {bytes_} "
        f"\"{referer}\" \"{ua}\" {_kv_pairs(kv)}"
    )


def _pick(rnd: random.Random, now: dt.datetime, uid: int) -> str:
    r = rnd.random()
    if r < MIX_ACCESS:                          return _access_line(rnd, now, uid)
    if r < MIX_ACCESS + MIX_REQUEST:            return _request_line(rnd, now)
    return _error_line(rnd, now)


def _agent_meta(rnd: random.Random, host_idx: int) -> dict:
    return {
        "agent": {
            "id":      "76c0e5b0-1a2b-4c3d-9e8f-0a1b2c3d4e5f",
            "name":    f"agent-svc-{host_idx:02d}",
            "type":    "elastic-agent",
            "version": "8.17.0",
        },
        "host": {
            "name":         f"web-{host_idx:02d}.shopping-demo.local",
            "hostname":     f"web-{host_idx:02d}",
            "architecture": "x86_64",
            "ip":           [f"10.10.20.{10 + host_idx}", "fe80::1"],
            "os": {
                "platform": "linux",
                "name":     "Ubuntu",
                "version":  "22.04.4 LTS",
                "kernel":   "6.5.0-generic",
                "type":     "linux",
                "family":   "debian",
            },
        },
        "log": {
            "file":   {"path": "/var/log/nginx/access.log"},
            "offset": rnd.randint(0, 10_000_000),
        },
        "ecs":          {"version": "8.11.0"},
        "data_stream":  {"type": "logs", "dataset": "web.access", "namespace": "service"},
    }


ProgressCB = Callable[[int, int], None]   # (msg_bytes_written, target_bytes)


def generate_bulk(
    target_bytes: int,
    seed: int = 42,
    start: Optional[dt.datetime] = None,
    progress: Optional[ProgressCB] = None,
) -> Iterable[dict]:
    """Yield bulk-ready doc dicts: {message, agent, host, log, ecs, data_stream}.

    Stops when accumulated **message bytes** reach `target_bytes`.
    """
    rnd = random.Random(seed)
    if start is None:
        # Anchor near "now" so TSDS look_back_time accepts these docs.
        start = dt.datetime.utcnow() - dt.timedelta(hours=2)
    msg_written = 0
    n = 0
    next_emit = 50_000
    while msg_written < target_bytes:
        host_idx = 1 + (n % 4)
        uid      = 10000 + (n % 5000)
        now      = start + dt.timedelta(seconds=n * 0.05)
        line     = _pick(rnd, now, uid)
        doc      = _agent_meta(rnd, host_idx)
        doc["message"]    = line
        doc["@timestamp"] = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        msg_written += len(line.encode("utf-8")) + 1   # +1 for the implicit newline
        n += 1
        yield doc
        if progress and msg_written >= next_emit:
            progress(msg_written, target_bytes)
            next_emit = msg_written + 50_000
    if progress:
        progress(msg_written, target_bytes)


def generate(
    out_path: Path,
    target_bytes: int,
    seed: int = 42,
    start: Optional[dt.datetime] = None,
    progress: Optional[ProgressCB] = None,
) -> tuple[int, int]:
    """Returns (docs, message_bytes). `message_bytes` is what the runner stores
    as `raw_size_bytes` so it stays comparable to firewall."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    msg_bytes = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for doc in generate_bulk(target_bytes, seed=seed, start=start, progress=progress):
            line = json.dumps(doc, ensure_ascii=False) + "\n"
            f.write(line)
            msg_bytes += len(doc["message"].encode("utf-8")) + 1
            n += 1
    return n, msg_bytes

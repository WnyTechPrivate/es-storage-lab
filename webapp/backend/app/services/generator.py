"""Synthetic Fortinet traffic log generator.

Reuses the format from scripts/generate_data.py but parameterized: target_bytes
(or target_docs), seed, output path. Yields progress via a callback so the
backend can stream % completion to the UI.
"""
from __future__ import annotations
import random
import datetime as dt
from pathlib import Path
from typing import Callable, Optional

INT_PREFIXES = ["10.10.", "10.20.", "172.18.", "192.168."]
SERVICES = [
    ("HTTPS", 443, "tcp", 6),
    ("HTTP",  80,  "tcp", 6),
    ("RDP",   3389,"tcp", 6),
    ("SSH",   22,  "tcp", 6),
    ("DNS",   53,  "udp", 17),
    ("SMTP",  25,  "tcp", 6),
    ("FTP",   21,  "tcp", 6),
    ("MYSQL", 3306,"tcp", 6),
    ("LDAP",  389, "tcp", 6),
    ("NTP",   123, "udp", 17),
]
SUBTYPES   = ["forward", "local", "multicast"]
ACTIONS    = ["accept", "deny", "close", "timeout"]
APPCATS    = ["unscanned", "Web.Client", "Network.Service", "Remote.Access", "Email"]
LEVELS     = ["notice", "warning", "information"]
DEVNAMES   = ["WNYT-FW-A", "WNYT-FW-B", "WNYT-FW-DMZ"]
DEVIDS     = ["FG180FTK23902182", "FG200FTK21501100", "FG100FTK22301400"]
HOSTIPS    = ["10.10.200.103", "10.10.200.104", "10.10.200.105"]


def _internal_ip(rnd: random.Random) -> str:
    return rnd.choice(INT_PREFIXES) + f"{rnd.randint(1,254)}.{rnd.randint(1,254)}"


def _external_ip(rnd: random.Random) -> str:
    return f"{rnd.randint(1,223)}.{rnd.randint(0,255)}.{rnd.randint(0,255)}.{rnd.randint(1,254)}"


def _make_line(rnd: random.Random, now: dt.datetime) -> str:
    direction = rnd.choice(["in", "out"])
    if direction == "in":
        srcip = _external_ip(rnd); dstip = _internal_ip(rnd)
        srcintf = "wan1"; dstintf = rnd.choice(["internal", "dmz"])
    else:
        srcip = _internal_ip(rnd); dstip = _external_ip(rnd)
        srcintf = rnd.choice(["internal", "dmz"]); dstintf = "wan1"
    svc, port, _, ianano = rnd.choice(SERVICES)
    srcport = rnd.randint(1024, 65535)
    dstport = port if rnd.random() < 0.7 else rnd.randint(1024, 65535)
    devname = rnd.choice(DEVNAMES); devid = rnd.choice(DEVIDS); hostip = rnd.choice(HOSTIPS)
    eventtime_ns = int(now.timestamp() * 1_000_000_000) + rnd.randint(0, 999_999)
    sessionid = rnd.randint(1_000_000_000, 9_999_999_999)
    policyid  = rnd.randint(1, 300)
    duration  = rnd.randint(0, 3600)
    sentpkt   = rnd.randint(1, 5000)
    rcvdpkt   = rnd.randint(1, 5000)
    sentbyte  = sentpkt * rnd.randint(40, 1500)
    rcvdbyte  = rcvdpkt * rnd.randint(40, 1500)
    action    = rnd.choice(ACTIONS)
    subtype   = rnd.choice(SUBTYPES)
    level     = rnd.choice(LEVELS)
    appcat    = rnd.choice(APPCATS)
    date_s = now.strftime("%Y-%m-%d")
    time_s = now.strftime("%H:%M:%S")
    mon_s  = now.strftime("%b %d %H:%M:%S")
    kv = (
        f"date={date_s} time={time_s} "
        f"devname={devname} devid={devid} "
        f"eventtime={eventtime_ns} tz=+0900 "
        f"logid=0000000013 type=traffic subtype={subtype} level={level} vd=root "
        f"srcip={srcip} srcport={srcport} srcintf={srcintf} srcintfrole=undefined "
        f"dstip={dstip} dstport={dstport} dstintf={dstintf} dstintfrole=undefined "
        f"srccountry=- dstcountry=- "
        f"sessionid={sessionid} proto={ianano} action={action} "
        f"policyid={policyid} policytype=policy service={svc} trandisp=noop "
        f"duration={duration} sentbyte={sentbyte} rcvdbyte={rcvdbyte} "
        f"sentpkt={sentpkt} rcvdpkt={rcvdpkt} appcat={appcat}"
    )
    return f"{date_s} {time_s} {mon_s} {hostip} {kv}\n"


ProgressCB = Callable[[int, int], None]  # (bytes_written, target_bytes)


def generate(
    out_path: Path,
    target_bytes: int,
    seed: int = 42,
    start: Optional[dt.datetime] = None,
    progress: Optional[ProgressCB] = None,
    progress_every: int = 50_000,
) -> tuple[int, int]:
    """Generate a Fortinet-flavored syslog file of ~target_bytes.

    Returns (docs_written, bytes_written).
    """
    rnd = random.Random(seed)
    if start is None:
        # Anchor near "now" so TSDS look_back_time accepts these docs.
        start = dt.datetime.utcnow() - dt.timedelta(hours=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    n = 0
    last_emit = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        while written < target_bytes:
            now = start + dt.timedelta(seconds=n * 0.1)
            line = _make_line(rnd, now)
            f.write(line)
            written += len(line.encode("utf-8"))
            n += 1
            if progress and (written - last_emit) >= progress_every:
                progress(written, target_bytes)
                last_emit = written
    if progress:
        progress(written, target_bytes)
    return n, written

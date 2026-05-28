"""SNMP positional log generator.

Each line is a pipe-separated, all-numeric record:

    timestamp_ms | device_id | vendor_code | device_type_code | dataset_code
        | interface_index | metric_code | metric_value | interval_sec
        | admin_status | oper_status | severity_code

Dataset code (110/120/130/210) controls which metric_codes are emitted and
which positional values are meaningful. Counter-style metrics
(ifHCInOctets/Out, ifInErrors/Out) carry per-(device, interface) cumulative
state so subsequent samples grow monotonically.

Plain text output (one line = one record) — same shape as the firewall
generator. No agent / host / log / ecs / data_stream meta attached.
`target_bytes` counts message bytes accumulated.
"""
from __future__ import annotations
import random
import datetime as dt
from pathlib import Path
from typing import Callable, Optional, Iterable

# --- topology -----------------------------------------------------------

DEVICES = [
    # (device_id, vendor_code, device_type_code, interface_count)
    (101001, 1, 1, 24),   # Cisco switch
    (101002, 1, 1, 24),   # Cisco switch
    (101003, 1, 1, 48),   # Cisco switch (more ports)
    (101004, 5, 1, 24),   # Arista switch
    (102001, 1, 2, 8),    # Cisco router
    (102002, 2, 2, 8),    # Juniper router
    (103001, 3, 3, 12),   # Fortinet firewall
]

# --- code book (matches the user's spec) --------------------------------

DS_INTERFACE  = 110
DS_SYSTEM     = 120
DS_ENV        = 130
DS_TRAP       = 210

IF_METRICS  = (10001, 10002, 10003, 10004)        # ifHCInOctets/Out, ifInErrors/Out
SYS_METRICS = (20001, 20002, 20003)               # cpu(x100), mem_used, mem_total
ENV_METRICS = (30001, 30002, 30003)               # temp(x100), fan rpm, power status
TRAP_CODES  = (40001, 40002, 40003)               # linkDown, linkUp, coldStart


# --- per-(device, interface, metric) cumulative state -------------------

def _new_state(rnd: random.Random, dev_id: int, ifcount: int) -> dict:
    """Initialize cumulative counters for this device + its interfaces."""
    return {
        "if": {
            i: {
                10001: rnd.randint(1_000_000_000, 200_000_000_000),  # in octets
                10002: rnd.randint(1_000_000_000, 200_000_000_000),  # out octets
                10003: rnd.randint(0, 500),                          # in errors
                10004: rnd.randint(0, 500),                          # out errors
                "admin": 1,
                "oper":  1 if rnd.random() < 0.97 else 2,
                "rate_in":  rnd.randint(10_000, 8_000_000),   # bytes/sec target
                "rate_out": rnd.randint(10_000, 8_000_000),
                "err_rate": rnd.random() < 0.10,              # 10% of interfaces are flaky
            }
            for i in range(1, ifcount + 1)
        },
        "sys": {
            "cpu":  rnd.randint(1500, 7500),                  # x100 pct, normal range
            "mem_used": rnd.randint(1 << 30, 6 << 30),        # 1-6 GB
            "mem_total": 8 << 30,                             # 8 GB fixed
        },
        "env": {
            "temp_x100": rnd.randint(5000, 7000),             # 50-70 C
            "fan_rpm":   rnd.randint(6000, 11000),
            "power":     1,
        },
        "active_outages": [],  # list[(if_index, ticks_remaining)]
    }


def _step_interface_counters(rnd: random.Random, st: dict, interval_sec: int) -> None:
    """Advance octet/error counters one polling tick."""
    for i, ifs in st["if"].items():
        if ifs["oper"] == 1:
            ifs[10001] += ifs["rate_in"]  * interval_sec + rnd.randint(-50_000, 50_000)
            ifs[10002] += ifs["rate_out"] * interval_sec + rnd.randint(-50_000, 50_000)
            if ifs["err_rate"]:
                ifs[10003] += rnd.randint(0, 8)
                ifs[10004] += rnd.randint(0, 3)
            else:
                if rnd.random() < 0.05: ifs[10003] += 1
                if rnd.random() < 0.05: ifs[10004] += 1


def _step_system(rnd: random.Random, st: dict) -> None:
    cur = st["sys"]
    cur["cpu"]      = max(500, min(9800, cur["cpu"]      + rnd.randint(-800, 800)))
    cur["mem_used"] = max(1 << 30, min(cur["mem_total"] - (1 << 29),
                                       cur["mem_used"] + rnd.randint(-(1 << 28), 1 << 28)))


def _step_env(rnd: random.Random, st: dict) -> None:
    cur = st["env"]
    cur["temp_x100"] = max(4500, min(8500, cur["temp_x100"] + rnd.randint(-200, 200)))
    cur["fan_rpm"]   = max(4000, min(12000, cur["fan_rpm"]  + rnd.randint(-400, 400)))


# --- one line ------------------------------------------------------------

def _line(ts_ms: int, dev_id: int, vendor: int, dtype: int, ds: int, ifidx: int,
          mcode: int, mvalue: int, interval: int, admin: int, oper: int, sev: int) -> str:
    return (f"{ts_ms}|{dev_id}|{vendor}|{dtype}|{ds}|{ifidx}|{mcode}|{mvalue}"
            f"|{interval}|{admin}|{oper}|{sev}")


def _severity_for_metric(mcode: int, value: int) -> int:
    """Map raw metric value to ECS-like severity_code (0=normal..3=critical)."""
    if mcode == 20001:   # cpu x100
        if value >= 9000: return 3
        if value >= 8000: return 2
        if value >= 7000: return 1
        return 0
    if mcode == 30001:   # temp x100
        if value >= 7500: return 3
        if value >= 7000: return 2
        return 0
    if mcode == 30003:   # power status: 1 normal, 3 critical
        return 3 if value == 3 else 0
    if mcode in (10003, 10004):   # error counters
        return 1 if value % 7 == 0 else 0
    return 0


# --- driver -------------------------------------------------------------

ProgressCB = Callable[[int, int], None]


def generate_bulk(
    target_bytes: int,
    seed: int = 42,
    progress: Optional[ProgressCB] = None,
) -> Iterable[str]:
    """Yield raw text lines. Stops when accumulated message bytes ≥ target."""
    rnd = random.Random(seed)
    interval = 60  # seconds
    state = {dev[0]: _new_state(rnd, dev[0], dev[3]) for dev in DEVICES}

    # Anchor near "now" so TSDS look_back_time accepts these docs.
    ts = int((dt.datetime.utcnow() - dt.timedelta(hours=2)).timestamp() * 1000)
    msg_written = 0
    next_emit = 50_000
    tick = 0

    while msg_written < target_bytes:
        for (dev_id, vendor, dtype, ifcount) in DEVICES:
            st = state[dev_id]

            _step_interface_counters(rnd, st, interval)
            _step_system(rnd, st)
            _step_env(rnd, st)

            # interface metrics (one record per (interface, metric))
            for i in range(1, ifcount + 1):
                ifs = st["if"][i]
                for m in IF_METRICS:
                    line = _line(ts, dev_id, vendor, dtype, DS_INTERFACE, i, m,
                                 ifs[m], interval, ifs["admin"], ifs["oper"],
                                 _severity_for_metric(m, ifs[m]))
                    msg_written += len(line.encode("utf-8")) + 1
                    yield line

            # system metrics
            for m in SYS_METRICS:
                v = (st["sys"]["cpu"] if m == 20001
                     else st["sys"]["mem_used"] if m == 20002
                     else st["sys"]["mem_total"])
                line = _line(ts, dev_id, vendor, dtype, DS_SYSTEM, 0, m, v,
                             interval, 0, 0, _severity_for_metric(m, v))
                msg_written += len(line.encode("utf-8")) + 1
                yield line

            # environment metrics
            for m in ENV_METRICS:
                v = (st["env"]["temp_x100"] if m == 30001
                     else st["env"]["fan_rpm"] if m == 30002
                     else st["env"]["power"])
                line = _line(ts, dev_id, vendor, dtype, DS_ENV, 0, m, v,
                             interval, 0, 0, _severity_for_metric(m, v))
                msg_written += len(line.encode("utf-8")) + 1
                yield line

            # occasional trap (~5% of polling ticks per device)
            if rnd.random() < 0.05:
                ifidx = rnd.randint(1, ifcount)
                tcode = rnd.choices(TRAP_CODES, weights=[6, 5, 1])[0]
                if tcode == 40001:    # linkDown
                    val, admin, oper, sev = 2, 1, 2, 3
                    st["if"][ifidx]["oper"] = 2
                elif tcode == 40002:  # linkUp
                    val, admin, oper, sev = 1, 1, 1, 1
                    st["if"][ifidx]["oper"] = 1
                else:                  # coldStart
                    val, admin, oper, sev = rnd.randint(60_000, 600_000), 0, 0, 2
                    ifidx = 0
                line = _line(ts, dev_id, vendor, dtype, DS_TRAP, ifidx, tcode,
                             val, 0, admin, oper, sev)
                msg_written += len(line.encode("utf-8")) + 1
                yield line

            if progress and msg_written >= next_emit:
                progress(msg_written, target_bytes)
                next_emit = msg_written + 50_000

            if msg_written >= target_bytes:
                break

        ts   += interval * 1000
        tick += 1

    if progress:
        progress(msg_written, target_bytes)


def generate(
    out_path: Path,
    target_bytes: int,
    seed: int = 42,
    start=None,    # signature parity with the other generators (unused here)
    progress: Optional[ProgressCB] = None,
) -> tuple[int, int]:
    """Write one line per record, plain text. Returns (docs, message_bytes)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    msg_bytes = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for line in generate_bulk(target_bytes, seed=seed, progress=progress):
            f.write(line + "\n")
            msg_bytes += len(line.encode("utf-8")) + 1
            n += 1
    return n, msg_bytes

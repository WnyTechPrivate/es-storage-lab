"""Generate ~10MB Fortinet traffic syslog sample."""
import random
import datetime as dt
from config import DATA_DIR

random.seed(42)
TARGET_BYTES = 10 * 1024 * 1024
OUT = DATA_DIR / "raw_sample.log"

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
INTERFACES = ["wan1", "wan2", "internal", "dmz", "vpn1"]
ACTIONS    = ["accept", "deny", "close", "timeout"]
APPCATS    = ["unscanned", "Web.Client", "Network.Service", "Remote.Access", "Email"]
LEVELS     = ["notice", "warning", "information"]
DEVNAMES   = ["WNYT-FW-A", "WNYT-FW-B", "WNYT-FW-DMZ"]
DEVIDS     = ["FG180FTK23902182", "FG200FTK21501100", "FG100FTK22301400"]
HOSTIPS    = ["10.10.200.103", "10.10.200.104", "10.10.200.105"]


def rand_internal_ip():
    return random.choice(INT_PREFIXES) + f"{random.randint(1,254)}.{random.randint(1,254)}"


def rand_external_ip():
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"


def make_line(now: dt.datetime) -> str:
    direction = random.choice(["in", "out"])
    if direction == "in":
        srcip = rand_external_ip()
        dstip = rand_internal_ip()
        srcintf = "wan1"
        dstintf = random.choice(["internal", "dmz"])
    else:
        srcip = rand_internal_ip()
        dstip = rand_external_ip()
        srcintf = random.choice(["internal", "dmz"])
        dstintf = "wan1"

    svc, port, transport, ianano = random.choice(SERVICES)
    srcport = random.randint(1024, 65535)
    dstport = port if random.random() < 0.7 else random.randint(1024, 65535)

    devname = random.choice(DEVNAMES)
    devid   = random.choice(DEVIDS)
    hostip  = random.choice(HOSTIPS)

    eventtime_ns = int(now.timestamp() * 1_000_000_000) + random.randint(0, 999_999)
    sessionid    = random.randint(1_000_000_000, 9_999_999_999)
    policyid     = random.randint(1, 300)
    duration     = random.randint(0, 3600)
    sentpkt      = random.randint(1, 5000)
    rcvdpkt      = random.randint(1, 5000)
    sentbyte     = sentpkt * random.randint(40, 1500)
    rcvdbyte     = rcvdpkt * random.randint(40, 1500)
    action       = random.choice(ACTIONS)
    subtype      = random.choice(SUBTYPES)
    level        = random.choice(LEVELS)
    appcat       = random.choice(APPCATS)

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


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    start = dt.datetime(2026, 3, 18, 0, 0, 0)
    written = 0
    n = 0
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        while written < TARGET_BYTES:
            now = start + dt.timedelta(seconds=n * 0.1)
            line = make_line(now)
            f.write(line)
            written += len(line.encode("utf-8"))
            n += 1
    print(f"wrote {OUT}  docs={n}  bytes={written}")


if __name__ == "__main__":
    main()

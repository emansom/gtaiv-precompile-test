#!/usr/bin/env python3
"""Where in the route did the pipelines get built?

  legsplit.py RUNDIR [RUNDIR ...]

`gpparse.py` says how many pipelines a run built during the route; this says *where*.
It maps FusionFix's session clock (the log's "session clock: t=0 is <local time>" line)
onto `route.json`'s legs and on-foot steps, and prints per leg: the >= 20 ms creations
and the long frames that fell inside it (one log line each), and the cumulative creation
and compile counters as they stood at its end (FusionFix reports those every 15 s, so
they lag the leg boundary by up to that much).

Written for the 09-21 boot-gate control, where the two builds' totals differed by ~50
creations and the difference turned out to sit almost entirely in the on-foot segment at
the Cluckin' Bell -- which no total could have shown.
"""
import argparse
import datetime
import json
import os
import re

CLOCK = re.compile(r"session clock: t=0 is ([\d-]+ [\d:.]+) local time")
CUM = re.compile(r"created by DXVK in gameplay so far: (\d+) pipelines.*?>=5 ms \(compiled\): (\d+)")
CUMT = re.compile(r"gameplay frames t=([\d.]+) ")
SLOW = re.compile(r"gameplay compile t=([\d.]+): DXVK spent ([\d.]+) ms")
LONG = re.compile(r"gameplay long frame t=([\d.]+): ([\d.]+) ms")


def one(rundir):
    log = os.path.join(rundir, "FusionFix.shaders.log")
    rj = os.path.join(rundir, "route.json")
    if not (os.path.exists(log) and os.path.exists(rj)):
        print("%s: no FusionFix.shaders.log / route.json" % rundir)
        return
    text = open(log, encoding="utf-8", errors="replace").read()
    m = CLOCK.search(text)
    if not m:
        print("%s: no session clock line (a build without VkCapture's metrics?)" % rundir)
        return
    t0 = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f").timestamp()
    r = json.load(open(rj))
    rs = r["start_epoch"] - t0                      # the route's start, on the session clock
    spans = [(l["name"], l["start"], l["end"]) for l in r.get("legs", []) if l.get("end")]
    spans += [(s["name"], s["start"], s["end"]) for s in r.get("on_foot", []) if s.get("end")]
    spans.sort(key=lambda s: s[1])
    slow = [float(a) for a, _ in SLOW.findall(text)]
    longf = [float(a) for a, _ in LONG.findall(text)]
    cum, last_t = [], 0.0
    for line in text.splitlines():
        mt = CUMT.search(line)
        if mt:
            last_t = float(mt.group(1))
        mc = CUM.search(line)
        if mc:
            cum.append((last_t, int(mc.group(1)), int(mc.group(2))))

    print("\n== %s   route t=%.1f..%.1f on the session clock"
          % (rundir, rs, rs + r.get("route_live_s", 0)))
    print("   %-18s %7s %7s %6s %6s   %s"
          % ("leg", "from", "to", ">=20ms", ">50ms", "creations / compiles so far"))
    for name, a, b in spans:
        A, B = rs + a, rs + b
        at = [c for c in cum if c[0] <= B]
        print("   %-18s %7.1f %7.1f %6d %6d   %s"
              % (name, A, B, sum(1 for t in slow if A <= t < B), sum(1 for t in longf if A <= t < B),
                 ("%d / %d" % (at[-1][1], at[-1][2])) if at else "-"))
    if cum:
        print("   final: %d creations, %d compiles >= 5 ms" % (cum[-1][1], cum[-1][2]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rundirs", nargs="+", metavar="RUNDIR")
    for d in ap.parse_args().rundirs:
        one(d)

#!/usr/bin/env python3
"""Compare runs over the SAME amount of gameplay, not over the whole route.

  samewindow.py [PLAY_SECONDS] NAME=path/to/FusionFix.shaders.log ...

gpparse.py's route-window columns need route.json's log offsets, which a run whose
route did not finish does not have. What every log does have, at the same cadence, is
vkcapture's cumulative report every 15 s of play. This prints each log's report closest
to a given play= time, so a run that ended after 71 s of gameplay can still be compared
with one that ran the whole route — over the part they share.

Written for state/2026-09-20-linux-engine-warm-v2-test.md, where two of the four arms
ended when the game died mid-route.
"""
import re
import sys

FRAMES = re.compile(r"gameplay frames(?: final)? t=([\d.]+) play=([\d.]+)s: frames (\d+), avg ([\d.]+) fps, "
                    r"p50 ([\d.]+) ms, p95 ([\d.]+) ms, p99 ([\d.]+) ms, max ([\d.]+) ms, spikes (\d+), >50 ms (\d+)")
PIPES = re.compile(r"created by DXVK in gameplay(?: so far)?: (\d+) pipelines .*?>=1 ms: (\d+), "
                   r">=5 ms \(compiled\): (\d+) \(\d+ libraries\), >=20 ms: (\d+); worst ([\d.]+) ms")


def report(path, want):
    """The (frames, pipelines) report pair whose play= time is closest to `want`."""
    rows, frames = [], None
    for line in open(path, encoding="utf-8", errors="replace"):
        m = FRAMES.search(line)
        if m:
            frames = m
            continue
        m = PIPES.search(line)
        if m and frames:
            rows.append((float(frames.group(2)), frames, m))
            frames = None
    if not rows:
        return None
    play, f, p = min(rows, key=lambda r: abs(r[0] - want))
    return dict(play=play, frames=int(f.group(3)), fps=float(f.group(4)), p50=float(f.group(5)),
                p99=float(f.group(7)), maxms=float(f.group(8)), spikes=int(f.group(9)),
                over50=int(f.group(10)), pipes=int(p.group(1)), c1=int(p.group(2)),
                c5=int(p.group(3)), c20=int(p.group(4)), worst=float(p.group(5)))


def main():
    want = float(sys.argv[1]) if len(sys.argv) > 1 and "=" not in sys.argv[1] else 60.0
    args = [a for a in sys.argv[1:] if "=" in a]
    if not args:
        print(__doc__)
        return 2
    print("| run | play s | pipelines | >=1 ms | >=5 ms | >=20 ms | worst ms | frames | fps | p99 | max ms | spikes | >50 ms |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, path in (a.split("=", 1) for a in args):
        r = report(path, want)
        if not r:
            print("| %s | (no gameplay report in the log) |" % name)
            continue
        print("| %s | %.1f | %d | %d | %d | %d | %.1f | %d | %.1f | %.1f | %.1f | %d | %d |"
              % (name, r["play"], r["pipes"], r["c1"], r["c5"], r["c20"], r["worst"],
                 r["frames"], r["fps"], r["p99"], r["maxms"], r["spikes"], r["over50"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Synthesize PresentMon-format before/after captures to self-test the analyzer
# offline (no game). Models a 90 s native-D3D9 run at ~60 fps with:
#   - baseline (precompile OFF, cold driver cache): isolated driver-ISA compile
#     hitches on first traversal (30-200 ms), plus normal jitter and two genuine
#     heavy scene sections (sustained -- must NOT be flagged as compile spikes).
#   - precompiled (precompile ON): the isolated hitches removed; everything else
#     preserved.
# Emits classic PresentMon 1.x CSV columns so the PresentMon adapter is exercised.

import csv
import os
import random

random.seed(1234)
HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 60.0
BASE = 1000.0 / FPS
N = int(90 * FPS)
JITTER = 1.1
HEAVY = [(int(20 * FPS), int(24 * FPS), 7.0), (int(55 * FPS), int(58 * FPS), 5.0)]
HITCHES = [(int(3.2 * FPS), 55), (int(8.7 * FPS), 120), (int(12.1 * FPS), 38),
           (int(19.9 * FPS), 180), (int(27.4 * FPS), 44), (int(33.0 * FPS), 96),
           (int(41.6 * FPS), 61), (int(50.2 * FPS), 150), (int(63.8 * FPS), 33),
           (int(71.0 * FPS), 210), (int(79.5 * FPS), 47), (int(85.1 * FPS), 88)]

PM_HEADER = ["Application", "ProcessID", "SwapChainAddress", "Runtime",
             "SyncInterval", "PresentFlags", "AllowsTearing", "PresentMode",
             "Dropped", "TimeInSeconds", "msInPresentAPI", "msBetweenPresents",
             "msUntilRenderComplete", "msUntilDisplayed", "msBetweenDisplayChange"]


def series():
    dt = []
    for i in range(N):
        v = BASE + random.gauss(0, JITTER)
        for a, b, extra in HEAVY:
            if a <= i < b:
                v += extra + random.gauss(0, 0.8)
        dt.append(max(4.0, v))
    return dt


def write_pm(path, dt):
    t = 0.0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(PM_HEADER)
        for i, d in enumerate(dt):
            t += d / 1000.0                 # TimeInSeconds
            w.writerow(["GTAIV.exe", 1234, "0x0", "DXGI", 0, 0, 0,
                        "Hardware: Legacy Flip", 0, "%.6f" % t, "0.5",
                        "%.3f" % d, "1.0", "1.5", "%.3f" % d])
        # A couple of dropped presents to exercise the Dropped filter.
        w.writerow(["GTAIV.exe", 1234, "0x0", "DXGI", 0, 0, 0,
                    "Hardware: Legacy Flip", 1, "%.6f" % t, "0", "0", "0", "0", "0"])


def main():
    off = series()
    for fr, extra in HITCHES:
        if 0 <= fr < N:
            off[fr] += extra
    on = series()
    write_pm(os.path.join(HERE, "baseline_off.presentmon.csv"), off)
    write_pm(os.path.join(HERE, "precompiled_on.presentmon.csv"), on)
    print("wrote baseline_off.presentmon.csv, precompiled_on.presentmon.csv in", HERE)
    print("baseline: %d isolated hitches injected; precompiled: 0" % len(HITCHES))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""How much of REAL PLAY does a baseline actually cover?

  basecov.py <baseline.bin> <capture.bin> [<capture.bin> ...]

We can measure what a baseline CONTAINS, but the number that decides whether it is
worth its launch cost is what fraction of actual gameplay it HITS -- and that needs
no game run, since both key sets are already on disk.

Coverage is reported at both tiers the replay warms (see ffpc.replay_base_key):
  base identities   shaders + vertex input (incl. instancing) + output/blend state.
                    On a driver that cannot fast-link, every one the baseline misses
                    is a synchronous compile in gameplay. This is the number to watch.
  replay keys       the base plus spec-constant state (alpha test, fog, clip planes,
                    sampler types). Misses here only cost background work on a GPL
                    driver.

TRAPS THIS AVOIDS
  1. declIndex is an index into a PER-FILE declaration table; comparing raw indexes
     across two files compares unrelated declarations. ffpc resolves it to the
     declaration's bytes.
  2. The identity must be the replay's own. The capture's strict record over-counts
     ~14x against what DXVK builds, and would report thousands of phantom misses.
     ffpc mirrors ReplayBaseKey/ReplayPipelineKey. Verified 2026-09-19 the strong
     way: every record of the capture an ASI export was deduplicated from maps onto
     one of the exported keys. Matching distinct COUNTS alone does not prove it -- a
     mirror finer than the ASI's key still counts the export's keys as distinct.
  3. Distinct keys answer "how many shapes did we miss", not "how much play". Misses
     are therefore also weighted by draw count. Counts in captures merged before
     2026-09-19 were compounded by re-merging (41.5e9 vs 5.07e6 real draws); the
     Linux capture was reset then, so its weights are honest from that date on.

"""
import argparse
from collections import defaultdict

import ffpc

ap = argparse.ArgumentParser()
ap.add_argument("baseline")
ap.add_argument("captures", nargs="+")
a = ap.parse_args()

base = ffpc.read(a.baseline)
caps = [ffpc.read(p) for p in a.captures]
use = ffpc.sampler_use_table([base] + caps)
bools = ffpc.bool_mask_table([base] + caps)

base_ids = {ffpc.replay_base_key(base, r) for r in base.keys}
base_keys = {ffpc.replay_key(base, r, use, bools) for r in base.keys}
print("baseline %-44s v%d  %6d records -> %5d replay keys, %4d base identities"
      % (a.baseline.split("/")[-1], base.version, len(base.keys), len(base_keys), len(base_ids)))

for path, c in zip(a.captures, caps):
    ids = defaultdict(int)      # base identity -> draws
    keys = defaultdict(int)     # replay key -> draws
    pair_of = {}
    for r in c.keys:
        b = ffpc.replay_base_key(c, r)
        ids[b] += r[-2]
        keys[ffpc.replay_key(c, r, use, bools)] += r[-2]
        pair_of[b] = (r[ffpc.I_VS], r[ffpc.I_PS])
    inst = sum(1 for r in c.keys if ffpc.instanced(r))

    print()
    print("capture  %-44s v%d  %6d records (%d instanced), shader dir '%s'"
          % (path.split("/")[-1], c.version, len(c.keys), inst, c.shader_dir()))
    for label, have, tbl in (("base identities", base_ids, ids), ("replay keys", base_keys, keys)):
        miss = [k for k in tbl if k not in have]
        draws = sum(tbl.values())
        mdraws = sum(tbl[k] for k in miss)
        print("  %-16s covered %5d / %-5d (%5.1f%%)   missed %4d, carrying %5.2f%% of draws"
              % (label, len(tbl) - len(miss), len(tbl),
                 100.0 * (len(tbl) - len(miss)) / max(1, len(tbl)),
                 len(miss), 100.0 * mdraws / max(1, draws)))

    missed = [k for k in ids if k not in base_ids]
    if missed:
        byshader = defaultdict(lambda: [0, 0])
        for k in missed:
            byshader[pair_of[k]][0] += 1
            byshader[pair_of[k]][1] += ids[k]
        print("  missed base identities by shader pair (top 8 of %d):" % len(byshader))
        for (vs, ps), (n, d) in sorted(byshader.items(), key=lambda kv: -kv[1][1])[:8]:
            print("    %3d identities, %9d draws   vs=%016x ps=%016x" % (n, d, vs, ps))

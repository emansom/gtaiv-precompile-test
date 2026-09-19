#!/usr/bin/env python3
"""How much of RAGE's shader database did our playthroughs actually reach?

  fxcgap.py <fxc_shaders.txt> <cache.bin> [<cache.bin> ...]

The shipped baseline replays pipeline keys harvested from real play, so it covers
only what we happened to render. The .fxc database is everything the game could ever
use. The difference is the ceiling on what any playthrough-independent approach
(walking every technique/pass statically) could add -- measure it before building it.

<fxc_shaders.txt> is fxc_hashes output for the install's shader directory
(`<stage> <hash> <size>` per line). Caches are FFPC containers, v1 or v2.
"""
import sys

import ffpc

if len(sys.argv) < 3:
    sys.exit(__doc__)

fxc = {}
with open(sys.argv[1]) as f:
    for line in f:
        stage, h, size = line.split()
        fxc[int(h, 16)] = (stage, int(size))

print("RAGE .fxc database: %d unique shaders (%d vs, %d ps)"
      % (len(fxc),
         sum(1 for v in fxc.values() if v[0] == "vs"),
         sum(1 for v in fxc.values() if v[0] == "ps")))
print()

for path in sys.argv[2:]:
    c = ffpc.read(path)
    used = {h for r in c.keys for h in (r[ffpc.I_VS], r[ffpc.I_PS])}
    hit = [h for h in fxc if h in used]
    miss = [h for h in fxc if h not in used]
    foreign = len(used - set(fxc) - {0})
    print("%s" % path.split("/")[-1])
    print("  v%d, %d keys, %d vertex declarations, shader dir '%s'"
          % (c.version, len(c.keys), len(c.decls), c.shader_dir()))
    print("  reached  %4d / %d .fxc shaders (%.1f%%)"
          % (len(hit), len(fxc), 100.0 * len(hit) / len(fxc)))
    print("  NEVER    %4d  (vs %d, ps %d)"
          % (len(miss),
             sum(1 for h in miss if fxc[h][0] == "vs"),
             sum(1 for h in miss if fxc[h][0] == "ps")))
    print("  non-.fxc shaders named by keys: %d (FusionFix's own + runtime, or another"
          " install's .fxc)" % foreign)
    print()

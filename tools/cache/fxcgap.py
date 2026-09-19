#!/usr/bin/env python3
"""How much of RAGE's shader database did our playthroughs actually reach?

  fxcgap.py <fxc_shaders.txt> <keys.bin> [<keys.bin> ...]

The shipped baseline replays pipeline keys harvested from real play, so it covers
only what we happened to render. The .fxc database is everything the game could ever
use. The difference is the ceiling on what any playthrough-independent approach
(walking every technique/pass statically) could add -- measure it before building it.
"""
import struct
import sys

NUM_RS = 58
NUM_SAMPLERS = 20
REC = "<QQIIII" + "I" * 4 + "III" + "I" * NUM_RS + "B" * NUM_SAMPLERS + "II"
REC_SZ = struct.calcsize(REC)


def key_shaders(path):
    """Set of shader hashes named by any key, plus the key count."""
    seen = set()
    with open(path, "rb") as f:
        magic, ver, num_rs, num_s, decl_count, rec_count = struct.unpack("<6I", f.read(24))
        assert magic == 0x4B504646, "bad keys magic"
        f.read(4 * num_rs)
        decls = 0
        for _ in range(decl_count):
            n = struct.unpack("<I", f.read(4))[0]
            f.read(8 * n)
            decls += 1
        for _ in range(rec_count):
            buf = f.read(REC_SZ)
            if len(buf) < REC_SZ:
                break
            r = struct.unpack(REC, buf)
            seen.add(r[0])
            seen.add(r[1])
    return seen, rec_count, decls


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
    used, keys, decls = key_shaders(path)
    hit = [h for h in fxc if h in used]
    miss = [h for h in fxc if h not in used]
    foreign = len(used - set(fxc) - {0})
    print("%s" % path.split("/")[-1])
    print("  %d keys, %d vertex declarations" % (keys, decls))
    print("  reached  %4d / %d .fxc shaders (%.1f%%)"
          % (len(hit), len(fxc), 100.0 * len(hit) / len(fxc)))
    print("  NEVER    %4d  (vs %d, ps %d)"
          % (len(miss),
             sum(1 for h in miss if fxc[h][0] == "vs"),
             sum(1 for h in miss if fxc[h][0] == "ps")))
    print("  non-.fxc shaders named by keys: %d (FusionFix's own + runtime)" % foreign)
    print()

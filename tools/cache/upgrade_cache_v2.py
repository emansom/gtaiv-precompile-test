#!/usr/bin/env python3
"""Upgrade a v1 FusionFix pipeline cache to v2.

  upgrade_cache_v2.py <in.bin> <out.bin | out-dir>

A ONE-OFF SHIM, like convert_cache.py before it. ASI builds up to 141a876 have no
migration path: they refuse a v1 file and move it aside as <name>.unmerged. Later
builds (d3d9cache.h) widen v1 in memory the same way this does, so a v1 drop-in
from an older PC works there without this. Given a directory, the result is
written there as FusionFix.<content hash>.bin.

v2 adds the instancing a key was drawn with. A v1 capture never recorded it, so
every upgraded key reads "per-vertex on every stream" (streamFreq = 0). For a key
the game really drew instanced that is wrong, but harmlessly so: replay warms the
per-vertex pipeline, and the first v2 capture adds the instanced one as a new key.
Nothing is lost that was ever known.
"""
import sys

import ffpc

if len(sys.argv) != 3:
    sys.exit(__doc__)
c = ffpc.read(sys.argv[1])
if c.version != 1:
    sys.exit("%s is already v%d" % (sys.argv[1], c.version))
out, size = ffpc.write_to(sys.argv[2], c)
print("%s: v1 -> v%d, %d keys, %d declarations, %d shaders, shader dir '%s' (%d bytes)"
      % (out, ffpc.CURRENT, len(c.keys), len(c.decls), len(c.shaders),
         c.shader_dir(), size))

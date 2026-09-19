#!/usr/bin/env python3
"""Upgrade a v1 FusionFix pipeline cache to v2.

  upgrade_cache_v2.py <in.bin> <out.bin>

A ONE-OFF SHIM, like convert_cache.py before it. The ASI deliberately has no
migration path (pipelinekeys.h, kCacheVersion): it refuses a v1 file and moves it
aside as <name>.unmerged rather than misreading it. The only v1 files that exist
are this project's own captures and the shipped baseline, so they are converted
here, once, and the ASI stays clean.

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
size = ffpc.write(sys.argv[2], c)
print("%s: v1 -> v%d, %d keys, %d declarations, %d shaders, shader dir '%s' (%d bytes)"
      % (sys.argv[2], ffpc.CURRENT, len(c.keys), len(c.decls), len(c.shaders),
         c.shader_dir(), size))

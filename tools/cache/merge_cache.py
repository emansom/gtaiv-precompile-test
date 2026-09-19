#!/usr/bin/env python3
"""Merge FusionFix pipeline caches into one: the core of the golden-cache pipeline.

  merge_cache.py <out.bin> <in.bin> [<in.bin> ...]

Unions the keys of every input, the same way the capture merges a previous session
into a new one: declarations are matched by their BYTES (declIndex is file-local),
a key is identified by everything except its count/firstFrame tail, and the draw
counts of a key seen in several files are summed -- which is correct here, because
different contributions are different play, not a re-read of shared history.

Refuses to mix shader directories. Two captures that resolved different
directories name different bytecode, so their union would be half noise on any
install (see cacheinfo.py). Meta and provenance are taken from the first input.
Reads v1 or v2, writes v2 (see ffpc.py).
"""
import sys

import ffpc

if len(sys.argv) < 3:
    sys.exit(__doc__)
out_path, inputs = sys.argv[1], sys.argv[2:]

merged = None
index = {}          # identity -> position in merged.keys
decl_index = {}     # decl bytes -> index in merged.decls
for path in inputs:
    c = ffpc.read(path)
    if merged is None:
        merged = ffpc.Container()
        merged.meta, merged.rs_types = c.meta, c.rs_types
    elif c.shader_dir() != merged.shader_dir():
        sys.exit("%s was captured against '%s', the first input against '%s' - not merging"
                 % (path, c.shader_dir(), merged.shader_dir()))
    elif c.rs_types != merged.rs_types:
        sys.exit("%s tracks a different render-state set - not merging" % path)

    before = len(merged.keys)
    for r in c.keys:
        ident = ffpc.identity(c, r)
        if ident in index:
            merged.keys[index[ident]][-2] += r[-2]
            continue
        r = list(r)
        d = r[ffpc.I_DECL]
        if d != ffpc.DECL_NONE:
            decl = c.decls[d]
            if decl not in decl_index:
                decl_index[decl] = len(merged.decls)
                merged.decls.append(decl)
            r[ffpc.I_DECL] = decl_index[decl]
        index[ident] = len(merged.keys)
        merged.keys.append(r)
    for h, v in c.shaders.items():
        merged.shaders.setdefault(h, v)
    print("  %-50s v%d  %6d keys, %6d new" % (path.split("/")[-1], c.version,
                                              len(c.keys), len(merged.keys) - before))

size = ffpc.write(out_path, merged)
inst = sum(1 for r in merged.keys if ffpc.instanced(r))
print("wrote %s: %d keys (%d instanced), %d declarations, %d shaders, dir '%s' (%d bytes)"
      % (out_path, len(merged.keys), inst, len(merged.decls), len(merged.shaders),
         merged.shader_dir(), size))

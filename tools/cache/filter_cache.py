#!/usr/bin/env python3
"""Drop every key that names a given shader from a FusionFix pipeline-cache container.

  filter_cache.py <in.bin> <out.bin> [--drop <hashes.txt> ...] [--strip-fxc <hashes.txt> ...]

WHY
  A capture records whatever bytecode the capturing install loads. The Linux install
  that produced the shipped baseline had four vehicle .fxc files that are not part of
  FusionFix's stock set (gta_vehicle_licenseplate, _licenseplate_ext, _track, _track2),
  so 47 of its 2001 keys named shaders that a stock install never loads. Replay still
  "succeeds" for them -- the container carries their bytecode -- which is exactly why
  they are dead weight rather than an error: warming a pipeline nobody will ever draw.

WHAT IT DOES
  - drops every key whose VS or PS hash is in a --drop list
  - drops declarations no surviving key references, and renumbers declIndex
  - drops shader blobs no surviving key references
  - keeps meta untouched: it is the provenance of the capture the keys came from,
    not a description of this file's contents
  Reads v1 or v2, writes v2 (see ffpc.py).

  --strip-fxc keeps every key but drops the BYTECODE of the listed shaders, which is
  what the ASI itself now writes: shaders from an install's .fxc files are resolved
  by hash from that install, so a cache carries bytecode only for what FusionFix
  builds at runtime. Pass fxc_hashes output for every .fxc set the keys may name.

  A --drop or --strip-fxc file holds hashes, one per line: fxc_hashes output
  (`<stage> <hash> <size>`, the hash is the second field) or a bare list.

  To build the drop list: run fxc_hashes over a directory holding ONLY the non-stock
  .fxc files and over one holding the rest, and keep the hashes the first has and
  the second does not (`comm -23`). Compare against the install's own other effects,
  not against another machine, so shaders the branch itself ships are kept.
"""
import argparse

import ffpc


def load_hashes(paths):
    out = set()
    for p in paths or []:
        for line in open(p):
            tok = line.split()
            if tok:
                out.add(int(tok[1] if len(tok) >= 3 else tok[-1], 16))
    return out


ap = argparse.ArgumentParser()
ap.add_argument("inp")
ap.add_argument("out")
ap.add_argument("--drop", action="append")
ap.add_argument("--strip-fxc", action="append")
a = ap.parse_args()
if not a.drop and not a.strip_fxc:
    ap.error("nothing to do: give --drop and/or --strip-fxc")

drop = load_hashes(a.drop)
strip = load_hashes(a.strip_fxc)
c = ffpc.read(a.inp)
n_keys, n_decls, n_shaders = len(c.keys), len(c.decls), len(c.shaders)

gone = [r for r in c.keys if r[ffpc.I_VS] in drop or r[ffpc.I_PS] in drop]
named = {h for r in gone for h in (r[ffpc.I_VS], r[ffpc.I_PS]) if h in drop}
c.keys = [r for r in c.keys if not (r[ffpc.I_VS] in drop or r[ffpc.I_PS] in drop)]
ffpc.prune(c)
n_named = len(c.shaders)
c.shaders = {h: v for h, v in c.shaders.items() if h not in strip}
size = ffpc.write(a.out, c)

print("keys      %d -> %d  (dropped %d, naming %d of the %d listed shaders)"
      % (n_keys, len(c.keys), len(gone), len(named), len(drop)))
print("decls     %d -> %d" % (n_decls, len(c.decls)))
print("shaders   %d -> %d named by keys -> %d carrying bytecode (%d left to the install's .fxc)"
      % (n_shaders, n_named, len(c.shaders), n_named - len(c.shaders)))
print("wrote %s (v%d, %d bytes)" % (a.out, ffpc.CURRENT, size))

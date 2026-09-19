#!/usr/bin/env python3
"""Drop every key that names a given shader from a FusionFix pipeline-cache container.

  filter_cache.py <in.bin> <out.bin> --drop <hashes.txt> [--drop <more.txt>]

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

  A --drop file holds one hex hash per line; only the LAST whitespace-separated token
  is read, so fxc_hashes output (`<stage> <hash> <size>` -> use `cut -d' ' -f2`) or a
  bare hash list both work.

  To build the drop list: run fxc_hashes over a directory holding ONLY the non-stock
  .fxc files and over one holding the rest, and keep the hashes the first has and
  the second does not (`comm -23`). Compare against the install's own other effects,
  not against another machine, so shaders the branch itself ships are kept.
"""
import argparse
import struct
import sys

CACHE_MAGIC = 0x43504646     # 'FFPC'
SEC_META, SEC_RSTYPES, SEC_DECLS, SEC_KEYS, SEC_SHADERS = 1, 2, 3, 4, 5
NUM_RS, NUM_SAMPLERS = 58, 20
REC_FMT = "<QQIIII" + "I" * 4 + "III" + "I" * NUM_RS + "B" * NUM_SAMPLERS + "II"
REC_SZ = struct.calcsize(REC_FMT)
DECL_NONE = 0xFFFFFFFF
I_VS, I_PS, I_DECL = 0, 1, 2


def read_sections(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, version, nsec, _ = struct.unpack_from("<IIII", data, 0)
    if magic != CACHE_MAGIC:
        sys.exit("%s: not an FFPC container (magic 0x%08x)" % (path, magic))
    secs = []
    for i in range(nsec):
        sid, off, size, count = struct.unpack_from("<IIII", data, 16 + 16 * i)
        secs.append((sid, data[off:off + size], count))
    return version, secs


def load_hashes(paths):
    out = set()
    for p in paths:
        for line in open(p):
            tok = line.split()
            if tok:
                out.add(int(tok[-1], 16))
    return out


ap = argparse.ArgumentParser()
ap.add_argument("inp")
ap.add_argument("out")
ap.add_argument("--drop", action="append", required=True)
a = ap.parse_args()

drop = load_hashes(a.drop)
version, secs = read_sections(a.inp)
by_id = {sid: (blob, count) for sid, blob, count in secs}

# ---- keys --------------------------------------------------------------------
kblob, kcount = by_id[SEC_KEYS]
keys = [list(struct.unpack_from(REC_FMT, kblob, i * REC_SZ)) for i in range(kcount)]
kept = [r for r in keys if r[I_VS] not in drop and r[I_PS] not in drop]
dropped_named = {h for r in keys if r not in kept for h in (r[I_VS], r[I_PS]) if h in drop}

# ---- declarations: keep the referenced ones, in their original order ----------
dblob, dcount = by_id[SEC_DECLS]
decls, pos = [], 0
for _ in range(dcount):
    n = struct.unpack_from("<I", dblob, pos)[0]
    decls.append(dblob[pos:pos + 4 + 8 * n])
    pos += 4 + 8 * n
used = sorted({r[I_DECL] for r in kept if r[I_DECL] != DECL_NONE})
remap = {old: new for new, old in enumerate(used)}
for r in kept:
    if r[I_DECL] != DECL_NONE:
        r[I_DECL] = remap[r[I_DECL]]

# ---- shaders: keep the ones a surviving key names -----------------------------
sblob, scount = by_id[SEC_SHADERS]
named = {h for r in kept for h in (r[I_VS], r[I_PS]) if h}
shaders, pos = [], 0
for _ in range(scount):
    h, stage, size = struct.unpack_from("<QII", sblob, pos)
    end = pos + 16 + size
    if h in named:
        shaders.append(sblob[pos:end])
    pos = end

new = {
    SEC_DECLS: (b"".join(decls[i] for i in used), len(used)),
    SEC_KEYS: (b"".join(struct.pack(REC_FMT, *r) for r in kept), len(kept)),
    SEC_SHADERS: (b"".join(shaders), len(shaders)),
}
out_secs = [(sid, *new.get(sid, (blob, count))) for sid, blob, count in secs]

header_sz = 16 + 16 * len(out_secs)
offset, table = header_sz, b""
for sid, blob, count in out_secs:
    table += struct.pack("<IIII", sid, offset, len(blob), count)
    offset += len(blob)
with open(a.out, "wb") as f:
    f.write(struct.pack("<IIII", CACHE_MAGIC, version, len(out_secs), 0))
    f.write(table)
    for _, blob, _ in out_secs:
        f.write(blob)

print("keys      %d -> %d  (dropped %d, naming %d of the %d listed shaders)"
      % (len(keys), len(kept), len(keys) - len(kept), len(dropped_named), len(drop)))
print("decls     %d -> %d" % (dcount, len(used)))
print("shaders   %d -> %d" % (scount, len(shaders)))
print("wrote %s (%d bytes)" % (a.out, offset))

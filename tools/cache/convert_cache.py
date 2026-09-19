#!/usr/bin/env python3
"""Convert the old 3-file shader cache into the new single-file container.

  convert_cache.py <keys.bin> <shaders.bin> <out.bin> [--shader-dir NAME] [--reset-counts]

WHY A ONE-OFF SHIM AND NOT A READER IN THE ASI
  The ASI deliberately has no migration path: nothing has shipped, so carrying
  readers for formats nobody has costs more than re-capturing. But THIS machine's
  cache is 13,864 keys of real play accumulated over many sessions, which is the only
  such dataset that exists and is what the shipped baseline was derived from. Convert
  it once, here, and let the ASI stay clean.

WHAT CHANGES
  old: FusionFix.pipelinekeys.f<fmt>-ms<msaa>.bin   (header + rsTypes + decls + keys)
     + FusionFix.pipelineshaders.bin                ('FFPS' + blobs)
     + FusionFix.pipelinekeys.f<fmt>-ms<msaa>.txt   (human summary, dropped)
  new: FusionFix.pipelinecache.f<fmt>-ms<msaa>.bin  ('FFPC', sectioned, + provenance)

  --reset-counts is the point of doing this at all for THIS file: its per-key draw
  counts sum to 41.5e9 against the 5,073,509 draws actually recorded, because every
  run used to merge several predecessor files that shared history and re-added their
  counts. `count` orders which pipelines get warmed first, so carrying the compounded
  numbers forward would keep that ordering wrong. Clamping each key to 1 keeps the
  COVERAGE (which is the valuable part) and discards the corrupted weighting, which
  future sessions then rebuild honestly.
"""
import argparse
import struct
import sys

NUM_RS = 58
NUM_SAMPLERS = 20
REC_FMT = "<QQIIII" + "I" * 4 + "III" + "I" * NUM_RS + "B" * NUM_SAMPLERS + "II"
REC_SZ = struct.calcsize(REC_FMT)

KEYS_MAGIC = 0x4B504646     # 'FFPK'
KEYS_VERSION = 2
SHADER_MAGIC = 0x53504646   # 'FFPS'
CACHE_MAGIC = 0x43504646    # 'FFPC'
CACHE_VERSION = 1

SEC_META, SEC_RSTYPES, SEC_DECLS, SEC_KEYS, SEC_SHADERS = 1, 2, 3, 4, 5
META_STRINGS = 4            # shaderDir, adapter, driver, os


def read_old_keys(path):
    with open(path, "rb") as f:
        magic, version, num_rs, num_samplers, decl_count, rec_count = struct.unpack("<6I", f.read(24))
        if magic != KEYS_MAGIC:
            sys.exit("%s: not a pipelinekeys file (magic 0x%08x)" % (path, magic))
        if version != KEYS_VERSION:
            sys.exit("%s: v%d, this shim converts v%d" % (path, version, KEYS_VERSION))
        if num_rs != NUM_RS or num_samplers != NUM_SAMPLERS:
            sys.exit("%s: tracks %d states / %d samplers, expected %d / %d"
                     % (path, num_rs, num_samplers, NUM_RS, NUM_SAMPLERS))
        rs_types = list(struct.unpack("<%dI" % num_rs, f.read(4 * num_rs)))
        decls = []
        for _ in range(decl_count):
            n = struct.unpack("<I", f.read(4))[0]
            decls.append(f.read(8 * n))
        keys = []
        for _ in range(rec_count):
            buf = f.read(REC_SZ)
            if len(buf) < REC_SZ:
                break           # short flush: keep what is whole, same as the ASI
            keys.append(buf)
    return rs_types, decls, keys


def read_old_shaders(path):
    out = []
    with open(path, "rb") as f:
        magic, version, count = struct.unpack("<3I", f.read(12))
        if magic != SHADER_MAGIC:
            sys.exit("%s: not a shader sidecar (magic 0x%08x)" % (path, magic))
        for _ in range(count):
            hdr = f.read(16)
            if len(hdr) < 16:
                break
            h, stage, size = struct.unpack("<QII", hdr)
            code = f.read(size)
            if len(code) < size:
                break
            out.append((h, stage, code))
    return out


def wstr(buf, s):
    b = s.encode("utf-8")
    buf += struct.pack("<I", len(b)) + b
    return buf


ap = argparse.ArgumentParser()
ap.add_argument("keys")
ap.add_argument("shaders")
ap.add_argument("out")
ap.add_argument("--shader-dir", default="win32_30",
                help="which shader directory the capture ran against (the bucketing key)")
ap.add_argument("--adapter", default="")
ap.add_argument("--driver", default="")
ap.add_argument("--os", default="")
ap.add_argument("--bb-format", type=int, default=21)     # D3DFMT_A8R8G8B8
ap.add_argument("--msaa", type=int, default=0)
ap.add_argument("--reset-counts", action="store_true")
a = ap.parse_args()

rs_types, decls, keys = read_old_keys(a.keys)
shaders = read_old_shaders(a.shaders)
print("read %d keys, %d declarations, %d shaders" % (len(keys), len(decls), len(shaders)))

if a.reset_counts:
    fixed = []
    total_before = 0
    for buf in keys:
        r = list(struct.unpack(REC_FMT, buf))
        total_before += r[-2]
        r[-2] = 1
        fixed.append(struct.pack(REC_FMT, *r))
    keys = fixed
    print("reset draw counts to 1 (they summed to %d, which is the merge compounding)"
          % total_before)

# ---- assemble the sections -------------------------------------------------
meta = struct.pack("<IIIiIQIII",
                   NUM_RS, NUM_SAMPLERS, a.bb_format, a.msaa,
                   0,              # frames: unknown for a converted file
                   0,              # draws: unknown, and the old count was corrupt anyway
                   1,              # backend: DXVK (this cache came from Proton)
                   0, 0)           # vendorId, deviceId: unknown
meta += struct.pack("<I", META_STRINGS)
for s in (a.shader_dir, a.adapter, a.driver, a.os):
    meta = wstr(meta, s)

rstypes_blob = struct.pack("<%dI" % len(rs_types), *rs_types)
decls_blob = b"".join(struct.pack("<I", len(d) // 8) + d for d in decls)
keys_blob = b"".join(keys)
shaders_blob = b"".join(struct.pack("<QII", h, stage, len(code)) + code
                        for h, stage, code in shaders)

sections = [
    (SEC_META, meta, 1),
    (SEC_RSTYPES, rstypes_blob, len(rs_types)),
    (SEC_DECLS, decls_blob, len(decls)),
    (SEC_KEYS, keys_blob, len(keys)),
    (SEC_SHADERS, shaders_blob, len(shaders)),
]

header_sz = 16 + 16 * len(sections)
offset = header_sz
table = b""
for sid, blob, count in sections:
    table += struct.pack("<IIII", sid, offset, len(blob), count)
    offset += len(blob)

with open(a.out, "wb") as f:
    f.write(struct.pack("<IIII", CACHE_MAGIC, CACHE_VERSION, len(sections), 0))
    f.write(table)
    for _, blob, _ in sections:
        f.write(blob)

print("wrote %s (%d bytes), shader dir '%s'" % (a.out, offset, a.shader_dir))

#!/usr/bin/env python3
"""Build a fault-injection corpus for FusionFix's D3D9 cache reader (d3d9cache.h).

  make_corpus.py <good.bin> <outdir>

<good.bin> is a real, valid cache (e.g. cache/windows-amd-dxvk/). Every file written
to <outdir> is a variant of it: damaged containers, out-of-range values a replay
would pass to D3D9, malformed or mis-hashed shader bytecode, older and newer
formats, duplicates under other names. <outdir>/expected.txt lists what the reader
must say about each, one "<file> <verdict> [<keys> <decls> <shaders> dropped]" line;
run the files through d3d9cache_check.exe and compare with check_corpus.py.

Nothing here is random except the bit flips, which use a fixed seed.
"""
import os
import random
import struct
import sys

import ffpc

if len(sys.argv) != 3:
    sys.exit(__doc__)
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
good = open(src, "rb").read()
base = ffpc.read(src)
expected = []

REC2 = struct.calcsize(ffpc.REC[2])
REC1 = struct.calcsize(ffpc.REC[1])
I_RS = 13
RS = ["ZENABLE", "ZWRITEENABLE", "ZFUNC", "ALPHATESTENABLE", "ALPHAFUNC", "ALPHAREF", "ALPHABLENDENABLE",
      "SRCBLEND", "DESTBLEND", "BLENDOP"]


def put(name, data, verdict, dropped=None):
    with open(os.path.join(out, name), "wb") as f:
        f.write(data)
    expected.append("%s %s%s" % (name, verdict, "" if dropped is None else " %d %d %d" % dropped))


def container(mutate):
    c = ffpc.read(src)
    mutate(c)
    path = os.path.join(out, ".tmp")
    ffpc.write(path, c)
    data = open(path, "rb").read()
    os.remove(path)
    return data


def sections(data):
    n = struct.unpack_from("<I", data, 8)[0]
    return {struct.unpack_from("<I", data, 16 + 16 * i)[0]: (16 + 16 * i,) + struct.unpack_from("<III", data, 20 + 16 * i)
            for i in range(n)}


def patch(data, off, fmt, *vals):
    b = bytearray(data)
    struct.pack_into(fmt, b, off, *vals)
    return bytes(b)


def fnv(b):
    """The ASI's SHADER hash (pipelinekeys::Fnv1a): FNV-1a with its legacy offset
    basis, the standard one missing its last digit. Not the content-name hash."""
    h = 1469598103934665603
    for x in b:
        h = ((h ^ x) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


secs = sections(good)
keys_off = secs[ffpc.SEC_KEYS][1]

# ---- the real thing, and copies of it ----------------------------------------
put("00-real-windows.bin", good, "accepted", (0, 0, 0))
put("01-copy of windows.bin", good, "duplicate")
put("02-another-name.BIN", good, "duplicate")

# ---- not a cache at all ----------------------------------------------------------
put("10-zero-length.bin", b"", "rejected")
put("11-garbage.bin", bytes(random.Random(1).getrandbits(8) for _ in range(65536)), "rejected")
put("12-wrong-magic.bin", patch(good, 0, "<I", 0x4B504646), "rejected")         # 'FFPK', the old key file
put("13-fossilize.bin", b"\x81FOSSILIZEDB" + bytes(4000), "rejected")
put("14-too-large.bin", good + bytes(17 * 1024 * 1024), "rejected")

# ---- truncated ---------------------------------------------------------------------
for i, cut in enumerate([3, 12, 40, 100, secs[ffpc.SEC_DECLS][1] + 10, keys_off + 5000, len(good) // 2, len(good) - 1]):
    put("2%d-truncated-at-%d.bin" % (i, cut), good[:cut], "rejected")

# ---- absurd counts and offsets ---------------------------------------------------
put("30-section-count-huge.bin", patch(good, 8, "<I", 0xFFFFFFFF), "rejected")
put("31-section-count-zero.bin", patch(good, 8, "<I", 0), "rejected")
t, off, size, count = secs[ffpc.SEC_KEYS]
put("32-key-count-huge.bin", patch(good, t + 12, "<I", 0xFFFFFFFF), "rejected")
put("33-key-offset-huge.bin", patch(good, t + 4, "<I", 0xFFFFFF00), "rejected")
put("34-key-size-huge.bin", patch(good, t + 8, "<I", 0x7FFFFFFF), "rejected")
t, off, size, count = secs[ffpc.SEC_DECLS]
put("35-decl-count-huge.bin", patch(good, t + 12, "<I", 0x10000000), "rejected")
put("36-decl-elements-huge.bin", patch(good, off, "<I", 0xFFFFFFFF), "rejected")
t, off, size, count = secs[ffpc.SEC_SHADERS]
put("37-shader-count-huge.bin", patch(good, t + 12, "<I", 0x40000000), "rejected")
put("38-shader-size-huge.bin", patch(good, off + 12, "<I", 0xFFFFFFF0), "rejected")
t, off, size, count = secs[ffpc.SEC_META]
put("39-meta-strings-huge.bin", patch(good, off + 40, "<I", 0xFFFFFFFF), "rejected")
put("3a-meta-string-length-huge.bin", patch(good, off + 44, "<I", 0x7FFFFFFF), "rejected")
put("3b-section-overlaps-header.bin", patch(good, secs[ffpc.SEC_KEYS][0] + 4, "<I", 4), "rejected")

# ---- other versions / builds / installs ------------------------------------------
def v1(data):
    """The same file as container v1: KeyRecord without streamFreq."""
    c = ffpc.read(src)
    fmt1 = ffpc.REC[1]
    keys = b"".join(struct.pack(fmt1, *(r[:ffpc.I_STREAMS] + r[-2:])) for r in c.keys)
    body = [(ffpc.SEC_META, c.meta, 1), (ffpc.SEC_RSTYPES, c.rs_types, len(c.rs_types) // 4),
            (ffpc.SEC_DECLS, b"".join(struct.pack("<I", len(d) // 8) + d for d in c.decls), len(c.decls)),
            (ffpc.SEC_KEYS, keys, len(c.keys)),
            (ffpc.SEC_SHADERS, b"".join(struct.pack("<QII", h, s, len(code)) + code for h, (s, code) in c.shaders.items()),
             len(c.shaders))]
    offset = 16 + 16 * len(body)
    table = b""
    for sid, blob, n in body:
        table += struct.pack("<IIII", sid, offset, len(blob), n)
        offset += len(blob)
    return struct.pack("<IIII", ffpc.MAGIC, 1, len(body), 0) + table + b"".join(b for _, b, _ in body)


put("40-format-v1.bin", v1(good), "accepted", (0, 0, 0))
put("41-format-v3.bin", patch(good, 4, "<I", 3), "skipped")
put("42-format-v0.bin", patch(good, 4, "<I", 0), "rejected")


def shader_dir(c, name):
    off = struct.calcsize(ffpc.META_FMT)
    n = struct.unpack_from("<I", c.meta, off)[0]
    c.meta = c.meta[:off] + struct.pack("<I", len(name)) + name + c.meta[off + 4 + n:]


put("43-shaderdir-nv8.bin", container(lambda c: shader_dir(c, b"win32_30_nv8")), "skipped")
put("44-numrs-57.bin", patch(good, secs[ffpc.SEC_META][1], "<I", 57), "skipped")

# ---- out-of-range values in keys: each drops only its key ------------------------
def keyfield(i, field, value):
    def m(c):
        c.keys[i][field] = value
    return m


def many(*ms):
    def m(c):
        for x in ms:
            x(c)
    return m


bad_keys = [
    keyfield(0, 4, 0),                              # primType 0
    keyfield(1, 4, 7),                              # primType 7
    keyfield(2, I_RS + 2, 99),                      # ZFUNC 99
    keyfield(3, I_RS + 7, 40),                      # SRCBLEND 40
    keyfield(4, I_RS + 9, 0),                       # BLENDOP 0
    keyfield(5, 6, 12345),                          # rtFmt[0] not a format
    keyfield(6, 10, 7),                             # dsFmt 7
    keyfield(7, 11, 99),                            # msType 99
    keyfield(8, 13 + 58 + 3, 9),                    # samplerType 9
    keyfield(9, ffpc.I_STREAMS + 1, 0x80000000),    # instance data, divisor 0
    keyfield(10, ffpc.I_STREAMS + 0, 0x80000001),   # instance data on stream 0
    keyfield(11, I_RS + 55, 0x7FC00000),            # DEPTHBIAS NaN
    keyfield(12, 2, 0xFFFFFFF0),                    # declIndex out of range
    many(keyfield(14, 2, ffpc.DECL_NONE), keyfield(14, 3, 0x4004)),           # FVF: undefined position type
    keyfield(15, I_RS + 18, 4),                     # CULLMODE 4
    keyfield(16, I_RS + 52, 5),                     # VERTEXBLEND 5
]
# control: a valid FVF (XYZ | TEX1) on the FVF path must be KEPT
control = many(keyfield(13, 2, ffpc.DECL_NONE), keyfield(13, 3, 0x102))
put("50-bad-enums.bin", container(many(control, *bad_keys)), "accepted", (len(bad_keys), 0, 0))
put("51-all-keys-bad.bin", container(lambda c: [r.__setitem__(4, 9) for r in c.keys]), "accepted", (len(base.keys), 0, 0))

# ---- invalid vertex declarations: each drops the declaration and its keys ---------
def decl_users(c, d):
    return sum(1 for r in c.keys if r[2] == d)


def decl_mut(d, fn):
    def m(c):
        el = bytearray(c.decls[d])
        fn(el)
        c.decls[d] = bytes(el)
    return m


end0 = len(base.decls[0]) - 8
bad_decls = [
    (0, lambda el: el.__setitem__(slice(end0, end0 + 8), struct.pack("<HHBBBB", 0, 0, 2, 0, 0, 0))),   # no END
    (1, lambda el: struct.pack_into("<H", el, 0, 7)),                                                    # stream 7
    (2, lambda el: struct.pack_into("<B", el, 4, 30)),                                                   # type 30
    (3, lambda el: struct.pack_into("<HHBBBB", el, 0, 0xFF, 0, 17, 0, 0, 0)),                           # END first
    (4, lambda el: struct.pack_into("<B", el, 6, 20)),                                                   # usage 20
    (5, lambda el: struct.pack_into("<H", el, 2, 6)),                                                    # offset 6
]
dropped_keys = sum(decl_users(base, d) for d, _ in bad_decls)
put("60-bad-declarations.bin", container(many(*(decl_mut(d, f) for d, f in bad_decls))), "accepted",
    (dropped_keys, len(bad_decls), 0))

# ---- shader bytecode ------------------------------------------------------------------
ps = next(h for h, (s, code) in sorted(base.shaders.items()) if s == 1 and any(ffpc.ps_sampler_use(code)))
vs = next(h for h, (s, code) in sorted(base.shaders.items()) if s == 0)


def reshader(h, fn, rehash=True):
    """Replace one blob's bytecode; rehash=True stores it under its new, correct hash."""
    def m(c):
        stage, code = c.shaders.pop(h)
        code = fn(bytearray(code))
        c.shaders[fnv(code) if rehash else h] = (stage, bytes(code))
    return m


def tokens(code):
    return list(struct.unpack("<%dI" % (len(code) // 4), code))


def first_dcl(code, regtype):
    t = tokens(code)
    i = 1
    while i < len(t):
        op = t[i] & 0xFFFF
        if op == 0xFFFE:
            i += 1 + ((t[i] >> 16) & 0x7FFF)
            continue
        if op == 0x1F and (((t[i + 2] >> 28) & 7) | ((t[i + 2] >> 8) & 0x18)) == regtype:
            return i
        i += 1 + ((t[i] >> 24) & 0xF)
    raise ValueError("no dcl")


def set_tok(code, i, v):
    struct.pack_into("<I", code, 4 * i, v)
    return code


put("70-shader-hash-mismatch.bin", container(reshader(ps, lambda c: set_tok(c, 5, 0x12345678), rehash=False)),
    "accepted", (0, 0, 1))
put("71-shader-no-end.bin", container(reshader(ps, lambda c: c[:-4])), "accepted", (0, 0, 1))
put("72-shader-sampler-s20.bin",
    container(reshader(ps, lambda c: set_tok(c, first_dcl(c, 10) + 2, (tokens(c)[first_dcl(c, 10) + 2] & ~0x7FF) | 20))),
    "accepted", (0, 0, 1))
put("73-shader-unknown-opcode.bin", container(reshader(ps, lambda c: set_tok(c, first_dcl(c, 10), 0x02000031))),
    "accepted", (0, 0, 1))
put("74-shader-wrong-stage.bin", container(reshader(ps, lambda c: set_tok(c, 0, 0xFFFE0300))), "accepted", (0, 0, 1))
put("75-shader-comment-past-end.bin", container(reshader(vs, lambda c: set_tok(c, 1, 0x7FFFFFFE))), "accepted", (0, 0, 1))
put("76-shader-sm1.bin", container(reshader(vs, lambda c: set_tok(c, 0, 0xFFFE0101))), "accepted", (0, 0, 1))
put("77-shader-instruction-past-end.bin",
    container(reshader(ps, lambda c: set_tok(c, len(c) // 4 - 1, 0x0F000001))), "accepted", (0, 0, 1))
put("78-shader-odd-size.bin", container(reshader(ps, lambda c: c + b"\x00")), "accepted", (0, 0, 1))
put("79-shader-stage-9.bin", container(lambda c: c.shaders.__setitem__(ps, (9, c.shaders[ps][1]))), "accepted", (0, 0, 1))
# 17 input declarations (v0..v15, then v0 again): each register is in range, but
# DXVK's input signature holds 16 and throws past that.
dcls = b"".join(struct.pack("<III", 0x0200001F, 0x80000005 | (i << 16 & 0xF0000), 0x800F0000 | 0x10000000 | (i % 16))
                for i in range(17))
put("7a-shader-17-inputs.bin", container(reshader(vs, lambda c: bytearray(c[:4] + dcls + c[4:]))), "accepted", (0, 0, 1))

# ---- bit flips anywhere: must never crash; any verdict is fine ------------------------
rng = random.Random(1234)
for i in range(12):
    b = bytearray(good)
    for _ in range(1 + i // 3):
        pos = rng.randrange(len(b))
        b[pos] ^= 1 << rng.randrange(8)
    put("8%x-bitflip.bin" % i, bytes(b), "any")
# targeted: a flip inside a key, inside a shader, inside the section table
RS0 = 60                                            # byte offset of KeyRecord::rs[0] (ZENABLE)
put("90-flip-in-key.bin", patch(good, keys_off + 5 * REC2 + RS0, "<I", 0x40000001), "accepted", (1, 0, 0))
sh_off = secs[ffpc.SEC_SHADERS][1]
b = bytearray(good)
b[sh_off + 16 + 40] ^= 0x10
put("91-flip-in-shader.bin", bytes(b), "accepted", (0, 0, 1))
put("92-flip-in-table.bin", patch(good, secs[ffpc.SEC_SHADERS][0] + 4, "<I", secs[ffpc.SEC_SHADERS][1] + 0x10000000), "rejected")

with open(os.path.join(out, "expected.txt"), "w") as f:
    f.write("\n".join(expected) + "\n")
print("wrote %d files to %s" % (len(expected), out))

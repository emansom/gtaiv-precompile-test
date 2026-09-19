"""Read and write FusionFix pipeline-cache containers ('FFPC'), versions 1 and 2.

Shared by filter_cache.py, merge_cache.py and upgrade_cache_v2.py so the record
layout is written down once, the way pipelinekeys.h is the one definition on the
ASI side. Keep the two in step: a layout drift here parses fine and silently
mislabels every field after the change.

  v1  first single-file container
  v2  KeyRecord gains streamFreq[4] before count: the instancing a key was drawn
      with (D3DSTREAMSOURCE_INSTANCEDATA | divisor per stream, else 0)

Records are returned as lists of field values in KeyRecord order. Writing always
produces the current version (2); a v1 record is widened with streamFreq = 0,
which is what "never seen instanced" means.
"""
import struct

MAGIC = 0x43504646            # 'FFPC'
CURRENT = 2
SEC_META, SEC_RSTYPES, SEC_DECLS, SEC_KEYS, SEC_SHADERS = 1, 2, 3, 4, 5
NUM_RS, NUM_SAMPLERS, MAX_STREAMS = 58, 20, 4
DECL_NONE = 0xFFFFFFFF

_HEAD = "<QQIIII" + "I" * 4 + "III" + "I" * NUM_RS + "B" * NUM_SAMPLERS
REC = {1: _HEAD + "II", 2: _HEAD + "I" * MAX_STREAMS + "II"}

# Field positions (same in both versions up to the samplers).
I_VS, I_PS, I_DECL = 0, 1, 2
I_STREAMS = 13 + NUM_RS + NUM_SAMPLERS        # v2 only
META_FMT = "<IIIiIQIIII"                      # CacheMeta, #pragma pack(1), 44 bytes


class Container:
    def __init__(self):
        self.version = CURRENT
        self.meta = None          # raw bytes of the meta section (CacheMeta + strings)
        self.rs_types = b""       # raw bytes
        self.decls = []           # list of bytes: n * D3DVERTEXELEMENT9 (8 bytes each)
        self.keys = []            # list of field lists, CURRENT layout
        self.shaders = {}         # hash -> (stage, code)

    def shader_dir(self):
        """The bucketing key: first meta string."""
        off = struct.calcsize(META_FMT)
        n = struct.unpack_from("<I", self.meta, off)[0]
        return self.meta[off + 4:off + 4 + n].decode("utf-8", "replace")


def read(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, version, nsec, _ = struct.unpack_from("<IIII", data, 0)
    if magic != MAGIC:
        raise ValueError("%s: not an FFPC container (magic 0x%08x)" % (path, magic))
    if version not in REC:
        raise ValueError("%s: container v%d, this tool reads v1 and v2" % (path, version))
    fmt = REC[version]
    size = struct.calcsize(fmt)
    c = Container()
    c.version = version
    for i in range(nsec):
        sid, off, sz, count = struct.unpack_from("<IIII", data, 16 + 16 * i)
        blob = data[off:off + sz]
        if sid == SEC_META:
            c.meta = blob
        elif sid == SEC_RSTYPES:
            c.rs_types = blob
        elif sid == SEC_DECLS:
            pos = 0
            for _ in range(count):
                n = struct.unpack_from("<I", blob, pos)[0]
                c.decls.append(blob[pos + 4:pos + 4 + 8 * n])
                pos += 4 + 8 * n
        elif sid == SEC_KEYS:
            for j in range(count):
                r = list(struct.unpack_from(fmt, blob, j * size))
                if version == 1:
                    r[-2:-2] = [0] * MAX_STREAMS
                c.keys.append(r)
        elif sid == SEC_SHADERS:
            pos = 0
            for _ in range(count):
                h, stage, n = struct.unpack_from("<QII", blob, pos)
                c.shaders[h] = (stage, blob[pos + 16:pos + 16 + n])
                pos += 16 + n
    return c


def write(path, c):
    fmt = REC[CURRENT]
    sections = [
        (SEC_META, c.meta, 1),
        (SEC_RSTYPES, c.rs_types, len(c.rs_types) // 4),
        (SEC_DECLS, b"".join(struct.pack("<I", len(d) // 8) + d for d in c.decls), len(c.decls)),
        (SEC_KEYS, b"".join(struct.pack(fmt, *r) for r in c.keys), len(c.keys)),
        (SEC_SHADERS, b"".join(struct.pack("<QII", h, s, len(code)) + code
                               for h, (s, code) in c.shaders.items()), len(c.shaders)),
    ]
    offset = 16 + 16 * len(sections)
    table = b""
    for sid, blob, count in sections:
        table += struct.pack("<IIII", sid, offset, len(blob), count)
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(struct.pack("<IIII", MAGIC, CURRENT, len(sections), 0))
        f.write(table)
        for _, blob, _ in sections:
            f.write(blob)
    return offset


def identity(c, r):
    """What makes two records the same key across files: every field except the
    count/firstFrame tail, with the file-local declIndex replaced by the
    declaration's own bytes (the same rule the capture's merge uses)."""
    d = r[I_DECL]
    decl = c.decls[d] if d != DECL_NONE and d < len(c.decls) else b""
    return (tuple(r[:I_DECL]), decl, tuple(r[I_DECL + 1:-2]))


def instanced(r):
    return any(r[I_STREAMS:I_STREAMS + MAX_STREAMS])


def prune(c):
    """Drop declarations and shader blobs no key references; renumber declIndex."""
    used = sorted({r[I_DECL] for r in c.keys if r[I_DECL] != DECL_NONE})
    remap = {old: new for new, old in enumerate(used)}
    for r in c.keys:
        if r[I_DECL] != DECL_NONE:
            r[I_DECL] = remap[r[I_DECL]]
    c.decls = [c.decls[i] for i in used]
    named = {h for r in c.keys for h in (r[I_VS], r[I_PS]) if h}
    c.shaders = {h: v for h, v in c.shaders.items() if h in named}

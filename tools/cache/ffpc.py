"""Read and write FusionFix pipeline-cache containers ('FFPC'), versions 1 to 3.

Shared by filter_cache.py, merge_cache.py and upgrade_cache_v2.py so the record
layout is written down once, the way pipelinekeys.h is the one definition on the
ASI side. Keep the two in step: a layout drift here parses fine and silently
mislabels every field after the change.

  v1  first single-file container
  v2  KeyRecord gains streamFreq[4] before count: the instancing a key was drawn
      with (D3DSTREAMSOURCE_INSTANCEDATA | divisor per stream, else 0)
  v3  KeyRecord gains the rest of what DXVK specialises a D3D9 pipeline on and the
      v2 key left to ambient device state: the b# registers per stage, DXVK's
      clip-plane COUNT (enabled AND non-zero, not the enable mask), the
      projected-texture stage mask, the per-slot sampler MODE (plain / Fetch4 /
      depth-compare) and the fixed-function texture stage block

Records are returned as lists of field values in KeyRecord order. Writing always
produces the current version (3); an older record is widened exactly as the ASI's
reader widens it in memory (d3d9cache.h, WidenToV3) -- streamFreq = 0 for v1, and
for v2 the defaults the replay actually drew those keys with, with clipPlaneCount
inferred as the popcount of the enable mask. write_named()/write_to() write under
the content name the ASI shares files by, FusionFix.<h>.bin -- see "sharing
between PCs" below.
"""
import os
import struct

MAGIC = 0x43504646            # 'FFPC'
CURRENT = 3
SEC_META, SEC_RSTYPES, SEC_DECLS, SEC_KEYS, SEC_SHADERS = 1, 2, 3, 4, 5
NUM_RS, NUM_SAMPLERS, MAX_STREAMS = 58, 20, 4
FF_STAGES = 8
DECL_NONE = 0xFFFFFFFF

_HEAD = "<QQIIII" + "I" * 4 + "III" + "I" * NUM_RS + "B" * NUM_SAMPLERS
# vsBools, psBools, clipPlaneCount, projMask, samplerMode[20], ffStage[8] x 9 bytes
_SPEC = "HHBB" + "B" * NUM_SAMPLERS + "B" * (9 * FF_STAGES)
REC = {1: _HEAD + "II",
       2: _HEAD + "I" * MAX_STREAMS + "II",
       3: _HEAD + "I" * MAX_STREAMS + _SPEC + "II"}

# Field positions (same in every version up to the samplers).
I_VS, I_PS, I_DECL = 0, 1, 2
I_STREAMS = 13 + NUM_RS + NUM_SAMPLERS        # v2+
I_SPEC = I_STREAMS + MAX_STREAMS              # v3: vsBools is the first of them
I_VSBOOLS, I_PSBOOLS = I_SPEC, I_SPEC + 1
I_CLIPCOUNT, I_PROJMASK = I_SPEC + 2, I_SPEC + 3
I_SAMPLERMODE = I_SPEC + 4                    # 20 entries
I_FFSTAGE = I_SAMPLERMODE + NUM_SAMPLERS      # 8 x (colorOp, alphaOp, resultArg,
                                              #      colorArg[3], alphaArg[3])
N_SPEC = 4 + NUM_SAMPLERS + 9 * FF_STAGES
META_FMT = "<IIIiIQIIII"                      # CacheMeta, #pragma pack(1), 44 bytes

# D3DTOP_MODULATE / SELECTARG1 / DISABLE and D3DTA_CURRENT / TEXTURE: D3D9's own
# texture stage defaults, which is what a device nobody has told otherwise holds.
# Mirrors pipelinekeys::DefaultFFStages.
def default_ff_stages():
    out = []
    for s in range(FF_STAGES):
        out += [4 if s == 0 else 1,      # colorOp
                2 if s == 0 else 1,      # alphaOp
                1,                       # resultArg  D3DTA_CURRENT
                1, 2, 1,                 # colorArg0..2
                1, 2, 1]                 # alphaArg0..2
    return out


# Which of ARG0/1/2 an op reads, exactly as D3D9DeviceEx::GetTextureStageArgMask
# decides it (dxvk d3d9_device.cpp:8273). Mirrors pipelinekeys::FFArgMask.
def ff_arg_mask(op):
    if op in (1, 22, 23):      # DISABLE, BUMPENVMAP, BUMPENVMAPLUMINANCE
        return 0b000
    if op in (2, 17):          # SELECTARG1, PREMODULATE
        return 0b010
    if op == 3:                # SELECTARG2
        return 0b100
    if op in (25, 26):         # MULTIPLYADD, LERP
        return 0b111
    return 0b110


def canonical_ff_stages(ff):
    """Mirrors pipelinekeys::CanonicalFFStages.

    The capture writes a disabled stage all-zero with both ops DISABLE, which is
    what D3D9SpecData::disableTextureStage stores; a widened pre-v3 record gets
    D3D9's defaults instead. Both mean "off", so they have to hash the same or a
    v3 capture replayed beside a v2 baseline draws every no-pixel-shader identity
    twice. Same two merging rules as the ASI: nothing survives the first disabled
    stage, and an argument the op does not consume is zeroed."""
    out = list(ff)
    off = False
    for s in range(FF_STAGES):
        b = s * 9
        if off or out[b] == 1:               # D3DTOP_DISABLE
            off = True
            out[b:b + 9] = [1, 1, 0, 0, 0, 0, 0, 0, 0]
            continue
        cm, am = ff_arg_mask(out[b]), ff_arg_mask(out[b + 1])
        for a in range(3):
            if not (cm >> a) & 1:
                out[b + 3 + a] = 0
            if not (am >> a) & 1:
                out[b + 6 + a] = 0
    return tuple(out)


def widen_to_v3(r, rs_types):
    """The v3 specialisation block for a pre-v3 record, appended in place.

    Every value is a default the device measurably held, with one inference:
    DXVK counts the clip planes that are enabled AND non-zero, and a pre-v3 file
    has no coefficients, so the count is taken to be the popcount of the enable
    mask. That over-warms at worst; the other direction stutters. Same rule as
    d3d9cache.h's WidenToV3, which is what makes an old file replay the same
    offline and in the ASI."""
    try:
        cpe = 13 + list(rs_types).index(152)      # D3DRS_CLIPPLANEENABLE
        count = bin(r[cpe] & 0x3F).count("1")
    except ValueError:
        count = 0
    return [0, 0, count, 0] + [0] * NUM_SAMPLERS + default_ff_stages()


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

    def rs_index(self, d3drs):
        """Field index of a render state in this file's records, found by its
        D3DRENDERSTATETYPE value through the file's own rsTypes section rather than
        by position, so a reordered state list cannot silently shift every field."""
        types = struct.unpack("<%dI" % (len(self.rs_types) // 4), self.rs_types)
        return 13 + types.index(d3drs)


def read(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, version, nsec, _ = struct.unpack_from("<IIII", data, 0)
    if magic != MAGIC:
        raise ValueError("%s: not an FFPC container (magic 0x%08x)" % (path, magic))
    if version not in REC:
        raise ValueError("%s: container v%d, this tool reads v1 to v%d" % (path, version, CURRENT))
    fmt = REC[version]
    size = struct.calcsize(fmt)
    c = Container()
    c.version = version
    key_blob, key_count = b"", 0
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
            key_blob, key_count = blob, count
        elif sid == SEC_SHADERS:
            pos = 0
            for _ in range(count):
                h, stage, n = struct.unpack_from("<QII", blob, pos)
                c.shaders[h] = (stage, blob[pos + 16:pos + 16 + n])
                pos += 16 + n
    # Keys last: widening a pre-v3 record needs the rsTypes section, and the
    # section table does not promise an order.
    for j in range(key_count):
        r = list(struct.unpack_from(fmt, key_blob, j * size))
        if version == 1:
            r[-2:-2] = [0] * MAX_STREAMS
        if version < 3:
            r[-2:-2] = widen_to_v3(r, struct.unpack("<%dI" % (len(c.rs_types) // 4), c.rs_types))
        c.keys.append(r)
    return c


def encode(c):
    """The container as bytes, always the current version."""
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
    return (struct.pack("<IIII", MAGIC, CURRENT, len(sections), 0) + table
            + b"".join(blob for _, blob, _ in sections))


def write(path, c):
    data = encode(c)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


# ---- sharing between PCs ----------------------------------------------------------
#
# FusionFix names the files it shares after their content: FusionFix.<h>.bin in
# plugins\d3d9cache\, <h> = 16 lowercase hex digits of 64-bit FNV-1a over the whole
# file. Same content, same name, so copying folders between PCs never needs a rename,
# and the loaders use one content once, whatever it is called. Mirrors d3d9cache.h.
#
# NB this is FNV-1a with the STANDARD offset basis 0xcbf29ce484222325. The shader and
# key hashes INSIDE a file use the ASI's pipelinekeys::Fnv1a, whose basis is
# 1469598103934665603 (the standard one with its last digit lost). Do not mix them up.

def content_hash(data):
    h = 0xcbf29ce484222325
    for b in data:
        h = ((h ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def content_name(data):
    return "FusionFix.%016x.bin" % content_hash(data)


def write_named(directory, c):
    """Write `c` into `directory` under its content name, through a temp file and a
    rename. A file of that name already holds these exact bytes and is left alone.
    Returns (path, size)."""
    data = encode(c)
    path = os.path.join(directory, content_name(data))
    if not os.path.exists(path):
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    return path, len(data)


def write_to(out, c):
    """write() to a file path, or write_named() when `out` is an existing directory
    (e.g. a PC's plugins\\d3d9cache\\). Returns (path, size)."""
    if os.path.isdir(out):
        return write_named(out, c)
    return out, write(out, c)


def identity(c, r):
    """What makes two records the same key across files: every field except the
    count/firstFrame tail, with the file-local declIndex replaced by the
    declaration's own bytes (the same rule the capture's merge uses)."""
    d = r[I_DECL]
    decl = c.decls[d] if d != DECL_NONE and d < len(c.decls) else b""
    return (tuple(r[:I_DECL]), decl, tuple(r[I_DECL + 1:-2]))


def instanced(r):
    return any(r[I_STREAMS:I_STREAMS + MAX_STREAMS])


# ---- the replay's identity, mirrored ------------------------------------------
#
# These two functions MUST match ReplayBaseKey / ReplayPipelineKey in
# shaderprecompile.ixx: they decide what the replay warms, so a coverage number
# computed with any other identity is a number about something else. (Using the
# capture's strict record instead counts ~9300 "pipelines" where DXVK builds ~660.)
# The one deliberate difference: the declaration is compared by its BYTES, because
# declIndex is file-local and these tools compare across files.

D3DRS = {                     # D3DRENDERSTATETYPE values (d3d9types.h)
    "ALPHATESTENABLE": 15, "SRCBLEND": 19, "DESTBLEND": 20, "ALPHAFUNC": 25,
    "ALPHABLENDENABLE": 27, "FOGENABLE": 28, "SPECULARENABLE": 29,
    "FOGTABLEMODE": 35, "CLIPPLANEENABLE": 152, "POINTSPRITEENABLE": 156,
    "POINTSCALEENABLE": 157, "FOGVERTEXMODE": 140,
    "SHADEMODE": 9, "FILLMODE": 8, "MULTISAMPLEANTIALIAS": 161, "MULTISAMPLEMASK": 162,
    "COLORWRITEENABLE": 168, "BLENDOP": 171, "COLORWRITEENABLE1": 190,
    "COLORWRITEENABLE2": 191, "COLORWRITEENABLE3": 192,
    "SEPARATEALPHABLENDENABLE": 206, "SRCBLENDALPHA": 207, "DESTBLENDALPHA": 208,
    "BLENDOPALPHA": 209,
}
MAX_RT, PS_SAMPLERS, VS_SAMPLERS = 4, 16, 4
_WRITE = ("COLORWRITEENABLE", "COLORWRITEENABLE1", "COLORWRITEENABLE2", "COLORWRITEENABLE3")


def sampler_use(code):
    """[16] bools: which sampler slots an SM3 shader DECLARES (dcl_* s#).

    Mirrors ParseShaderIO in shaderprecompile.ixx, for BOTH stages. DXVK builds one
    nullOrUnusedMask from the pixel and vertex shaders' declarations together
    (d3d9_device.cpp:7384,7466) and feeds it to setPsSamplers/setVsSamplers, so the
    recorded type of an undeclared slot is leftover device state that changes no
    pipeline: the replay masks it out and so must we. A vertex shader's s0..s3 are
    D3DVERTEXTEXTURESAMPLER0..3, i.e. KeyRecord.samplerType[16..19].

    Returns None below SM2, where the instruction-length field does not exist and
    the walk would desynchronise. The ASI does the same: a missing mask leaves the
    key unmasked, which over-counts, while a WRONG mask merges two pipelines into
    one key, which under-warms."""
    dw = struct.unpack("<%dI" % (len(code) // 4), code[:len(code) // 4 * 4])
    if not dw or ((dw[0] >> 8) & 0xFF) < 2:
        return None
    slots = [False] * PS_SAMPLERS
    i = 1                                   # skip the version token
    while i < len(dw):
        tok = dw[i]
        op = tok & 0xFFFF
        if op == 0xFFFF:                    # END
            break
        if op == 0xFFFE:                    # comment block: skip its payload
            i += 1 + ((tok >> 16) & 0x7FFF)
            continue
        if op == 0x001F and i + 2 < len(dw):            # DCL: dcl token + dest token
            dst = dw[i + 2]
            regtype = ((dst >> 28) & 0x7) | ((dst >> 8) & 0x18)
            regnum = dst & 0x7FF
            if regtype == 10 and regnum < PS_SAMPLERS:  # D3DSPR_SAMPLER
                slots[regnum] = True
        i += 1 + ((tok >> 24) & 0x0F)       # instruction length field
    return slots


ps_sampler_use = sampler_use      # the name this was called before it covered both stages


def bool_mask(code):
    """Which b# registers an SM2/SM3 shader READS, or None below SM2.

    Mirrors the second half of ParseShaderIO, which mirrors DXVK's own analysis
    (d3d9_shader_analysis.cpp:127): every source operand whose register type is
    CONSTBOOL. The device ANDs its 16 bool constants with this before they reach
    the spec constant, so without it the recorded b# would split keys on registers
    the bound shader never looks at. def/defi/defb are stepped over whole -- their
    operands are raw data, and scanning them would invent b# out of constants."""
    dw = struct.unpack("<%dI" % (len(code) // 4), code[:len(code) // 4 * 4])
    if not dw or ((dw[0] >> 8) & 0xFF) < 2:
        return None
    mask = 0
    i = 1
    while i < len(dw):
        tok = dw[i]
        op = tok & 0xFFFF
        if op == 0xFFFF:
            break
        if op == 0xFFFE:
            i += 1 + ((tok >> 16) & 0x7FFF)
            continue
        n = (tok >> 24) & 0x0F
        if op not in (0x001F, 0x0051, 0x0052, 0x0053):   # not dcl / def / defi / defb
            for a in range(1, n + 1):
                if i + a >= len(dw):
                    break
                p = dw[i + a]
                if not (p & 0x80000000):
                    continue
                if (((p >> 28) & 0x7) | ((p >> 8) & 0x18)) != 14:   # D3DSPR_CONSTBOOL
                    continue
                reg = p & 0x7FF
                if reg < 16:
                    mask |= 1 << reg
        i += 1 + n
    return mask


def bool_mask_table(containers, extra=None):
    """hash -> b# mask, from whatever bytecode is visible. Same population and the
    same "absent means unmasked" rule as sampler_use_table."""
    out = {}
    for c in containers:
        for h, (_stage, code) in c.shaders.items():
            m = bool_mask(code)
            if m is not None:
                out.setdefault(h, m)
    for h, (_stage, code) in (extra or {}).items():
        m = bool_mask(code)
        if m is not None:
            out.setdefault(h, m)
    return out


def sampler_use_table(containers, extra=None):
    """(ps_use, vs_use): hash -> declared slots, from bytecode we can see.

    The ASI masks EVERY shader it holds bytecode for -- RAGE's .fxc database, the
    engine's own shader objects (GetFunction), the runtime registry, the cache's
    stored bytecode and FusionFix's own resources (shaderprecompile.ixx, each
    NoteSamplerUse call) -- and a container stores the bytecode of every shader its
    keys name that the install cannot supply.

    So for PIXEL shaders parsing the containers reproduces the ASI. For VERTEX
    shaders it does NOT: nearly every vertex shader a key names is RAGE's own, whose
    bytecode lives in the .fxc files and is deliberately not carried in the container.
    Pass `extra` -- {hash: (stage, code)} from an .fxc dump -- to close that gap;
    without it the vertex slots stay unmasked for those shaders and the key count
    comes out ABOVE what the ASI reports."""
    ps, vs = {}, {}

    def note(h, stage, code):
        slots = sampler_use(code)
        if slots is not None:
            (ps if stage == 1 else vs).setdefault(h, slots)

    for c in containers:
        for h, (stage, code) in c.shaders.items():
            note(h, stage, code)
    for h, (stage, code) in (extra or {}).items():
        note(h, stage, code)
    return ps, vs


def replay_base_key(c, r):
    """ReplayBaseKey: shaders, vertex input (incl. instancing), output/blend state,
    and the rasterizer/multisample words DxvkGraphicsPipelineStateInfo bakes.

    D3DRS_MULTISAMPLEANTIALIAS is two cache ENTRIES and one compile, which is why
    it is not in here. BindRasterizerState maps it to DxvkRsInfo's sampleCount 0 or
    1 and DxvkGraphicsPipelineStateInfo is compared as bytes, so DXVK does make two
    entries -- but the VkPipeline is looked up by a fast-instance key that carries
    no rs.sampleCount, and the word only reaches msInfo when state.ms.sampleCount()
    is zero (dxvk_graphics.cpp:356), which comes from the framebuffer and so is
    never zero for a D3D9 render pass. Cull mode and front face ARE dynamic and
    stay out."""
    rs = lambda name: r[c.rs_index(D3DRS[name])]
    rts = r[6:6 + MAX_RT]
    write = tuple((rs(_WRITE[i]) & 0xF) if rts[i] else 0 for i in range(MAX_RT))
    blend = (0, 0, 0, 0, 0, 0, 0)
    if any(write) and rs("ALPHABLENDENABLE"):
        color = (rs("SRCBLEND"), rs("DESTBLEND"), rs("BLENDOP"))
        alpha = ((rs("SRCBLENDALPHA"), rs("DESTBLENDALPHA"), rs("BLENDOPALPHA"))
                 if rs("SEPARATEALPHABLENDENABLE") else color)
        blend = (1,) + color + alpha
    d = r[I_DECL]
    decl = c.decls[d] if d != DECL_NONE and d < len(c.decls) else b""
    # D3DRS_MULTISAMPLEANTIALIAS is deliberately NOT here, and the ASI leaves it
    # out too (PrecompileKeySampleCount = 0). Measured, same binary and same gate:
    # keying on it draws 1188 pipelines instead of 1093 and the driver compiles the
    # same 786 either way -- our 786 counts vkCreateGraphicsPipelines calls, and by
    # the docstring above the two values cannot reach the Vulkan create-info. It
    # costs 95 draws and saves 95 of DXVK's own cache entries; neither is a compile.
    raster = (rs("SHADEMODE") == 1,                         # D3DSHADE_FLAT
              rs("FILLMODE"),
              # DXVK forces 0xffff unless RT0 is multisampled above NONMASKABLE.
              (rs("MULTISAMPLEMASK") & 0xFFFF) if r[11] > 1 else 0xFFFF)
    return (r[I_VS], r[I_PS], decl, r[3], r[4],             # vs, ps, decl, fvf, prim
            tuple(r[I_STREAMS:I_STREAMS + MAX_STREAMS]),
            tuple(rts), r[10], r[11], r[12],                # ds, msType, msQuality
            write, blend, raster)


def replay_key(c, r, use, bools=None):
    """ReplayPipelineKey: the base plus ALL of D3D9SpecData's device inputs.

    `use` is the (ps_use, vs_use) pair sampler_use_table returns; `bools` is
    bool_mask_table's hash -> b# mask. Each stage's sampler slots (and their modes)
    are masked to what that stage's shader declares, and the b# to what it reads; a
    shader we cannot resolve keeps its value as recorded, which over-counts rather
    than under-warms -- the same choice the ASI makes.

    Note what is NOT in here: the clip-plane ENABLE mask. DXVK specialises on the
    clip-plane COUNT (enabled AND non-zero), so that is the field, and it comes
    from the record. Fog modes, point mode, specular, the projected mask and the
    fixed-function stages are only in the key where DXVK evaluates them at all."""
    ps_use, vs_use = use
    bools = bools or {}
    rs = lambda name: r[c.rs_index(D3DRS[name])]
    pu = ps_use.get(r[I_PS])
    vu = vs_use.get(r[I_VS])
    samplers = r[13 + NUM_RS:13 + NUM_RS + NUM_SAMPLERS]
    modes = r[I_SAMPLERMODE:I_SAMPLERMODE + NUM_SAMPLERS]
    used = [(pu is None or pu[i]) for i in range(PS_SAMPLERS)] + \
           [(vu is None or vu[j]) for j in range(VS_SAMPLERS)]
    masked = tuple(t if used[i] else 0 for i, t in enumerate(samplers))
    masked_modes = tuple(m if (used[i] and samplers[i]) else 0 for i, m in enumerate(modes))
    # samplerProjMask is `projected & bound & declared`, and only stages 0..7.
    proj = 0
    for i in range(FF_STAGES):
        if used[i] and samplers[i] and (r[I_PROJMASK] >> i) & 1:
            proj |= 1 << i

    fog = rs("FOGENABLE")
    fog_modes = (rs("FOGVERTEXMODE"), rs("FOGTABLEMODE")) if fog else (0, 0)
    point = ((bool(rs("POINTSPRITEENABLE")), bool(not r[I_VS] and rs("POINTSCALEENABLE")))
             if r[4] == 1 else (False, False))          # D3DPT_POINTLIST
    ff = (canonical_ff_stages(r[I_FFSTAGE:I_FFSTAGE + 9 * FF_STAGES])
          if not r[I_PS] else ())

    def mask_bools(h, bits):
        if not h:
            return 0
        m = bools.get(h)
        return bits if m is None else bits & m

    return (replay_base_key(c, r), rs("ALPHATESTENABLE"), rs("ALPHAFUNC"),
            fog, r[I_CLIPCOUNT], masked,
            fog_modes, point, bool(rs("SPECULARENABLE")), proj,
            mask_bools(r[I_VS], r[I_VSBOOLS]), mask_bools(r[I_PS], r[I_PSBOOLS]),
            masked_modes, ff)


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

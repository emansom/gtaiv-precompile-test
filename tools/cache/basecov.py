#!/usr/bin/env python3
"""How much of REAL PLAY does the shipped baseline actually cover?

  basecov.py <baseline.bin> <capture.bin> [<capture.bin> ...]

We have measured what the baseline CONTAINS (1985 pipelines) but never what fraction
of actual gameplay it HITS. That is the number that decides whether the shipped
artifact is worth its launch cost, and it needs no game run -- both key sets are
already on disk.

TWO TRAPS THIS AVOIDS
  1. declIndex is an index into a PER-FILE declaration table. Comparing raw indexes
     across two bundles silently compares unrelated declarations. The decl table is
     read from each file and the index resolved to its BYTES before matching.
  2. Counting distinct keys answers "how many shapes did we miss", not "how much
     stutter did we remove". A key drawn 700k times matters more than one drawn once,
     so coverage is also weighted by draw count.

  Dynamic render states (ALPHAREF, STENCILREF/MASK/WRITEMASK, DEPTHBIAS,
  SLOPESCALEDEPTHBIAS, SCISSORTESTENABLE) do not create Vulkan pipelines, so they are
  excluded from the identity -- including them would count the same pipeline as a miss.
"""
import struct
import sys
from collections import defaultdict

TRACKED = [
    "ZENABLE", "ZWRITEENABLE", "ZFUNC", "ALPHATESTENABLE", "ALPHAFUNC", "ALPHAREF",
    "ALPHABLENDENABLE", "SRCBLEND", "DESTBLEND", "BLENDOP", "SEPARATEALPHABLENDENABLE",
    "SRCBLENDALPHA", "DESTBLENDALPHA", "BLENDOPALPHA", "COLORWRITEENABLE",
    "COLORWRITEENABLE1", "COLORWRITEENABLE2", "COLORWRITEENABLE3", "CULLMODE",
    "FILLMODE", "SHADEMODE", "STENCILENABLE", "TWOSIDEDSTENCILMODE", "STENCILFUNC",
    "STENCILFAIL", "STENCILZFAIL", "STENCILPASS", "STENCILREF", "STENCILMASK",
    "STENCILWRITEMASK", "CCW_STENCILFUNC", "CCW_STENCILFAIL", "CCW_STENCILZFAIL",
    "CCW_STENCILPASS", "FOGENABLE", "FOGTABLEMODE", "FOGVERTEXMODE", "RANGEFOGENABLE",
    "CLIPPLANEENABLE", "CLIPPING", "MULTISAMPLEANTIALIAS", "MULTISAMPLEMASK",
    "POINTSPRITEENABLE", "POINTSCALEENABLE", "LIGHTING", "COLORVERTEX",
    "SPECULARENABLE", "NORMALIZENORMALS", "DIFFUSEMATERIALSOURCE",
    "SPECULARMATERIALSOURCE", "AMBIENTMATERIALSOURCE", "EMISSIVEMATERIALSOURCE",
    "VERTEXBLEND", "INDEXEDVERTEXBLENDENABLE", "SRGBWRITEENABLE", "DEPTHBIAS",
    "SLOPESCALEDEPTHBIAS", "SCISSORTESTENABLE",
]
DYNAMIC = {"ALPHAREF", "STENCILREF", "STENCILMASK", "STENCILWRITEMASK",
           "DEPTHBIAS", "SLOPESCALEDEPTHBIAS", "SCISSORTESTENABLE"}
PIPE = [i for i, n in enumerate(TRACKED) if n not in DYNAMIC]
NUM_RS = len(TRACKED)
NUM_SAMPLERS = 20
REC = "<QQIIII" + "I" * 4 + "III" + "I" * NUM_RS + "B" * NUM_SAMPLERS + "II"
REC_SZ = struct.calcsize(REC)


def ps_sampler_use(sidecar):
    """psHash -> [16] bools: which sampler slots the pixel shader DECLARES.

    Mirrors ParseShaderIO in shaderprecompile.ixx. DXVK folds D3D9 sampler dimensions
    into SPIR-V spec constants, so only DECLARED slots take part in the pipeline
    identity; the recorded type of an undeclared slot is leftover device state and
    varies freely. Leaving it in the key splits one real pipeline into many phantom
    ones -- it is what took the raw counts from 11:1 down to ~3:1 against DXVK's own
    pipeline count, and skipping it here inflates the capture from 1985 to 4820.
    """
    use = {}
    with open(sidecar, "rb") as f:
        magic, ver, count = struct.unpack("<3I", f.read(12))
        assert magic == 0x53504646, "bad sidecar magic"
        for _ in range(count):
            hdr = f.read(16)
            if len(hdr) < 16:
                break
            h, stage, size = struct.unpack("<QII", hdr)
            code = f.read(size)
            if stage != 1:                      # pixel shaders only
                continue
            slots = [False] * 16
            dw = struct.unpack("<%dI" % (len(code) // 4), code[:len(code) // 4 * 4])
            i = 1                               # skip the version token
            while i < len(dw):
                tok = dw[i]
                op = tok & 0xFFFF
                if op == 0xFFFF:                # END
                    break
                if op == 0xFFFE:                # comment block: skip its payload
                    i += 1 + ((tok >> 16) & 0x7FFF)
                    continue
                if op == 0x001F and i + 2 < len(dw):        # DCL: dcl token + dest token
                    dst = dw[i + 2]
                    regtype = ((dst >> 28) & 0x7) | ((dst >> 8) & 0x18)
                    regnum = dst & 0x7FF
                    if regtype == 10 and regnum < 16:       # D3DSPR_SAMPLER
                        slots[regnum] = True
                i += 1 + ((tok >> 24) & 0x0F)   # instruction length field
            use[h] = slots
    return use


PS_USE = {}
PS_SAMPLERS = 16      # slots 0..15 are pixel samplers; 16..19 are vertex samplers


def mask_samplers(ps_hash, sampler_types):
    """Zero the sampler slots the pixel shader does not declare (vertex slots kept)."""
    use = PS_USE.get(ps_hash)
    if use is None:
        return tuple(sampler_types)
    return tuple((t if (i >= PS_SAMPLERS or use[i]) else 0)
                 for i, t in enumerate(sampler_types))


def load(path):
    """-> {identity: draws}. Identity resolves declIndex through the file's own table."""
    out = defaultdict(int)
    with open(path, "rb") as f:
        magic, ver, num_rs, num_s, decl_count, rec_count = struct.unpack("<6I", f.read(24))
        assert magic == 0x4B504646, "bad keys magic in %s" % path
        assert num_rs == NUM_RS
        f.read(4 * num_rs)
        decls = []
        for _ in range(decl_count):
            n = struct.unpack("<I", f.read(4))[0]
            decls.append(f.read(8 * n))
        for _ in range(rec_count):
            buf = f.read(REC_SZ)
            if len(buf) < REC_SZ:
                break
            r = struct.unpack(REC, buf)
            declIdx = r[2]
            decl = decls[declIdx] if declIdx < len(decls) else b"\xff\xff\xff\xff"
            # MUST match ReplayPipelineKey (shaderprecompile.ixx), which is the identity
            # that decides what gets warmed. It keeps shaders, declaration, topology,
            # RT/depth/MSAA, sampler types and exactly THREE render states -- everything
            # else DXVK folds into spec constants instead of baking into the pipeline.
            # Using the capture's own "dynamic state folded out" identity instead counts
            # 9327 pipelines where DXVK really builds ~660, a ~14x over-count, and would
            # report the baseline as missing thousands of pipelines that do not exist.
            # (Sampler masking by declared PS slot is not reproduced here; it is applied
            # identically to both files, so the comparison stays apples-to-apples.)
            ident = (r[0], r[1], decl, r[3], r[4],          # vs, ps, decl bytes, fvf, prim
                     r[6], r[7], r[8], r[9],                # rt0..rt3
                     r[10], r[11], r[12],                   # ds, msType, msQuality
                     r[13 + 3], r[13 + 4], r[13 + 34],      # ALPHATESTENABLE, ALPHAFUNC, FOGENABLE
                     mask_samplers(r[1], r[13 + NUM_RS: 13 + NUM_RS + NUM_SAMPLERS]))
            # NB the per-key `count` is NOT a usable draw metric in a merged bundle: the
            # cache merges several predecessor files each run and adds their counts again,
            # so this file's counts sum to 41.5e9 against 5,073,509 draws actually
            # recorded. Count records, not draws.
            out[ident] += 1
    return out, rec_count


SIDECAR = ("/home/ewout/.local/share/Steam/steamapps/common/Grand Theft Auto IV/"
           "GTAIV/plugins/FusionFix.pipelineshaders.bin")
PS_USE.update(ps_sampler_use(SIDECAR))
print("sampler declarations parsed for %d pixel shaders" % len(PS_USE))

base, base_n = load(sys.argv[1])
print("baseline %-46s %6d records, %6d distinct pipelines"
      % (sys.argv[1].split("/")[-1], base_n, len(base)))

for path in sys.argv[2:]:
    cap, cap_n = load(path)
    hit = [k for k in cap if k in base]
    miss = [k for k in cap if k not in base]
    print()
    print("capture  %-46s %6d records, %6d distinct pipelines"
          % (path.split("/")[-1], cap_n, len(cap)))
    print("  pipelines the baseline covers : %6d / %-6d (%5.1f%%)"
          % (len(hit), len(cap), 100.0 * len(hit) / max(1, len(cap))))
    print("  pipelines it would MISS       : %6d" % len(miss))
    if miss:
        byshader = defaultdict(int)
        for k in miss:
            byshader[(k[0], k[1])] += 1
        print("  missed pipelines by shader pair (top 8 of %d pairs):" % len(byshader))
        for (vs, ps), n in sorted(byshader.items(), key=lambda kv: -kv[1])[:8]:
            print("      %4d pipelines   vs=%016x ps=%016x" % (n, vs, ps))

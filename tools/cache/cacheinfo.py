#!/usr/bin/env python3
"""Index a FusionFix pipeline-cache container ('FFPC'). First piece of the merge tool.

  cacheinfo.py <file.bin> [<file.bin> ...]

The container is sectioned precisely so this can bucket a thousand contributions by
metadata WITHOUT parsing a thousand key tables: seek to kSecMeta, read the shader
directory, and only descend into the keys for files that belong in the same bucket.

The bucketing key is the SHADER DIRECTORY. GTA IV picks between win32_30 and five
vendor-specific variants by probing depth formats, and those directories hold
different bytecode -- so two captures that disagree here name different shaders and
must never be unioned. Under DXVK the probe is answered by DXVK rather than the
vendor driver, which is what makes a single golden cache plausible; this tool is how
that assumption gets CHECKED against real contributions instead of assumed.
"""
import struct
import sys

import ffpc

CACHE_MAGIC = 0x43504646     # 'FFPC'
SEC = {1: "meta", 2: "rsTypes", 3: "decls", 4: "keys", 5: "shaders"}
META_NAMES = ["shaderDir", "adapter", "driver", "os", "dxvk"]   # dxvk: FusionFix d8bfec0+1 on


def read_container(path):
    with open(path, "rb") as f:
        magic, version, nsec, _ = struct.unpack("<IIII", f.read(16))
        if magic != CACHE_MAGIC:
            raise ValueError("not an FFPC container (magic 0x%08x)" % magic)
        secs = []
        for _ in range(nsec):
            secs.append(struct.unpack("<IIII", f.read(16)))

        info = {"version": version, "sections": secs}
        for sid, off, size, count in secs:
            if sid != 1:
                continue
            f.seek(off)
            # CacheMeta is #pragma pack(1): nine uint32 plus one uint64 = 44 bytes.
            (numRS, numSamplers, bbFormat, msaa, frames, draws,
             backend, vendorId, deviceId, strCount) = struct.unpack("<IIIiIQIIII", f.read(44))
            info.update(numRS=numRS, numSamplers=numSamplers, bbFormat=bbFormat,
                        msaa=msaa, frames=frames, draws=draws, backend=backend,
                        vendorId=vendorId, deviceId=deviceId)
            strs = []
            for _ in range(min(strCount, 8)):
                n = struct.unpack("<I", f.read(4))[0]
                strs.append(f.read(n).decode("utf-8", "replace"))
            info["strings"] = strs
        return info


for path in sys.argv[1:]:
    try:
        i = read_container(path)
    except Exception as e:
        print("%s: %s" % (path.split("/")[-1], e))
        continue
    print("%s" % path.split("/")[-1])
    with open(path, "rb") as f:
        print("  shared as  %s" % ffpc.content_name(f.read()))
    print("  container v%d, %d sections" % (i["version"], len(i["sections"])))
    for sid, off, size, count in i["sections"]:
        print("    %-8s offset %-9d %9d bytes  %6d items"
              % (SEC.get(sid, "id%d" % sid), off, size, count))
    strs = i.get("strings", [])
    for n, v in zip(META_NAMES, strs):
        print("  %-10s %s" % (n + ":", v if v else "(empty)"))
    print("  %-10s fmt=%d msaa=%d  backend=%s  vendor=0x%04x device=0x%04x"
          % ("config:", i["bbFormat"], i["msaa"],
             "DXVK" if i["backend"] else "native D3D9", i["vendorId"], i["deviceId"]))
    print("  %-10s %d frames, %d draws" % ("captured:", i["frames"], i["draws"]))
    print()

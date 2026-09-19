#!/usr/bin/env python3
"""Read Fossilize stream archives (.foz): what is in them, who recorded them, and how
much two of them share.

  fozinfo.py <db.foz> [<db.foz> ...]                 per-tag counts + application infos
  fozinfo.py --overlap <ours.foz> <theirs.foz> [...] how much of OURS each other DB holds

Fossilize is Valve's pipeline recorder (MIT). Steam's Shader Pre-Caching downloads
crowd databases of it per game, and FusionFix records its own. A pipeline only
warms a driver cache if the exact same create-info is replayed, so "which DXVK
recorded this" and "what fraction of our pipelines does it contain" are the two
questions that decide whether a database is worth replaying (see
state/2026-09-19-linux-golden-fossilize-plan.md).

FORMAT (Fossilize fossilize_db.cpp, StreamArchive, format version 6)
  16-byte magic "\\x81FOSSILIZEDB\\0\\0\\0<version>", then entries:
    40 ASCII hex chars: 24 for the tag, 16 for the hash
    uint32 stored_size, uint32 flags (1 = raw, 2 = deflate), uint32 crc32,
    uint32 payload_size (after decompression)
    payload[stored_size]
  A truncated last entry is legal and ignored. Application info payloads are JSON.

Pipeline hashes are Fossilize's own content hashes of the create-info, so the same
hash in two databases means the same pipeline -- which is what "overlap" counts.
"""
import json
import struct
import sys
import zlib

MAGIC = b"\x81FOSSILIZEDB"
TAGS = ["applicationInfo", "sampler", "descriptorSetLayout", "pipelineLayout",
        "shaderModule", "renderPass", "graphicsPipeline", "computePipeline",
        "applicationBlobLink", "raytracingPipeline", "bucketInfo"]


def entries(path, want_payload=lambda tag: False):
    """Yield (tag, hash, payload-or-None). Payloads are only read when asked for."""
    with open(path, "rb") as f:
        head = f.read(16)
        if not head.startswith(MAGIC):
            raise ValueError("%s: not a Fossilize stream archive" % path)
        while True:
            name = f.read(40)
            hdr = f.read(16)
            if len(name) < 40 or len(hdr) < 16:
                return
            tag, h = int(name[:24], 16), int(name[24:], 16)
            stored, flags, _crc, size = struct.unpack("<4I", hdr)
            if want_payload(tag):
                data = f.read(stored)
                if len(data) < stored:
                    return
                if flags == 2:
                    try:
                        data = zlib.decompress(data)
                    except zlib.error:
                        data = zlib.decompress(data, -15)
                yield tag, h, data
            else:
                pos = f.tell()
                f.seek(stored, 1)
                if f.tell() != pos + stored:
                    return
                yield tag, h, None


def app_info(payload):
    try:
        j = json.loads(payload)
    except ValueError:
        return None
    a = j.get("applicationInfo", j)
    ver = a.get("engineVersion", 0)
    return "%s (app v%s) / engine %s %d.%d.%d / api %d.%d" % (
        a.get("applicationName"), a.get("applicationVersion"), a.get("engineName"),
        (ver >> 22) & 0x7F, (ver >> 12) & 0x3FF, ver & 0xFFF,
        (a.get("apiVersion", 0) >> 22) & 0x7F, (a.get("apiVersion", 0) >> 12) & 0x3FF)


def summary(path):
    counts = {}
    apps = []
    for tag, h, data in entries(path, want_payload=lambda t: t == 0):
        counts[tag] = counts.get(tag, 0) + 1
        if tag == 0 and data is not None:
            apps.append(app_info(data))
    print(path)
    print("  " + ", ".join("%s %d" % (TAGS[t] if t < len(TAGS) else "tag%d" % t, n)
                           for t, n in sorted(counts.items())))
    for a in sorted(set(x for x in apps if x)):
        print("  recorded by: %s  (x%d)" % (a, apps.count(a)))


def hashes(path, tags=(4, 6, 7)):
    out = {t: set() for t in tags}
    for tag, h, _ in entries(path):
        if tag in out:
            out[tag].add(h)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "--overlap":
        ours = hashes(args[1])
        print("ours: %s -- %s" % (args[1], ", ".join(
            "%s %d" % (TAGS[t], len(s)) for t, s in ours.items())))
        for other in args[2:]:
            theirs = hashes(other)
            print("  in %s:" % other)
            for t, s in ours.items():
                if s:
                    both = len(s & theirs[t])
                    print("    %-16s %6d / %-6d (%5.1f%%)" % (TAGS[t], both, len(s), 100.0 * both / len(s)))
    else:
        for p in args:
            summary(p)

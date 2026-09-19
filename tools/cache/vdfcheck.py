#!/usr/bin/env python3
"""Mirror of Find-GtaivInstall.ps1's VDF logic, run against the REAL Steam files.

PowerShell syntax cannot be executed here, but the parsing is the part that can be
wrong in a way nobody notices (a regex that works on one VDF dialect and silently
returns nothing on another). Steam's VDF format is identical on Linux and Windows,
so the algorithm can be checked on genuine data even though the host cannot.
"""
import os, re, sys

PAIR = re.compile(r'"([^"]+)"\s+"([^"]*)"')          # same expression as the .ps1

def vdf_pairs(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, errors="replace") as f:
        for line in f:
            m = PAIR.search(line)
            if m:
                out.append((m.group(1), m.group(2).replace("\\\\", "\\")))
    return out

steam_root = os.path.expanduser("~/.local/share/Steam")
libs = [steam_root]
for k, v in vdf_pairs(os.path.join(steam_root, "steamapps/libraryfolders.vdf")):
    is_path = (k == "path") or (k.isdigit() and (re.match(r'^[A-Za-z]:\\', v) or v.startswith("\\\\")))
    if is_path and v:
        libs.append(v)
libs = list(dict.fromkeys(libs))
print("libraries discovered: %d" % len(libs))
for l in libs:
    print("   %s" % l)

found = []
for lib in libs:
    for appid in ("12210", "12220"):
        acf = os.path.join(lib, "steamapps", "appmanifest_%s.acf" % appid)
        if not os.path.exists(acf):
            continue
        pairs = dict(vdf_pairs(acf))
        installdir = pairs.get("installdir")
        if not installdir:
            print("   appmanifest_%s.acf has no installdir!" % appid)
            continue
        root = os.path.join(lib, "steamapps", "common", installdir)
        # Resolve-ExeDir: GTAIV subfolder first, then the root.
        exedir = None
        for sub in ("GTAIV", ""):
            d = os.path.join(root, sub) if sub else root
            if os.path.exists(os.path.join(d, "GTAIV.exe")):
                exedir = d
                break
        found.append((appid, pairs.get("name"), root, exedir))

print("\nresolved:")
for appid, name, root, exedir in found:
    print("  appid %s  %s" % (appid, name))
    print("    root   : %s" % root)
    print("    exe dir: %s" % (exedir if exedir else "NOT FOUND (no GTAIV.exe)"))
sys.exit(0 if any(e for _, _, _, e in found) else 1)

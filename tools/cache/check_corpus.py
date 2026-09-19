#!/usr/bin/env python3
"""Run a make_corpus.py corpus through d3d9cache_check.exe and compare with expected.txt.

  check_corpus.py <d3d9cache_check.exe> <corpus-dir>

Runs the checker under wine on every corpus file in one go (in name order, as the
replay would, so duplicates are detected against earlier files), then checks each
verdict -- and for accepted files the dropped key/declaration/shader counts --
against expected.txt. "any" accepts every verdict: those files only have to not
crash the reader. Exit code 0 when everything matches.
"""
import os
import re
import subprocess
import sys

if len(sys.argv) != 3:
    sys.exit(__doc__)
exe, corpus = sys.argv[1], sys.argv[2]
expected = {}
for line in open(os.path.join(corpus, "expected.txt")):
    parts = line.split()
    if parts:
        name = line[:line.rindex(".bin") + 4] if ".bin" in line else parts[0]
        rest = line[len(name):].split()
        expected[name] = rest
names = sorted(expected)
env = dict(os.environ, WINEDEBUG="-all")
p = subprocess.run(["wine", exe, "check"] + [os.path.join(corpus, n) for n in names],
                   capture_output=True, text=True, env=env, timeout=600)
print(p.stdout, end="")
if p.returncode != 0:
    sys.exit("checker exited with %d (stderr: %s)" % (p.returncode, p.stderr.strip()[:500]))

got = {}
for line in p.stdout.splitlines():
    m = re.match(r"^(.*?\.(?:bin|BIN)): (accepted|rejected|duplicate|skipped|not present)\b(.*)$", line)
    if m:
        drops = re.search(r"dropped (\d+) invalid keys, (\d+) declarations, (\d+) shaders", m.group(3))
        got[m.group(1)] = (m.group(2), tuple(int(x) for x in drops.groups()) if drops else (0, 0, 0))

bad = 0
for n in names:
    want = expected[n]
    if n not in got:
        print("MISSING  %s" % n)
        bad += 1
        continue
    verdict, drops = got[n]
    ok = want[0] == "any" or want[0] == verdict
    if ok and len(want) == 4 and verdict == "accepted":
        ok = drops == tuple(int(x) for x in want[1:])
    if not ok:
        print("MISMATCH %s: expected %s, got %s %s" % (n, " ".join(want), verdict, drops))
        bad += 1
print("%d files, %d mismatches" % (len(names), bad))
sys.exit(1 if bad else 0)

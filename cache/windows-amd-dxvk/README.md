# Windows / AMD / DXVK reference capture

The capture from the first Windows session (2026-09-19, Run 1: base-game Niko,
downtown Algonquin), taken off the NTFS partition afterwards.

| file | contents |
|---|---|
| `FusionFix.pipelinecache.f21-ms0.bin` | 3667 keys, 29 decls; names 542 shaders, carries bytecode for 25; **upgraded to cache format v2** |

```
shaderDir: win32_30
adapter:   AMD Radeon RX 9070 XT
driver:    32767.65535.65535.65535   (DXVK's placeholder; the build that ran predates d1c6119)
os:        windows   backend: recorded as "native D3D9", which was wrong: it ran on DXVK
config:    fmt=21 (D3DFMT_A8R8G8B8)  msaa=0
```

## What it is and isn't

- **Upgraded, not re-captured.** The original is v1, which the current ASI refuses.
  `tools/cache/upgrade_cache_v2.py` widened each key with "no instancing", because a
  v1 capture never recorded it. The keys are otherwise exactly what Windows wrote.
- **Bytecode trimmed** to the policy the ASI now writes (`filter_cache.py
  --strip-fxc`): the game's `.fxc` shaders are named by hash only and resolved from
  whatever install replays this; only FusionFix's 25 runtime-built shaders travel as
  bytecode.
- **Unfiltered.** It still holds 47 keys naming Liberty City Plates shaders, a mod
  installed only on the Linux machine; this install has just FusionFix and Various
  Fixes. They are not Windows data: all 47 are exact copies of keys in the old
  Linux-built baseline, each drawn exactly once, which is the replay drawing them and
  capture recording it. It also holds 1 key naming this install's older
  `gta_radar.fxc` shader. The shipped baseline was built from a filtered copy; see
  `..\linux-amd-dxvk\README.md`.
- **Not a baseline.** It is this machine's own record, kept so that "what did Windows
  see" stays answerable.

## Carrying it on in the next Windows session

The new ASI moves the install's v1 file aside as `FusionFix.pipelinecache.f21-ms0.bin.unmerged`
and starts a fresh capture. To keep accumulating onto what Windows already saw instead,
copy this file into `<game>\plugins\pipelinecache\` (create the folder) before the
first launch: the replay warms it and capture merges it into the new file. Either is
fine for the experiment; say which was done.

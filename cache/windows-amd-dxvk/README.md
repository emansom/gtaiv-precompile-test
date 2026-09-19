# Windows / AMD / DXVK reference capture

The capture from the first Windows session (2026-09-19, Run 1: base-game Niko,
downtown Algonquin), taken off the NTFS partition afterwards.

| file | contents |
|---|---|
| `FusionFix.pipelinecache.f21-ms0.bin` | 3667 keys, 29 decls, 542 shaders, **upgraded to cache format v2** |

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
  v1 capture never recorded it. Everything else is byte-for-byte what Windows wrote.
- **Unfiltered.** It still holds 47 keys naming non-stock vehicle shaders (inherited
  by recording its replay of the old Linux baseline) and 1 key naming the Windows
  install's older `gta_radar.fxc` shader. The shipped baseline was built from a
  filtered copy; see `..\linux-amd-dxvk\README.md`.
- **Not a baseline.** It is this machine's own record, kept so that "what did Windows
  see" stays answerable.

## Carrying it on in the next Windows session

The new ASI moves the install's v1 file aside as `FusionFix.pipelinecache.f21-ms0.bin.unmerged`
and starts a fresh capture. To keep accumulating onto what Windows already saw instead,
copy this file into `<game>\plugins\` before the first launch. Either is fine for the
experiment; say which was done.

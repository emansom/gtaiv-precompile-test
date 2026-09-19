# Linux / AMD / DXVK reference caches

Captured on the machine this work was developed on, so a Windows run has something
real to compare against instead of starting from nothing.

| file | contents | what it is |
|---|---|---|
| `FusionFix.pipelinecache.baseline.bin` | 2350 pipelines (1 instanced), 29 decls; names 531 shaders, carries bytecode for 25 | the **shipped** baseline — what any player gets on first launch |
| `FusionFix.pipelinecache.f21-ms0.bin` | 14462 keys (4 instanced), 29 decls; names 543 shaders, carries bytecode for 25 | the full accumulated capture the baseline was distilled from |

Both are **cache format v2** (instancing recorded per key), which is the only format
the current prebuilt ASI reads. Neither carries bytecode for any game `.fxc`
shader. Those are resolved by hash from the install they are replayed on. The 25
that travel are the shaders FusionFix builds at runtime. Shared provenance:

```
shaderDir: win32_30
adapter:   AMD Radeon RX 9070 XT (RADV GFX1201)
os:        wine 11.0   backend: DXVK   vendor=0x1002 device=0x7550
config:    fmt=21 (D3DFMT_A8R8G8B8)  msaa=0
```

Run `python ..\..\tools\cache\cacheinfo.py <file>` to read that back from any
container, including one produced on Windows. The capture's `driver:` field is
`radv Mesa 26.2.3-arch1.1`. The baseline's still reads `32767.65535.65535.65535`,
the constant DXVK reports in place of a driver version: its metadata is carried over
from the capture it was first exported from, before build `d1c6119` recorded the
real driver.

### How the baseline was built (2026-09-19)

Exported by the ASI itself (`PrecompileExportBaseline = 1`), so the deduplication is
exactly the replay's own, from two raw captures upgraded to v2
(`tools/cache/upgrade_cache_v2.py`) and merged (`merge_cache.py`): this machine's
full capture and the Windows capture in `..\windows-amd-dxvk\`. It is keyed on DXVK's
base pipeline (shaders, vertex input including instancing, output/blend state) plus
the spec-constant variants, so it holds blend and write-mask variants the previous
1954-key baseline had folded away.

Then filtered (`filter_cache.py`) of keys naming shaders a stock install never
loads:
- the four vehicle effects that come from **Liberty City Plates**, installed only on
  this Linux machine (`gta_vehicle_licenseplate`, `_licenseplate_ext`, `_track`,
  `_track2`). This is where the bad keys originate. The Windows capture holds 47
  of them only because Windows replayed the old baseline built here: all 47 are exact
  copies of old-baseline keys, each drawn exactly once, i.e. by the replay itself;
- the one shader in the Windows install's older `gta_radar.fxc`.

The full capture is kept as recorded, so it still contains the vehicle keys.

### The two installs are not modded alike

| install | mods |
|---|---|
| Linux (this machine) | FusionFix, Various Fixes, **Liberty City Plates** (+ its texture pack), several texture replacement packs, map fixes |
| Windows (2026-09-19 run) | FusionFix, Various Fixes |

Only `.fxc` files change which shaders exist, and of these mods only Liberty City
Plates ships any. Texture packs and map fixes can still change *which* stock-shader
combinations get drawn. Those keys are harmless on a stock install (at worst a
pipeline that is never used), but they mean this capture is not a picture of a stock
game.

## Which one to deploy — deploy the BASELINE only

Copy `FusionFix.pipelinecache.baseline.bin` into `<game>\plugins\`. Do **not** also
copy the full capture, even though it is here.

The two warm almost exactly the same set (the baseline *is* the deduplication of that
capture, minus the non-stock keys above), so the full file buys no extra warming on a
stock install. What it
does cost is the ability to answer a question: if Windows starts from our capture and
records into it, the file that comes back is a mixture and "what did this machine see
on its own" can no longer be separated out. Starting from the baseline alone — which
is also what a real first-time player gets — leaves the Windows capture clean and
directly diffable against ours.

The full capture is here as reference: for inspecting, for diffing after the fact, and
in case a later run wants to pool deliberately rather than by accident.

## If Windows resolves a different shader directory

The capture will **refuse to merge** a cache whose `shaderDir` differs from the local
one and will say so in `FusionFix.shaders.log`:

```
<file> was captured against shader dir 'win32_30', this install uses '<other>' - not merging
```

That message is the **answer to the experiment**, not a failure to work around. It
means the golden cache has to be bucketed per shader directory. Leave the files in
place, note the line, and bring the log back — do not delete the baseline or try to
force the merge, because a forced union of two directories' keys is exactly the silent
corruption the check exists to prevent.

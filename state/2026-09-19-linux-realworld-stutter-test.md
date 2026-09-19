# Real-world stutter test on Linux: what each warming layer removes

The first end-to-end measurement of the pre-compiler on real gameplay: same route,
same recordings, one layer added at a time. It answers what the D3D9 pass, this PC's
own Fossilize recording, foreign Fossilize databases and a D3D9 file from another PC
are each worth, and what is left when everything is warm.

Build: the merged sharing work, `d3c5dc1` in the FusionFix fork (ASI sha256
`7b12f24257afba49`). Machine: Arch, KDE Plasma Wayland, RX 9070 XT (RDNA4), RADV Mesa
26.2.3, GTA IV Steam Complete Edition 1.2.0.59 under GE-Proton11, D3D9 through the
DXVK 3.1.1 FusionFix ships, **graphics pipeline libraries off**
(`dxvk.enableGraphicsPipelineLibrary = False`), Steam Shader Pre-Caching off.
13 runs, 2026-09-20 00:07-01:47.

## Method

One run = one launch driven along `lc-districts-v1` (`run/linux/routes/lc-districts.json`):
a fixed warp to Star Junction with the clock held at 13:00 and the weather at sunny,
then 9 driven legs (Algonquin → the Algonquin Bridge → Rotterdam Hill → East Hook →
the Broker Bridge → Fishmarket South → Chinatown → Lower Easton → The Triangle, about
3.4 km) and 3 on-foot steps into the Cluckin' Bell. `run/linux/gameplay_run.py` runs one
condition end to end; `run/linux/gpparse.py` turns the results into these tables.

Every run starts from the same snapshot of the player's recordings
(`/tmp/ff-tools/snapshot`), restored before and after, and has **capture off**
(`CaptureDrawKeys = 0`, `CaptureVulkanPipelines = 0`) so the recordings stay frozen for
the whole session and capture's per-draw cost does not distort the frame times. Every
run is cold — `~/.cache/mesa_shader_cache` emptied first, then checked against the
game's own environment — except the warm floor. The ini was set by hand per condition;
the runner only asserts the keys and refuses if they do not match.

| condition | `PrecompileShaders` | `ReplayVulkanPipelines` | `…Foreign` | Mesa cache | runs |
|---|---|---|---|---|---|
| C1 `off` | 0 | 0 | 0 | cold | 2 |
| C2 `d3d9` | 1 | 0 | 0 | cold | 2 |
| C3 `d3d9+vk-own` | 1 | 1 | 0 | cold | 3 |
| C4 `full` | 1 | 1 | 1 | cold | 4 |
| C6 `warm` | 1 | 1 | 1 | **warm**, straight after a C4 run | 3 |

Rounds were interleaved (C1 C2 C3 C4 C6, then again) so drift over the session cannot
be read as an effect. C3 and C4 got a third run because their first two disagreed, and
C4/C6 a fourth pair to pin the warm floor.

Run quality: 13 of 13 routes completed, 12 of 13 "clean". The one exception is
`full/run1`, where the East Hook leg ran out of time and the car was warped to its end
— one deviation, no effect on its numbers (they sit inside the spread of the other
three `full` runs). No freeze, no loss of focus, no main-thread hang inside any route,
and no fault in any log.

### C5, the other PC's D3D9 file, was not run

The plan made C5 conditional on the drop-in first being shown to add pipelines this PC
does not already warm. Offline, with `tools/cache/ffpc.py` mirroring the replay's own
identities (`ReplayBaseKey`/`ReplayPipelineKey`):

```
this PC already warms: 599 base identities, 5475 replay keys   (snapshot capture + shipped baseline)
windows drop-in:       580 base identities, 2567 replay keys
ADDED by the drop-in:  1 base identities, 59 replay keys
```

The single added base identity names pixel shader `fb2f5d541b96d0b9`, which is **not in
this install's `.fxc` database** — 2387 unique shaders across `common\shaders\win32_30`
and `update\shaders\win32_30`, dumped with `tools/cache/fxc_hashes.c` — and the file
carries no bytecode for it. It is the older `gta_radar.fxc` the Windows machine still
had. Even if it did carry bytecode, the merged build never creates a shader from a
drop-in's bytecode (review finding D1). So the drop-in can warm **zero** pipelines this
install lacks. The other 59 additions are spec-constant variants of base identities C4
already builds, which with GPL off are folded into the same pipeline. C5 would have
measured C4 a second time, so it was dropped and those runs spent on third and fourth
rounds of the conditions that do differ.

## Results

Means over the runs of each condition, range in brackets. "Compiles" are DXVK pipeline
creations of 5 ms or more, which is what the build counts as a real compile; ">50 ms
frames" are counted **inside the route window only**, so the route's own start warp is
excluded (see below).

| | C1 `off` | C2 `d3d9` | C3 `+vk-own` | C4 `full` | C6 `warm` |
|---|---|---|---|---|---|
| runs | 2 | 2 | 3 | 4 | 3 |
| **loading** | | | | | |
| launch → pass done (s) | 29.7 | 44.3 | 46.3 | 55.2 | 32.2 |
| D3D9 pass (s) | – | 17.8 | 19.5 | 28.4 | 5.4 |
| loading screen held for the Vulkan replay (s) | – | – | 0.1 | 9.4 | 1.2 |
| quiet waits (s, summed) | – | 1.0 | 2.0 | 2.0 | 2.0 |
| **replayed** | | | | | |
| D3D9 keys drawn | – | 2421 | 2421 | 2421 | 2421 |
| Fossilize entries created | – | – | 765 | 3351 | 3351 |
| of those, from other PCs' files | – | – | – | 2586 | 2586 |
| **before gameplay** | | | | | |
| pipelines DXVK created | 20 | 736 | 735 | 735 | 735 |
| of those, compiles ≥5 ms | **1** | 576 | 583 | 578 | **0** |
| **in gameplay** | | | | | |
| pipelines DXVK created | 522 | 97 | 96.7 | 94.5 | 101 |
| **compiles ≥5 ms** | **414** (402-425) | **93.5** (93-94) | **93.0** (82-105) | **27.3** (18-39) | **11.3** (1-20) |
| compiles ≥20 ms | 239 | 55.5 | 56.7 | 25.5 | 10.3 |
| worst compile (ms) | 47.1 | 46.5 | 47.1 | 43.1 | 34.8 |
| **frame times** | | | | | |
| **route frames > 50 ms** | **62.0** (56-68) | **15.0** (15-15) | **15.3** (11-19) | **6.25** (5-9) | **3.0** (1-4) |
| … per 100 s of route | 21.7 | 4.9 | 4.8 | 2.1 | 1.0 |
| worst route frame (ms) | 431 | 370 | 386 | 283 | 175 |
| session spikes | 126 | 25.5 | 27.7 | 17 | 11.7 |
| p99 (ms) | 15.6 | 15.1 | 15.0 | 15.0 | 15.0 |
| average fps | 72.9 | 74.1 | 74.2 | 74.4 | 74.4 |
| route duration (s) | 286 | 303 | 317 | 303 | 301 |

Every long frame was checked against the compile lines on the same session clock. A
creation counts as behind a frame when it started inside the frame's own span or in the
0.5 s before it:

| | C1 `off` | C2 `d3d9` | C3 `+vk-own` | C4 `full` | C6 `warm` |
|---|---|---|---|---|---|
| route frames > 50 ms | 62.0 | 15.0 | 15.3 | 6.25 | 3.0 |
| … with a DXVK creation behind them | 60.5 | 15.0 | 15.3 | 6.0 | 2.7 |
| share | 98% | 100% | 100% | 96% | 89% |

**The route's own start warp is not stutter.** The single largest frame in every run —
1.4 to 1.7 s — happens about 17 s after gameplay begins, when the route teleports the
player to Star Junction and calls `LOAD_SCENE`. It is world streaming, it lands
*outside* the route window in every run, and it is the same size in every condition
(`off` 1640 ms, `warm` 1409 ms). It is excluded from the frame counts above and is a
property of the harness, not of the game or the pre-compiler.

## Conclusion

**The D3D9 pass is the big one.** It removes **320 of the 414** gameplay compiles
(−77%) and **47 of the 62** route frames over 50 ms (−76%), for 15 s of extra loading.
Reproducibility is near-exact: 93 and 94 compiles, 15 and 15 long frames.

**This PC's own Fossilize recording adds nothing measurable on top of it**: 93.0
compiles against 93.5, 15.3 long frames against 15.0 — the difference is inside the
run-to-run spread, and the means are equal to within 0.5%. The recording replays 765
entries in 0.1 s, but those are DXVK pipelines this machine built in earlier sessions,
which is the same set the D3D9 pass rebuilds from the captured keys. It is not useless
— it is what other PCs receive — but on the machine that recorded it, it is redundant
with layer L0.

**The foreign Fossilize databases are the second real win.** Adding the player's Steam
pre-cache buckets (2586 entries created) removes a further **66 of the remaining 93**
compiles (−71%) and **9 of the 15** route long frames (−59%), for another 9 s of
loading. From nothing warmed to the full default: **414 → 27 compiles (−93%)** and
**62 → 6.25 route frames over 50 ms (−90%)**.

**The other PC's D3D9 file is worth nothing here** — 1 added base identity, naming a
pixel shader this install does not have, so 0 warmable pipelines. Measured offline, not
run. That is a statement about *these two installs* (they differ by mods and by a
`gta_radar.fxc` revision), not about drop-ins in general.

**What is left, and what it is.** The mechanism is visible in the "before gameplay"
rows. Warming does not stop DXVK creating pipelines during play: it creates about the
same **~95-100** of them in every warmed condition. What warming changes is where the
*driver* compile is paid. Cold with only the D3D9 pass, 93.5 of those ~97 creations are
real compiles, because Mesa has never seen them; with the foreign databases replayed,
only 27 of ~95 are, because the replay put the rest in Mesa's cache; and on a warm
cache, 11 of ~101. The loading screen shows the same thing from the other side: `off`
compiles 1 pipeline before gameplay, every warmed cold condition compiles about 578,
and a warm run compiles **0** of the 735 it creates.

So the residue is genuinely new pipeline state — ambient traffic, pedestrian and prop
variety that neither the 599 captured base identities nor the Steam buckets contain.
Even warm, **3 frames over 50 ms per ~300 s route remain, and 2.7 of them still have a
DXVK compile behind them** (worst 175 ms). This is not a driver-cache problem and no
amount of replaying what we already have will fix it: those pipelines are not in any
recording. Closing it needs either broader coverage (keys harvested from more play, or
walked statically out of the `.fxc` database — 2387 shaders, against the 599 identities
the current corpus reaches) or GPL fast-linking, which this rig has switched off.

Average fps is flat at 74.1-74.4 across every warmed condition and 72.9 with nothing
warmed, and p99 barely moves (15.6 → 15.0 ms): the cost of this stutter is entirely in
the tail, which is exactly what the > 50 ms counts measure.

**Loading cost.** The full default adds **25.5 s** to a cold first launch (29.7 → 55.2 s)
and **2.5 s** once the driver cache is warm (29.7 → 32.2 s). The quiet waits that were
added with the load-order work cost 2.0 s of that and always reported "quiet" — DXVK
had genuinely finished before the loading screen was released, in all 12 runs that had
a pass. No wait ever ended in "NOT quiet, gave up".

## Rig notes

- `run/linux/conditions.json` and `gpparse.py` were corrected for the merged build in
  `464214f`: the Vulkan side now stages its shared copy as
  `plugins\FusionFix.pipelinecache.tmp`, which the runner has to clean too, and the new
  "created by DXVK on later loading screens" counter is parsed. That counter read 0 in
  all 13 runs — no loading screen returned during any of them, so it is carried but
  untested here.
- From `d3c5dc1` vkcapture hooks `vkGetInstanceProcAddr` whatever the ini says, which is
  what makes C1 measurable at all. On `141a876` the baseline had no frame times.
- The East Hook leg timed out once in 13 runs. If it recurs, its time budget is the
  thing to loosen, not the route.
- Results are in `/tmp/ff-results/<condition>/run<N>/` (tmpfs — copy anything worth
  keeping).

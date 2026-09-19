# Plan: golden Fossilize databases, and Steam's crowd database as a base

Agreed with the owner 2026-09-19. **Nothing here is built yet.** Background:
`re/shader-precompile/zero-stutter-research.md` on the Linux machine (§4.2–4.4).

## Why a Vulkan layer at all

The D3D9 replay (the FFPC cache) is portable: every machine's own DXVK turns the same
D3D9 keys into its own Vulkan state. What it cannot reach is anything below D3D9.
That means DXVK's internal pipelines, exact spec constants, and whatever the driver
does on first use. The ~2 s Windows stall appears only with a cold *driver* cache, so
that layer matters.

The design is two layers:

| layer | contents | portable across | when it runs |
|---|---|---|---|
| **L0** | FFPC D3D9 keys (today's cache) | vendors, drivers, OSes | load screen |
| **L1** | Fossilize database: DXVK's actual Vulkan pipelines | one **bucket** only (below) | background, during intro and menus |

L1 warms the driver cache in parallel. L0 then builds DXVK's own objects, mostly
against a warm driver cache.

## Golden Fossilize databases, one per bucket

A Fossilize database holds exact Vulkan create-infos and SPIR-V: API-level data, **not
GPU machine code**. The driver compiles it for whatever GPU replays it, so the GPU's
instruction set ("dialect") matters only to the driver's own cache, never to the
database. What a database is tied to is **what DXVK emits**: it warms a cache only if
DXVK would request byte-identical state. The bucket key is therefore what changes
DXVK's output:

| part | why | recorded today? |
|---|---|---|
| **DXVK build** | SPIR-V, layouts and spec constants change between DXVK releases (though much survives: see the measurement below) | yes, since FusionFix `d2211b5`: `d3d9.dll 7856142 fnv:4e9cdaec8067db9f` |
| driver + driver version | DXVK picks features and a few behaviours per driver; features change with driver releases | yes, since `d1c6119`: `VkPhysicalDeviceDriverProperties`, e.g. `radv Mesa 26.2.3-arch1.1` |
| the Vulkan feature set DXVK sees | descriptor heap vs legacy binding, GPL, robustness, shader features: all change the SPIR-V/state | the recording itself carries it (Fossilize stores the enabled features) |
| GPU vendor + model | **only through the feature set**: cards of one family on one driver expose the same features, so they share a bucket | recorded (`vendorId`/`deviceId`), but not a bucket key on its own |
| OS | recorded, but whether it must split buckets is **not known** | yes: `windows` / `wine <ver>` |

**Measured 2026-09-19:** Steam's DXVK 3.x bucket, recorded by other players on GPUs
we cannot see and with DXVK 3.0.0–3.1.0, already holds **85.8%** of the graphics
pipelines FusionFix's DXVK 3.1.1 built on this RX 9070 XT (RADV), 98.9% of its
shader modules and all 8 of its internal compute pipelines. The main crowd
database, mostly DXVK 1.x–2.x, holds 0.3%. So the partition that matters is DXVK
generation + feature set, not the GPU model.

In practice the driver mostly implies the OS (RADV is Linux-only). Whether the same
driver under Wine and native Windows yields identical DXVK output is a measurement,
not an assumption.

Merging within a bucket uses Fossilize's own `fossilize-merge-db`. `tools/cache/merge_cache.py`
is the FFPC counterpart. A wrong bucket costs compile time; it never breaks
rendering, because replay only creates pipelines.

**To confirm the bucketing:**
- record the same route on two machines of one bucket and on two different buckets;
- compare pipeline hashes (`fossilize-list`);
- high overlap within a bucket and low overlap across buckets means the key is right.

**Provenance:** done in FusionFix `d2211b5` (DXVK module hash in the FFPC meta). The
recorder itself is in `vkcapture.ixx` (in-process, `CaptureVulkanPipelines = 1`): it
wraps DXVK's Vulkan calls and writes `plugins\FusionFix.vkpipelines.foz`. First run:
730 graphics + 8 compute pipelines, 562 shader modules, all tagged DXVK 3.1.1.

## Steam's Linux crowd database as a base

**What is on record** (Linux `~/.local/share/Steam/logs/shader_log*.txt`, VERIFIED):
- Steam downloaded a crowd Fossilize database for app 12210 and kept **2 buckets**,
  `923fa87291dfec1c` and `049c3679665037db`, for compatibility tool
  **`ge-proton11-stock`**. The Steam log reads
  `Found 2 buckets for AppId 12210 CompatTool: ge-proton11-stock`.
- It launched the game with `MESA_DISK_CACHE_READ_ONLY_FOZ_DBS=…steam_precompiled…`,
  i.e. read-only Mesa caches pre-built from it.
- The files were removed on 2026-09-17 when the owner disabled Shader Pre-Caching for
  testing.

**The condition:** the crowd database was produced by the DXVK that **GE-Proton 11
bundles**. FusionFix always loads its own DXVK, the latest release (3.1.1 today). The
crowd database is reusable only as far as the two produce the same pipelines on the
same driver.

**The test:**
1. Re-enable Shader Pre-Caching for 12210 and let Steam re-download. Note the bucket
   IDs, paths and sizes.
2. Record our own database of a normal run with FusionFix's DXVK. Steam's Fossilize
   layer already records the running game locally
   (`fozpipelinesv6/steamapprun_pipeline_cache.<bucket>/`). If that turns out not to
   apply to a game-dir DXVK, use `VK_LAYER_fossilize` with `FOSSILIZE_DUMP_PATH`.
3. Read the `VkApplicationInfo` in both (engine name and version) to see which DXVK
   each came from.
4. Compare pipeline and shader-module hashes: our set ∩ crowd set.
5. Decide: high overlap means the crowd database is a usable base for the Linux/RADV
   bucket. Low overlap means it is not, and each run is still recorded locally anyway.

**Result (2026-09-19, RX 9070 XT, RADV Mesa 26.2.3, DXVK 3.1.1, GE-Proton 11).**
`tools/cache/fozinfo.py` reads the databases.
- Steam downloaded three databases:
  - the main crowd database, 1.85 GB, 280k graphics pipelines, recorded by GTA IV
    players across DXVK 1.7 → 3.1.1 plus NvRemix, a DXVK-HDR build, HappinessMP and
    the Rockstar launcher's vkd3d;
  - bucket `923fa87291dfec1c`, 76 MB, 19k pipelines, DXVK 3.0.0–3.1.0;
  - bucket `049c…`, vkd3d from the launcher and Social Club.
- Steam's layer turned out to record only pipelines **absent** from its read-only
  databases (104 of our run's pipelines, 1 of them in the main database). So our own
  full recording was needed, from the new in-process recorder: 730 graphics
  pipelines.

| crowd database | our graphics pipelines it holds | shader modules | compute |
|---|---:|---:|---:|
| main (1.85 GB, DXVK 1.7–3.1.1) | 2 / 730 (0.3%) | 2.3% | 0% |
| bucket `923fa87291dfec1c` (DXVK 3.0–3.1.0) | **626 / 730 (85.8%)** | 98.9% | 100% |
| Steam's local recording of our run | 104 / 730 (14.2%) | 1.1% | 0% |

626 + 104 = 730: the bucket plus Steam's "new" recording is exactly our set, which
cross-checks the recorder. **Verdict: the right Steam bucket is a strong local base
(~86%) for the Linux/RADV DXVK-3 bucket; the main crowd database is not.**

Tools: `fossilize-list`, `fossilize-convert-db` and `fossilize-merge-db` were built in
`/run/user/1000/zs/fz-build/cli/` for the research. That is tmpfs, so rebuild from
ValveSoftware/Fossilize after a reboot.

## The replay side (L1), built and measured

FusionFix `898c762` + `69e37df`, `ReplayVulkanPipelines = 1`. From the moment DXVK
creates its device, lowest-priority workers replay this PC's own
`FusionFix.vkpipelines.foz` on that device and destroy each pipeline as soon as it
exists; the point is the driver cache.

**It has to run in the game's process, and in its bitness.** RADV's
`pipelineCacheUUID` differs by ABI on this machine: 64-bit `fa708dc4…`, 32-bit
`590ac868…`. Steam's Mesa cache folder has one directory per UUID. Steam's own
pre-cache replay runs 64-bit `fossilize_replay` and filled **257 MB** of 64-bit
cache that 32-bit GTA IV never reads; the game's 32-bit directory held 3.9 MB,
all compiled by the game itself. **So Steam's Shader Pre-Caching buys 32-bit GTA
IV on Linux essentially nothing**, and a 64-bit helper process would repeat that.
In-process also hits on drivers that key their cache per application.

**Measured, cold 32-bit cache** (GTA IV's own Mesa cache directory cleared, nothing
else changed), loading-screen D3D9 warm-up:

| | L1 replay | warm-up |
|---|---|---:|
| L1 off | — | 18.0 s |
| L1 on, 1 thread | 765 pipelines in 9.7 s | 8.7 s |
| L1 on, 3 threads | 765 pipelines in 4.9 s | 4.6 s |
| warm cache, for reference | — | ~2.0 s |

**Foreign databases: the crash was our bug, fixed in FusionFix `73156da`.**
Replaying Steam's DXVK-3 bucket in-process used to kill the game at entry
`2e5a4038eefd9e7b`. The earlier reading, a driver fault on foreign data followed by
a crash in Social Club's exception handler, was wrong. What happened:
1. Our relevance check rejected two shader modules. They declare
   `SignedZeroInfNanPreserve`; DXVK 3.0/3.1.0 emits that, 3.1.1 uses
   `FloatControls2` instead.
2. Fossilize's replayer puts a module's hash in its handle map *before* asking us to
   create it, so each rejected module stayed there as `VK_NULL_HANDLE`.
3. A later pipeline in the same batch got both stages as null handles, and we created
   it anyway. Fossilize's own `fossilize-replay` refuses such a pipeline; ours did not.
4. RADV read the missing vertex shader (`radv_pipeline_init_vertex_input_state`,
   32-bit `libvulkan_radeon.so +0x151603`).
5. Under Wine that fault stays on the Unix side. winevulkan answers with
   `ExitProcess(3)`, and Social Club crashed while unloading on the way out.

Reproduced outside the game with Fossilize's replayer in native 64-bit, native
32-bit, and 32-bit Windows under GE-Proton11's wine.

Steam's replay never met this, because Fossilize's replayer filtered the entry: it
renders to D24S8, a depth format RDNA4 doesn't support. Over the whole bucket Steam's
replayer had 3205 "not supported", 562 "invalid create info" (its null-handle guard)
and 0 crashes.

Every replayed object now passes three checks:
- **relevant:** the existing check against what DXVK used on this device;
- **supported:** Fossilize's real feature filter (`cli/fossilize_feature_filter.cpp`),
  set up from DXVK's actual device;
- **complete:** no null module or library, and no derivative without a base.

With `ReplayVulkanPipelinesForeign = 1` over all 4 foreign inputs on Linux/RADV,
three runs came out identical, with no crash:

| foreign entries | count |
|---|---|
| created | 2586 |
| not relevant | 15596 |
| not supported (D24S8) | 496 |
| incomplete | 116 |
| failed | 0 |

The foreign pass runs after the own replay, on one lowest-priority thread. It took
46.6 s the first time and ~3 s once cached, and the loading-screen pass is unchanged.
Foreign replay is still off by default. No out-of-process helper is needed.

**Cross-platform / cross-vendor, in short:** a `.foz` can be read anywhere. A
pipeline in it is safe to replay only on a device that supports everything it uses:
Fossilize's feature filter decides that per pipeline. A replay that skips the filter
can crash the game. It warms a cache only where DXVK would create byte-identical
pipelines, which means the same DXVK generation and feature set, in practice per
driver family. Recording on each machine and replaying there always works.

## Legal status (researched 2026-09-19; research, not legal advice)

Full report on the Linux machine: `re/shader-precompile/legal-steam-shader-cache.md`.
The Steam Subscriber Agreement quotes below were re-checked against the live text.

| option | risk | why |
|---|---|---|
| (a) the mod reads the player's **own** Steam pre-cache, locally | low | personal use of a Subscription. Never write into Steam's folders, and never let Steam-derived entries reach anything that ships |
| (b) **ship** Steam's crowd database, or anything merged from it | **high: don't** | SSA §2.G: no copying or distributing the "Content and Services" "without the prior consent, in writing, of Valve". That definition covers "any other software, content, and updates you download or access via Steam". §9.C allows account cancellation. The data is also mostly translated Rockstar and third-party mod shaders, which Valve could not clear even if it agreed |
| (c) ship Fossilize databases **we record ourselves**, Steam's data kept out | low–medium | no Valve issue. The SPIR-V is a translation of FusionFix/Rockstar shaders, the same exposure FusionFix's shipped shader files already have |
| (d) FFPC as shipped today | low | measured: the baseline's 531 blobs are 505 FusionFix-release `.fxc` shaders (506 with the branch's radar) plus 25 FusionFix builds at runtime; **0** match the untouched game's own `common/shaders` |
| (e) FFPC with hashes in place of `.fxc` bytecode | very low | hashes and render state are facts |

**What this changes in the plan above.** Steam's crowd database can be a base only
**per player, locally**: the mod reads that player's own download. It can never be
a base for a golden database that ships. Shipped golden databases are built only from
recordings contributors make with the mod itself.

**Follow-up (e): DONE in FusionFix `567b3cb`.** Cache files no longer store bytecode
for shaders from the install's `.fxc` files. Where the install has them, the replay
resolves them by hash; where it doesn't, the pipeline would never be used anyway.
Bytecode is kept only for FusionFix's runtime-built shaders (the 25), so player
contributions no longer carry other mods' shaders either (e.g. Liberty City Plates).
The same build adds `plugins\pipelinecache\` for a player's caches from their own
other PCs: warmed, and merged into the local capture with max counts, so it can go
back and forth without the counts compounding.

## Measured vs assumed

- Measured: the Steam log lines above; the instancing and blend gaps in the D3D9 key
  (fixed in FusionFix `0468057`).
- Assumed, to be measured: that DXVK output is identical within a bucket; that the OS
  does not split buckets; any overlap with the crowd database.

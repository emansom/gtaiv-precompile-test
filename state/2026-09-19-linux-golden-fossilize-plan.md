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

A Fossilize database holds exact Vulkan create-infos and SPIR-V. It produces driver
cache hits only where DXVK would generate *identical* state, which depends on more
than the GPU. The bucket key:

| part | why | recorded today? |
|---|---|---|
| **DXVK build** | SPIR-V, layouts and spec constants change between DXVK releases | **no**, to add. FusionFix pins the DXVK it ships (`vulkan.dll` on Windows, `d3d9.dll` on Linux), so a hash of that module identifies it |
| GPU vendor + model | DXVK's output depends on device features and properties | yes: `vendorId`/`deviceId` in the FFPC meta |
| driver + driver version | features change with driver releases; the driver compiles the result | yes, since FusionFix `d1c6119`: `VkPhysicalDeviceDriverProperties`, e.g. `radv Mesa 26.2.3-arch1.1` |
| OS | recorded, but whether it must split buckets is **not known** | yes: `windows` / `wine <ver>` |

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

**Provenance TODO:** add the DXVK build (module hash, and version string if exposed) to
the FFPC meta, so every contribution names its bucket.

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

Tools: `fossilize-list`, `fossilize-convert-db` and `fossilize-merge-db` were built in
`/run/user/1000/zs/fz-build/cli/` for the research. That is tmpfs, so rebuild from
ValveSoftware/Fossilize after a reboot.

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

**Recommended follow-up (e), with no functional cost.** Stop storing bytecode for
shaders that come from the install's `.fxc` files. Where the install has them, the
replay already resolves them by hash; where it doesn't, the pipeline would never be
used anyway. Keep bytecode only for FusionFix's runtime-built shaders (the 25). This
also stops player contributions from carrying other mods' shaders (e.g. Liberty City
Plates).

## Measured vs assumed

- Measured: the Steam log lines above; the instancing and blend gaps in the D3D9 key
  (fixed in FusionFix `0468057`).
- Assumed, to be measured: that DXVK output is identical within a bucket; that the OS
  does not split buckets; any overlap with the crowd database.

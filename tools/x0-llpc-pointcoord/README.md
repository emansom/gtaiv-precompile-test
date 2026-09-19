# X0: does a PointCoord fragment library ever fast-link?

A one-minute Vulkan unit test. It needs no game, no DXVK and no elevation. It decides
**H0** from the Linux side's stutter research (`zero-stutter-research.md` §1.3 "Finding A",
§2.5 "X0"):

> On AMD's Windows Vulkan driver (LLPC), a graphics-pipeline-library fragment shader that
> declares `BuiltIn PointCoord` is stored as "requires full pipeline". Linking it never
> fast-links. A link with `FAIL_ON_PIPELINE_COMPILE_REQUIRED` returns
> `VK_PIPELINE_COMPILE_REQUIRED`, and a link without that flag silently runs a full compile.

That matters because dxbc-spirv declares `PointCoord` in **every** SM3 pixel shader, for
D3D9 point sprites. If H0 holds, every new GTA IV pipeline on that driver is a full
synchronous compile on DXVK's CS thread.

## Run it

```powershell
.\run\Invoke-X0.ps1
```

It runs `x0.exe` three times, each with a fresh, empty AMD pipeline-cache folder (the same
three `AMD_VK_*` variables Steam sets for GTA IV). Each run writes
`results\raw\x0-run<N>.json` and `.txt`, and all three are collected in
`results\raw\x0.json`. The last line printed is `X0 VERDICT: ...`.

Direct use: `x0.exe [-Json <path>] [-Iterations 25] [-Binding auto|both|heap|legacy]
[-Device <index>]`. `-FixedNonce <hex>` is a diagnostic that turns off the cold guarantee
(see below). Never report a run made with it.

## What it does

It builds pipelines the way DXVK v3.1.1 builds a D3D9 draw's *base* pipeline
(`dxvk_graphics.cpp` `createBasePipeline`, `dxvk_shader.cpp` `compile*ShaderPipeline`):

- four libraries: vertex input, pre-rasterization (the VS), fragment shader, and
  fragment output;
- the same library flags, dynamic state, dynamic-rendering info and layout type as
  DXVK;
- a link **without** `LINK_TIME_OPTIMIZATION`.

The two arms differ only in the fragment shader:

- **arm A** declares and reads `BuiltIn PointCoord`. As in dxbc-spirv
  (`sm3_io_map.cpp:676-698` @`bf14419e`), each TEXCOORD component is an `OpSelect`
  between `PointCoord` and the texcoord, chosen at run time by `enablePointSprite`;
- **arm B** is the same shader with a constant in place of `PointCoord`.

On start-up, x0 checks the SPIR-V it embeds: arm A must declare `PointCoord` and arm B
must not.

**What one iteration does, per arm.** It creates two separate sets of never-seen VS and
FS libraries. It links the first set with `FAIL_ON_PIPELINE_COMPILE_REQUIRED` and
records the VkResult and the time. It links the second set without the flag and records
the time. There are 2 warm-up iterations, then 25 measured ones, and the arms alternate
which goes first. All timings use QueryPerformanceCounter.

**Every compile is cold, even with a warm driver cache.** Before each library is
created, x0 patches a fresh nonce into an `OpConstant` in both shaders. The shader
compares that constant with push data, so the constant stays live and no driver can
strip it before hashing. The runner also points the AMD cache at an empty folder.

**The binding model.** On the Windows machine, DXVK 3.1.1 logs `Binding model:
Descriptor heap` (VERIFIED: `off-rep2-run\GTAIV_d3d9.log` on the NTFS mount). So
X0 runs:

- **heap** mode, the way DXVK does it: `DESCRIPTOR_HEAP_BIT_EXT` on every pipeline and a
  null layout. This mode decides the verdict;
- **legacy** mode as a cross-check: an `INDEPENDENT_SETS` pipeline layout.

If heap mode cannot run at all, the verdict comes from legacy and says so.

## How to read the result

| `X0 VERDICT` | what the numbers look like | what it means |
|---|---|---|
| **H0_PROVEN** | A: every link (i) returns `VK_PIPELINE_COMPILE_REQUIRED`; link (ii) median ≥ 5 ms and ≥ 10× B. B: every link returns `SUCCESS`; link (ii) median < 2 ms | The shipping driver never fast-links a DXVK SM3 pixel shader. Each new base pipeline is a full compile. |
| **H0_FALSIFIED** | Both arms return `SUCCESS` on every link; both link (ii) medians < 2 ms | The closed driver has fixed the LLPC TODO. H1 (32-bit lifetime tracking) moves up; see X1. |
| **OTHER** | anything else | Report it as-is. See the list below. |
| **MIXED** | the three runs disagree | Report every run's line. |
| **NO_GPL** | the device lacks `VK_EXT_graphics_pipeline_library` | DXVK does not use GPL here either. |
| **ERROR** | x0 could not measure | The output says why. |

Known shapes of OTHER:

- **A slow, but A's link (i) returns `SUCCESS`.** The driver ignores `FAIL_ON`: xgl has an
  `ignoreFlagFailOnPipelineCompileRequired` setting. H0's substance still holds.
- **Both arms slow.** Fast linking is broken on this driver for every shader, not only
  for `PointCoord`.
- **B between 2 and 5 ms.** A borderline fast link. Read the numbers.

**A second fingerprint, not used by the verdict.** On LLPC, arm A's *FS library create*
should be much cheaper than arm B's. LLPC returns `RequireFullPipeline` before it
compiles anything (`llpcCompiler.cpp:1609-1618`), so arm A's library is a stub. This is
INFERRED for the closed driver.

**Also look at the binding models.** If heap and legacy disagree, x0 prints a `NOTE`.
Report both.

## What X0 simplifies relative to DXVK, and why the verdict stands

1. **Where `enablePointSprite` comes from.** In a GPL library, DXVK turns the spec
   constant into a uniform-buffer load (`dxvk_shader_ir.cpp` `lowerSpecConstantsToCbv`).
   X0 loads it from push data instead. Both are run-time values, so `PointCoord` stays
   live in both. LLPC's rule does not depend on this: it fires when the module
   *declares* a `PointCoord` variable (`llpcShaderModuleHelper.cpp:92-95`, a scan of
   module variables), however the value is used. VERIFIED in open LLPC `40cb8d95`;
   INFERRED for the closed driver.
2. **No descriptors or samplers; tiny shaders.** LLPC's decision comes before any code
   generation, and arm B has the same interface as arm A. So whatever is left is the
   `PointCoord` difference.
3. **"Legacy" stands in for DXVK's descriptor-buffer model.** DXVK only uses descriptor
   buffers when the heap is missing, and the target machine has the heap (VERIFIED from
   its log).
4. **Less dynamic state.** X0 leaves out the sample-location and dynamic-multisample
   states that DXVK adds when `VK_EXT_sample_locations` or sample-rate shading apply. It
   also has no `VK_EXT_depth_clip_enable` fallback (it uses EDS3 depth clip, as the target
   does). Neither enters LLPC's `RequireFullPipeline` decision. Neither enters xgl's
   `IsGplFastLinkPossible` either, which checks only library presence, the LTO flag and
   push-constant compatibility (`vk_graphics_pipeline.cpp:656-693`). VERIFIED for xgl
   `e9782eb3`.
5. **No shader module identifiers.** Libraries are always built from SPIR-V with no
   extra flags, like DXVK's first compile. In the game, `FAIL_ON` reaches the link through
   libraries re-created from identifiers under 32-bit lifetime tracking
   (`dxvk_graphics.cpp:1375`). X0 sets `FAIL_ON` on link (i) directly.
6. **No link-time optimization anywhere.** DXVK 3.1.1 never sets
   `LINK_TIME_OPTIMIZATION` or `RETAIN_LINK_TIME_OPTIMIZATION_INFO`; its optimized
   pipelines are separate monolithic compiles. (VERIFIED: neither flag appears in `src/`
   at `v3.1.1`.) X0 sets neither.
7. **The process name.** The driver sees application `GTAIV.exe` and engine `DXVK`
   3.1.1, as in game, but the process image is `x0.exe`. A driver profile keyed on the
   process image would not apply. That is probably irrelevant (INFERRED), because a
   `GTAIV.exe` profile would target the game's D3D9 path. If the verdict is FALSIFIED,
   check it cheaply: copy `x0.exe` to an empty folder as `GTAIV.exe` and run it again.

## Validation on Linux (2026-09-19)

All VERIFIED on the build below, on an RX 9070 XT:

- **Native x86_64 build on RADV (Mesa 26.2.3).** H0_FALSIFIED in both binding models.
  Link median 0.002 ms for both arms, and `SUCCESS 25/25` for every link. RADV has no
  such rule, so this is the expected result.
- **`x0.exe` under Wine 11.17 on the same GPU.** Same result, 0.003 ms. That exercises
  the 32-bit path end to end, including the descriptor heap through winevulkan.
- **The cold guarantee.** Library creation takes 0.25–0.46 ms with fresh nonces and
  0.015 ms with `-FixedNonce`. The Mesa cache grows by 436 files against 10.
- **`RADV_DEBUG=nogpl`** produces NO_GPL and exit code 2.
- **The verdict logic,** unit-tested with synthetic samples: proven, falsified, both
  slow, `FAIL_ON` ignored, below threshold, library error.
- **`Invoke-X0.ps1`,** run end to end under pwsh 7.6.6 against the native binary.

**Not verified: AMD's Windows driver.** Measuring that is what this test is for.

## Provenance

```
source     x0.c, shaders/x0.vert, shaders/x0.frag in this folder
           source sha256 ea8b9caca89ee06c3733f42cfcd9af5cd0cd3970c36de3e5f63fa404e83362fa
           (x0.exe prints the first 12 digits on its first line)
commit     built from the working tree on top of 92f71a1; the commit that adds this
           README carries exactly that source
toolchain  MSVC 14.51.36231 x86, -O2 -MT, linked -Brepro (msvc-wine on Linux);
           glslang 16.4.0, SPIRV-Tools 2026.3, Vulkan headers 1.4.357
sha256     a10d6971d3d85c6ed33273cb9ae968563879ff9b23465fc96abb6e9f39611326
size       181,248 bytes, PE32 i386 console
imports    KERNEL32.dll only (static CRT; the Vulkan loader is opened at run time)
rebuild    bash tools/x0-llpc-pointcoord/build.sh (reproducible: two builds, same sha256)
```

These references were read at the versions pinned above: DXVK `v3.1.1` (`b1a1c99`),
dxbc-spirv `bf14419e`, LLPC `40cb8d95`, xgl `e9782eb3`.

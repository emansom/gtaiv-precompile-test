# Handoff: Linux → Windows (shader warming / pipeline cache)

State as of **2026-09-19**, written by the Claude Code instance on the Linux side
(Arch, Proton, RX 9070 XT, DXVK). Read this before `CLAUDE.md`, which is the
step-by-step stutter A/B built on top of it.

**Every run — yours and any third-party tester's — uses the latest DXVK.** That is a
requirement of the design, not a preference of this machine: see the next section.

## What this session is for

Two questions, both wanted. The first gates the whole "golden cache" plan:

> **1. Does GTA IV resolve the same shader directory on Windows + NVIDIA as it does
> on Linux + AMD, when both run DXVK?**

> **2. Does precompiling actually remove in-gameplay stutter on Windows?**

Question 1 comes first because it is quick and its answer changes what the project
ships. Question 2 is the reason the precompiler exists at all and has **never been
measured on Windows** — it is the outstanding validation, not a nice-to-have. Most
of this document is context for question 1; `CLAUDE.md` Run 2 covers question 2.

## Why that question decides everything

GTA IV ships **six** shader directories: `win32_30` plus `win32_30_low_ati`,
`_nv6`, `_nv7`, `_nv8`, `_atidx10`. Their `.fxc` bytecode genuinely differs, so the
shader hashes differ, so **every pipeline key naming them differs**. A cache captured
against one directory is noise against another.

`FUN_00b1d100` (GTA IV 1.2.0.59) picks by probing depth formats, not by vendor ID:

```
CheckDeviceFormat fails      -> [1] win32_30_low_ati
'RAWZ' (0x5a574152) works    -> [2] win32_30_nv6
'DF24' (0x34324644) works    -> [5] win32_30_atidx10
'INTZ' (0x5a544e49) works    -> [4] win32_30_nv8
none of the above            -> [0] win32_30
```

Result is stored as a `char*` in `DAT_01633800`; the table of six is at `0x01045520`.

**This is why DXVK everywhere is load-bearing, not a convenience.** Under DXVK that
probe is answered by *DXVK*, not the vendor driver, which is what could collapse six
vendor-specific shader sets into one shared cache. On native D3D9 the vendor driver
answers it, so an NVIDIA and an AMD player would load different bytecode and their
caches could never be pooled — which is why a native-D3D9 run is not a fallback or a
second data point, it is a different experiment whose results do not combine with
anything else here.

DXVK's own format support can still depend on the Vulkan implementation, so
convergence under DXVK is **plausible, not proven**. We cannot test it from Linux —
hence this handoff.

Linux measured (not assumed): resolves to **`win32_30`**. Proof: of the 1734 shaders
in `update/common/shaders/win32_30`, 498 hashes match captured keys; every other
directory matches **0**.

## The whole Windows session, in order

1. **Find the game** — confirm before anything deploys to it:
   `.\run\Find-GtaivInstall.ps1 -Json .\results\raw\installs.json`
   Its VDF parsing is verified against real Steam data; its **registry reads are not
   tested at all**. If it returns nothing or something surprising, set `GamePath` by
   hand rather than letting a guessed path get written to.
2. **Install the latest DXVK** — 32-bit `d3d9.dll` beside `GTAIV.exe`. Confirm a
   `GTAIV_d3d9.log` appears on launch; no log means native D3D9 and the run must not
   be collected.
3. **Deploy** the `.asi` built from branch `shader-precompile-cache` and
   `data\plugins\FusionFix.pipelinecache.baseline.bin` into `<game>\plugins\`.
4. **Run once** with `PrecompileShaders = 1`, `CaptureDrawKeys = 1`. Load a save,
   drive a few minutes, quit **through the pause menu** (never kill the process).
5. Optionally **run again** with `PrecompileShaders = 0` for a clean coverage
   capture — at `1`, most of what gets recorded is the replay's own draws.
6. **Then run the PresentMon stutter A/B** (`CLAUDE.md`, Run 2). It is the
   measurement the precompiler exists to justify and it has never been run on
   Windows, so it is the outstanding validation rather than an optional extra. The
   setup is already done by this point; keep the cache file from step 4/5, because
   the A/B's ON run warms from exactly that pipeline set.
7. Reboot. **Do not analyse anything here**; the Linux side reads it off the mount.

## What step 4 decides

That single run answers the question this session exists for. Launch once, then read
the log line:

```
shader directory in use: <name>
provenance: <os> / <adapter> / driver <ver> / backend <DXVK|native D3D9>
```

- **`win32_30` + `DXVK`** → convergence holds; one golden cache is achievable, and
  the Windows capture can be merged straight into the Linux one.
- **anything else** → the golden cache is per-bucket, and the merge tool must key on
  this field. That is not a failure; it is the answer we need, and the cache format
  already records it so nothing silently corrupts.

There is a second, independent tell in the same log, and it needs no interpretation:
the replay reports **`no-shader`** skips. On Linux that is `0` of 2001 pipelines. If
Windows resolved a different shader directory, the shipped baseline names shaders
that install never creates, and this number will be large. A big `no-shader` count
with a `win32_30` line would mean something else is wrong and is worth stopping for.

## Where the code is

Branch **`shader-precompile-cache`** on `emansom/GTAIV.EFLC.FusionFix`
(NOT `shader-precompile`, which is an older diverged line; NOT upstream ThirteenAG).

```
git clone -b shader-precompile-cache https://github.com/emansom/GTAIV.EFLC.FusionFix
```

**Do not open an issue or PR against ThirteenAG/GTAIV.EFLC.FusionFix.** The owner has
explicitly reserved that decision; there is a real upstream bug documented below, and
it stays local until they say otherwise.

## The cache format (one file per player)

`FusionFix.pipelinecache.f<fmt>-ms<msaa>.bin`, magic `FFPC`, sectioned:

| section | id | contents |
|---|---|---|
| meta | 1 | `CacheMeta` (44 bytes, packed) + 4 length-prefixed strings |
| rsTypes | 2 | which render states the records carry |
| decls | 3 | vertex declarations |
| keys | 4 | `KeyRecord` table |
| shaders | 5 | the bytecode those keys name |

Strings, in order: **shaderDir**, adapter, driver, os. `shaderDir` is the bucketing
key. Sectioned so a merge tool can seek to the metadata of a thousand contributions
without parsing a thousand key tables.

One file is the whole contribution — keys can never arrive without the shaders they
name. The capture **refuses to merge** a cache whose `shaderDir` differs from the
local one, and logs why.

## What is already settled (don't re-derive)

- **Replay works.** 2001 of 2001 pipelines warmed, 0 no-shader / 0 no-decl / 0 no-RT.
- **The shipped baseline covers 99.3%** of every pipeline ever observed locally
  (1985 of 1999 at the time of measurement), verified two independent ways: offline
  reconstruction of `ReplayPipelineKey` and the runtime's own count.
- **Identity granularity matters.** `ReplayPipelineKey` keeps shaders, declaration,
  topology, RT/depth/MSAA, sampler types and exactly **three** render states
  (`ALPHATESTENABLE`, `ALPHAFUNC`, `FOGENABLE`). Sampler types must be masked to the
  slots the pixel shader *declares*. Get this wrong and the same data counts 1999,
  4820 or 9327 pipelines against DXVK's real ~660.
- **Resolution does not affect keys.** Measured at 1080p vs 720p: identical RT combos.
- **Antialiasing and other settings only ADD keys**, never move RT formats, so
  merging captures from different settings is safe.
- **GPL is irrelevant to the DATA.** Keys are identical whether
  `VK_EXT_graphics_pipeline_library` is on or off; GPL only changes whether warming
  pays off. A contributor does **not** need to change their DXVK config.
- **Coverage is saturated.** Three separate attempts to broaden it returned ~nothing:
  synthesising keys from the `.fxc` database (24/432 exact vs a 23/432 control), a
  full 10-district map tour (+0 shaders), and spawning 51 vehicles (+2 shaders). The
  remaining 1236 of 1734 shaders look unreachable, not merely unvisited.

## Known traps

- **`count` in any pre-2026-09-19 cache is inflated.** Merging several predecessor
  files re-added their accumulated counts; this machine's read 41.5e9 against
  5,073,509 real draws. Fixed by merging only one file. Counts order
  warm-most-used-first, so a corrupted count corrupts the ordering, not correctness.
- **The game must be FOCUSED** for anything script-driven; GTA IV freezes its
  simulation when unfocused and queued work never drains.
- **Never `pkill` GTA IV** — it can respawn via `PlayGTAIV.exe` and leaves the Proton
  stack half-alive. On Linux use the `gtaiv-quit` skill (writes the pause-menu quit
  flag). On Windows, quit through the game's own menu.

## Parked, needs the owner's approval before acting

Upstream FusionFix commit `caf11e5` page-faults GTA IV 1.2.0.59 at startup. It patches
3 bytes at a site chosen by `6A ? 53 55 56`, accepted on `!empty()`. That pattern is
**unique on disk but matches twice in memory** (`0x439655`, `0x942ac0`) because
`0x439655` sits in a SecuROM-encrypted region decrypted at load. `get_first(0)` takes
the wrong one, rewriting `mov ecx,[0x7b6a5630]` into `mov ecx,[0x6A535630]` — exactly
the recorded fault `read 6A535630 at PC 0x439651`. Fixed locally in `aaa98ec` by
matching on a longer form that is unique at runtime.

**Confirming this reproduces on Windows would be genuinely useful** (it is the one
open question in the upstream report) — but do not file anything.

## Sharing state back

**Primary channel: the NTFS partition.** The owner mounts the Windows install from
Linux afterwards, so the Windows session does **not** need to analyse anything, does
not need Python, and does not need `gh`. Capture, quit, reboot. These are the files
the Linux side reads off the mount:

```
<game>\plugins\FusionFix.pipelinecache.f*-ms*.bin   the capture (shaderDir is in its metadata)
<game>\plugins\FusionFix.shaders.log                this run's log, truncated per process
<game>\GTAIV_d3d9.log                               DXVK version + pipeline-library status
C:\Users\<user>\.claude\projects\...                the Windows session transcript
```

`FusionFix.shaders.log` exists precisely because of this handoff: the ASI used to log
only via `OutputDebugString`, which nothing captures on Windows without a debugger
attached and which leaves **nothing on disk to mount**. If you find no such file, the
deployed ASI predates commit `9eb5766` and the log for that run is unrecoverable.

Secondary channel: commit notes to `state/` (see `state/README.md`) for anything the
other side should read without a mount — conclusions, surprises, anything that
contradicts this file. Keep large artifacts out of git; the mount handles those.

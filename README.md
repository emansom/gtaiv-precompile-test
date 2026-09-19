# gtaiv-precompile-test

A small, standalone Windows harness to verify — on **your** hardware — whether the
**FusionFix launch-time shader precompiler** eliminates in-gameplay
shader-compilation **stutter** in **Grand Theft Auto IV** (Complete Edition,
**running the latest DXVK**), and to measure the before/after objectively.

> **DXVK is required, not optional.** GTA IV chooses between six shader directories
> by probing depth formats. Under native Direct3D 9 the vendor's driver answers that
> probe, so different GPUs load *different shader bytecode* and their results cannot
> be compared or pooled. Under DXVK, DXVK answers it — which is what makes results
> from different machines mean the same thing. A native-D3D9 run is a different
> experiment and should not be collected here.

It captures per-frame present times with **PresentMon**, drives a fixed short
gameplay segment with the precompiler **OFF** (cold pipeline cache → expect
stutter) then **ON** (expect none), detects the isolated compile-stutter spikes,
and emits a **PASS/FAIL** result you post to a shared board so results aggregate
across many GPUs/drivers/CPUs.

> **Easiest path: open this folder in [Claude Code](https://claude.com/claude-code)
> on Windows and say "run the precompile test".** It follows [`CLAUDE.md`](CLAUDE.md)
> and walks you through every step, then formats + posts your result.

## Two runs live here — do both

They share an install, saves and DXVK setup, so the marginal cost of the second is
small. They answer **different** questions and neither substitutes for the other:

| | **Shader-cache run** | **Stutter A/B** (this README's subject) |
|---|---|---|
| question | does this machine resolve the same shader directory, and what pipeline keys does it produce? | does precompiling remove in-gameplay stutter here? |
| time | ~10 minutes, one launch | ~15–30 minutes, two captured drives |
| needs | nothing but the game | PresentMon, elevation, a repeatable route |
| output | a `.pipelinecache` file + log | `results\result.md` → the pinned issue |
| start at | [`HANDOFF.md`](HANDOFF.md) | this file, then `CLAUDE.md` Step 0 |

**Do the shader-cache run first**, because it is short and it gates a design
question: if this machine resolves a different shader directory, caches cannot be
pooled across machines at all, and that changes what the project ships. **Then do the
A/B**, which is the one that answers whether the precompiler is actually worth
shipping on your hardware — that is still an open question on Windows, and it is the
whole point of the precompiler existing.

If you only have time for one, say which you did; a cache capture alone is still
useful, and an A/B alone is still useful. Both from the same machine is worth more
than either, because the A/B result can then be read against the exact pipeline set
that machine warmed.

## What it proves

Under DXVK a Vulkan **pipeline** is built the first time the game draws with a given
shader + render-state combination, and that first hit is a **stutter** (an isolated
frame-time spike). The precompiler does all that work **at launch**. We prove it
by comparing the same drive, cold, OFF vs ON: **PASS** = the isolated spikes seen
OFF drop to ~0 ON and the p99.9 / max frame times collapse toward the median.

**Record whether `VK_EXT_graphics_pipeline_library` is active** (grep the DXVK log
for `Graphics pipeline libraries`) **and which Vulkan driver ran** (the precompiler
logs a `vulkan driver:` line). How much stutter there is to remove depends on the
driver, not just on GPL. With GPL on, Linux/RADV had almost nothing left to remove
(+2 spikes cold vs warm). With GPL on, Windows/AMD's proprietary driver lost ~18 s
per 90 s drive cold, and the precompiler cut that by 73%. An OFF run with no spikes is only
a real "nothing to fix here" if the run was **provably cold**: see `CLAUDE.md`. A
warm driver cache produces the same flat line.

## Requirements

- **Windows 11** (build 22000+). Windows 10 is legacy and is not supported — don't
  collect a result from it.
- The toolchain, all via winget (none need Administrator to install):
  ```powershell
  winget install Microsoft.WindowsTerminal   # terminal
  winget install Microsoft.PowerShell        # PowerShell 7.x (pwsh)
  winget install Anthropic.ClaudeCode        # drives the harness
  winget install Intel.PresentMon            # frame-time capture
  winget install Python.Python.3.13          # for tools\cache\*.py
  ```
  Then reopen Windows Terminal **as Administrator** and run `pwsh` — PresentMon
  captures via ETW and needs elevation.
- Note `Intel.PresentMon` installs Intel's PresentMon *application*. The harness
  drives the pinned command-line `PresentMon.exe` fetched by
  `.\tools\presentmon\Get-PresentMon.ps1`; run that too. Pinning the CLI version is
  what keeps results comparable between machines.
- **GTA IV** with the **latest DXVK** and the FusionFix build that includes the
  precompiler — branch `shader-precompile-cache` of
  `emansom/GTAIV.EFLC.FusionFix`. A build of it is in [`prebuilt/`](prebuilt/) so no
  toolchain is needed; check `prebuilt/README.md` that it is not stale first.
- **PresentMon CLI** — fetched at a pinned version by
  `tools\presentmon\Get-PresentMon.ps1` (MIT, Intel/MS). Not bundled; verify the
  printed hash.
- **Python** is needed only for `tools\cache\*.py` (reading a `.pipelinecache`
  container). The frame-time analysis is pure PowerShell and needs nothing extra;
  `python\analyze_frametimes.py` is an optional richer version of it.
- Optional: **GitHub CLI (`gh`)** to auto-post your result.

## Quick start — the stutter A/B (manual PowerShell)

For the shader-cache run instead, see [`HANDOFF.md`](HANDOFF.md); it needs none of
this. In an **Administrator** `pwsh`, from the repo root:

```powershell
Copy-Item config\test.config.example.psd1 config\test.config.psd1
# edit config\test.config.psd1: GamePath + how the precompiler toggles
.\tools\presentmon\Get-PresentMon.ps1
.\run\Invoke-PrecompileTest.ps1 -Phase all      # follow the on-screen gates
# -> produces results\result.md ; post it to the pinned issue (see below)
```

Or step by step: `-Phase hardware`, `-Phase off`, *(relaunch game)*, `-Phase on`,
`-Phase analyze`, `-Phase report`. See [`CLAUDE.md`](CLAUDE.md) for the guided run.

You (the human) drive a short fixed route during each capture; the harness handles
everything else (cache clear, capture, analysis, formatting).

## Share your result

The run produces `results\result.md` — a ready-to-post comment. Post it on the
project's **pinned "Hardware Test Results" issue (#1)**:

```powershell
gh issue comment 1 --repo emansom/gtaiv-precompile-test --body-file results\result.md
```

…or paste it into a new comment on that issue in the browser. The schema is fixed
so results compare cleanly; see [`results/examples/result.example.md`](results/examples/result.example.md).

## File tree

```
gtaiv-precompile-test/
├─ CLAUDE.md                  # guide for Claude Code on Windows; cache run first, then the A/B
├─ HANDOFF.md                 # state of the shader-cache work + the question Windows answers
├─ README.md                  # this file
├─ LICENSE                    # MIT (the harness)
├─ pinned-issue.md            # body for the stickied "Hardware Test Results" issue
├─ prebuilt/                  # so no build toolchain is needed
│  ├─ GTAIV.EFLC.FusionFix.asi   # built from shader-precompile-cache; check it isn't stale
│  ├─ GTAIV.EFLC.FusionFix.ini   # settings TEMPLATE, don't blindly overwrite an existing one
│  └─ README.md                  # commit, toolchain, hash, how to verify + install
├─ cache/                     # all cache format v2 (instancing recorded per key)
│  ├─ linux-amd-dxvk/         # reference caches from the development machine (the MORE modded install)
│  │  ├─ FusionFix.pipelinecache.baseline.bin  # DEPLOY THIS (2350 pipelines; game shaders by hash)
│  │  ├─ FusionFix.pipelinecache.f21-ms0.bin   # the full capture (reference only)
│  │  └─ README.md                             # how the baseline was built and filtered; how the installs differ
│  └─ windows-amd-dxvk/       # the first Windows session's capture, upgraded to v2
│     ├─ FusionFix.pipelinecache.f21-ms0.bin
│     └─ README.md
├─ saves/                     # same starting point => key sets are comparable
│  ├─ profile/SGTA400..414       # save games from the Linux prefix
│  └─ README.md                  # per-user profile folder; saves only appear in their own episode
├─ state/                     # notes shared between the Linux and Windows sessions
│  ├─ 2026-09-19-windows-shaderdir.md   # Run 1 on Windows: resolves win32_30, same as Linux
│  ├─ 2026-09-19-windows-stutter-ab.md  # Run 2 on Windows: -73% stutter; read its CORRECTION
│  ├─ 2026-09-19-linux-golden-fossilize-plan.md  # agreed plan: Fossilize layer, buckets, Steam's crowd DB
│  └─ README.md
├─ config/
│  └─ test.config.example.psd1   # copy to test.config.psd1 and edit
├─ run/                       # PowerShell; the A/B happy path needs nothing installed
│  ├─ Invoke-X0.ps1              # Run 0: X0, the driver unit test (no game) -> results\raw\x0.json
│  ├─ Invoke-PrecompileTest.ps1  # orchestrator (phases: hardware/off/on/analyze/report/all)
│  ├─ Find-GtaivInstall.ps1      # locate the game via Steam libraries / Rockstar / uninstall keys
│  ├─ Install-Saves.ps1          # copy saves/profile into the per-user GTA IV profile
│  ├─ Analyze-FrameTimes.ps1     # spike detection + A/B PASS/FAIL verdict
│  ├─ Capture-Frames.ps1         # PresentMon wrapper -> CSV
│  ├─ Clear-ShaderCache.ps1      # clear DXVK's %LOCALAPPDATA%\dxvk, Steam's per-game shadercache, vendor caches
│  ├─ Deploy-Precompiler.ps1     # deploy the ASI + toggle precompile ON/OFF
│  ├─ Verify-Precompiler.ps1     # confirm the precompiler ran (reads FusionFix.shaders.log)
│  ├─ Get-HardwareInfo.ps1       # GPU+driver / CPU / OS -> JSON
│  ├─ New-ResultReport.ps1       # build results\result.md (+ result.json)
│  └─ Common.ps1                 # shared helpers
├─ tools/
│  ├─ cache/                  # read and compare .pipelinecache containers (needs Python)
│  │  ├─ ffpc.py                 # shared reader/writer (v1+v2) and the mirror of the replay's key
│  │  ├─ cacheinfo.py            # index one by seeking to its metadata section
│  │  ├─ basecov.py              # how much of real play a baseline covers, per replay tier
│  │  ├─ merge_cache.py          # union several captures (the core of the golden cache)
│  │  ├─ filter_cache.py         # drop keys naming given shaders (how the baseline was cleaned)
│  │  ├─ fozinfo.py              # Fossilize .foz: who recorded it, counts, overlap between DBs
│  │  ├─ upgrade_cache_v2.py     # one-off shim: v1 -> v2
│  │  ├─ convert_cache.py        # one-off shim from the old 3-file format
│  │  ├─ fxcgap.py               # which of the install's .fxc shaders (1706 stock) a capture reached
│  │  ├─ fxc_hashes.c            # dump shader hashes from the game's .fxc database
│  │  ├─ fxc_passes.c            # dump technique/pass + render state from .fxc
│  │  └─ vdfcheck.py             # validates Find-GtaivInstall's Steam VDF parsing
│  ├─ presentmon/
│  │  └─ Get-PresentMon.ps1   # download the pinned PresentMon CLI
│  └─ x0-llpc-pointcoord/     # X0: does AMD's driver fast-link a PointCoord pixel shader?
│     ├─ x0.exe                  # prebuilt, 32-bit; provenance + how to read it in README.md
│     └─ x0.c, shaders/, build.sh  # the source; build.sh rebuilds x0.exe on Linux
├─ python/                    # OPTIONAL richer frame-time analysis
│  └─ analyze_frametimes.py      # same algorithm; PresentMon/MangoHud/generic CSV; JSON
├─ results/
│  ├─ examples/result.example.md
│  └─ raw/                    # per-run CSVs + JSONs (git-ignored)
└─ samples/                   # CSVs to self-test the analyzer offline
   ├─ baseline_off.presentmon.csv
   ├─ precompiled_on.presentmon.csv
   └─ make_samples.py
```

## How the measurement works (brief)

- **Capture:** PresentMon logs present-to-present frame times to CSV
  (`msBetweenPresents`).
- **Spike detection:** a frame is a compile-stutter spike if it exceeds its
  *rolling-median* baseline by ≥ 8 ms (tunable) **and** ≥ 1.5× baseline **and** a
  robust MAD threshold, with no neighboring spike (**isolated** = the one-time
  compile-hitch signature). Genuine heavy scenes (sustained) are not flagged.
- **Verdict:** PASS if the ON run has 0 isolated spikes (configurable), its p99.9
  didn't regress, and total stutter time dropped — while the OFF run *did* stutter
  (self-consistency).

There is no per-pipeline-compile counter exposed to the game, so the **isolated spike
count is the in-gameplay compile proxy**; the precompiler's own launch log
(`plugins\FusionFix.shaders.log`) reports how many pipelines it warmed.

## Status / provenance — read before trusting a result

**The harness was written on Linux and has been run end to end on Windows once**
(2026-09-19, Windows 11 + AMD). That run found and fixed five bugs that broke every
run: the analyzer crash, the analyze-phase argument binding, the report's number
formatting, the ini section match that could leave the OFF run silently ON, and the
cache clear that left DXVK's and Steam's caches warm. Details are in
`state/2026-09-19-windows-stutter-ab.md`. What that means for trusting a result:

- The spike-detection + A/B algorithm is unit-tested in Python
  (`python/analyze_frametimes.py`, against synthetic before/after data);
  `Analyze-FrameTimes.ps1` is a line-for-line port of it, now also exercised on
  real Windows captures.
- `Find-GtaivInstall.ps1`'s **Steam VDF parsing is verified** against real Steam
  files (`tools/cache/vdfcheck.py` mirrors it and runs on genuine data). Its
  **registry reads — Rockstar keys, uninstall entries — have no test coverage.** Run
  it on its own and confirm the path before anything deploys to it.
- One machine is not many. NVIDIA and Intel on Windows have not been run at all.

If a script misbehaves, please open an issue with the error.

## Credits & license

- Harness: **MIT** (see `LICENSE`).
- [PresentMon](https://github.com/GameTechDev/PresentMon) — Intel/MS, MIT
  (downloaded, not bundled). [CapFrameX](https://www.capframex.com/) is a fine
  GUI alternative for capturing frame times if you prefer.
- FusionFix: [ThirteenAG/GTAIV.EFLC.FusionFix](https://github.com/ThirteenAG/GTAIV.EFLC.FusionFix),
  and the shader-precompiler work on branch `shader-precompile-cache` of the
  `emansom` fork. That work is **not upstream** and is not to be filed upstream
  without the fork owner's say-so.
- Save games and reference caches in this repo are the fork owner's own, committed
  deliberately so a run elsewhere can reproduce the same starting conditions.

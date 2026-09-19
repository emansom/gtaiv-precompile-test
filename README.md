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

## What it proves

Under DXVK a Vulkan **pipeline** is built the first time the game draws with a given
shader + render-state combination, and that first hit is a **stutter** (an isolated
frame-time spike). The precompiler does all that work **at launch**. We prove it
by comparing the same drive, cold, OFF vs ON: **PASS** = the isolated spikes seen
OFF drop to ~0 ON and the p99.9 / max frame times collapse toward the median.

**Record whether `VK_EXT_graphics_pipeline_library` is active** (grep the DXVK log
for `Graphics pipeline libraries`). It decides how much there is to remove: with GPL
on, DXVK front-loads the work at shader-create time and most of this stutter is
already gone. An OFF run with no spikes and GPL on is a correct *"nothing to fix in
this configuration"*, not a broken measurement to retry until it looks bad.

## Requirements

- Windows 10/11 with **Windows PowerShell 5.1** (built in) — run **as Administrator**
  (PresentMon uses ETW).
- **GTA IV** installed, with the FusionFix build that includes the precompiler
  (`emansom/GTAIV.EFLC.FusionFix` branch `shader-precompile`).
- **PresentMon** — auto-downloaded by `tools\presentmon\Get-PresentMon.ps1` (MIT,
  from Intel/MS). Not bundled; verify the printed hash.
- **No Python required.** Analysis is pure PowerShell. (An optional richer Python
  analyzer is in `python\`.)
- Optional: **GitHub CLI (`gh`)** to auto-post your result.

## Quick start (manual PowerShell)

In an **Administrator** PowerShell, from the repo root:

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
├─ CLAUDE.md                  # step-by-step guide for Claude Code on Windows (start here)
├─ README.md                  # this file
├─ LICENSE                    # MIT (the harness)
├─ pinned-issue.md            # body for the stickied "Hardware Test Results" issue
├─ config/
│  └─ test.config.example.psd1  # copy to test.config.psd1 and edit
├─ run/                       # PowerShell (zero-install happy path)
│  ├─ Invoke-PrecompileTest.ps1  # orchestrator (phases: hardware/off/on/analyze/report/all)
│  ├─ Analyze-FrameTimes.ps1     # spike detection + A/B PASS/FAIL verdict
│  ├─ Capture-Frames.ps1         # PresentMon wrapper -> CSV
│  ├─ Clear-ShaderCache.ps1      # clear NVIDIA/AMD/Intel + D3DSCache shader caches
│  ├─ Deploy-Precompiler.ps1     # deploy the ASI + toggle precompile ON/OFF
│  ├─ Verify-Precompiler.ps1     # confirm the precompiler actually ran (~1734 shaders)
│  ├─ Get-HardwareInfo.ps1       # GPU+driver / CPU / OS -> JSON
│  ├─ New-ResultReport.ps1       # build results\result.md (+ result.json)
│  └─ Common.ps1                 # shared helpers
├─ tools/presentmon/
│  └─ Get-PresentMon.ps1      # download the pinned PresentMon CLI
├─ python/                    # OPTIONAL richer analysis (only if you have Python)
│  └─ analyze_frametimes.py   # same algorithm; PresentMon/MangoHud/generic CSV; JSON
├─ results/
│  ├─ examples/result.example.md
│  └─ raw/                    # per-run CSVs + JSONs (git-ignored)
└─ samples/                   # synthetic CSVs to self-test the analyzer offline
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

## Status / provenance

The spike-detection + A/B algorithm is unit-tested in Python
(`python/analyze_frametimes.py`, validated against synthetic before/after data);
the PowerShell `Analyze-FrameTimes.ps1` is a line-for-line port of it. The scripts
were authored on Linux and are **carefully written but not yet run on Windows** —
if a script misbehaves on your machine, please open an issue with the error.

## Credits & license

- Harness: **MIT** (see `LICENSE`).
- [PresentMon](https://github.com/GameTechDev/PresentMon) — Intel/MS, MIT
  (downloaded, not bundled). [CapFrameX](https://www.capframex.com/) is a fine
  GUI alternative for capturing frame times if you prefer.
- FusionFix: [ThirteenAG/GTAIV.EFLC.FusionFix](https://github.com/ThirteenAG/GTAIV.EFLC.FusionFix)
  and the `shader-precompile` fork.

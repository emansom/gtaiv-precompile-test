# CLAUDE.md — run the GTA IV shader-precompile test (Windows)

> **Read [`HANDOFF.md`](HANDOFF.md) first.** It carries the current state of the
> work, the cache format, what is already settled, and the one question the Windows
> side exists to answer. This file is the step-by-step stutter A/B on top of that.

You are Claude Code running on the tester's **Windows** machine. Your job: run
this harness end-to-end to measure whether the FusionFix **shader precompiler**
eliminates in-gameplay shader-compile **stutter** in **Grand Theft Auto IV**,
then format the result and help the tester post it to the project's pinned results
issue.

**Every run uses the latest DXVK**, on Windows exactly as on Linux — this is a
requirement, not a preference. GTA IV picks between six shader directories by
probing depth formats, and under native D3D9 that probe is answered by the vendor's
driver, so different GPUs load **different shader bytecode** and produce caches that
cannot be pooled. Under DXVK the probe is answered by DXVK, which is what makes a
single shared cache possible at all. A native-D3D9 result is not comparable to
anything else we have and should not be collected.

**You cannot play the game for the tester.** Parts of this are manual: the tester
launches GTA IV and drives a short fixed route while PresentMon captures frames.
Your role is to run the scripts, tell the tester exactly what to do at each gate,
wait for them, then analyze and format the result. Be explicit and patient.

Pinned results issue: **#1** — `https://github.com/emansom/gtaiv-precompile-test/issues/1`
*(the repo owner fills in `emansom`; ask the tester if unknown).*

---

## What "PASS" means (so you can explain it)

Under DXVK, a Vulkan **pipeline** is built the first time the game draws with a given
shader + render-state combination. Cold, that first use is a **stutter** — an isolated
large frame-time spike. The precompiler builds them all **at launch** instead. We
prove it by capturing the SAME short drive twice on a **freshly cleared pipeline
cache**: once with the precompiler **OFF** (cold → should stutter) and once **ON**
(should not). **PASS** = the isolated compile spikes seen OFF drop to ~0 ON, and
p99.9/max frame time collapse to the median.

**Record whether `VK_EXT_graphics_pipeline_library` is active** — grep the DXVK log
for `Graphics pipeline libraries`. It decides how much there is to remove: with GPL
on, DXVK does the expensive work at shader-create time and the stutter this test
measures is largely already absent (measured on Linux: +2 isolated spikes cold vs
warm, i.e. nothing to remove). With GPL off, pipelines compile lazily on first draw
and the stutter is real. **An OFF run with no spikes and GPL on is not a failure of
the precompiler — it is a correct "nothing to fix here" for that configuration**, and
should be reported as such rather than retried until it looks bad.

This does **not** affect the cache data: the keys are identical either way, so a
contributor never needs to change their DXVK config to contribute coverage.

---

## Step 0 — Preconditions (check, don't assume)

Run these and report what you find; stop and ask the tester if something's wrong.

```powershell
$PSVersionTable.PSVersion                      # need >= 5.1 (built into Win10/11)
# Elevated? PresentMon needs Administrator:
([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Get-Command gh -ErrorAction SilentlyContinue   # optional: lets you post automatically
```

- **Not elevated?** Tell the tester to reopen Claude Code / the terminal **as
  Administrator** (right-click → Run as administrator). PresentMon captures via
  ETW and needs it.
- **GTA IV** must be installed with the **FusionFix build that includes the
  precompiler** (from `emansom/GTAIV.EFLC.FusionFix` branch
  `shader-precompile-cache` — `shader-precompile` is an older diverged line).
- **DXVK must be installed and actually loading.** Drop the latest release's 32-bit
  `d3d9.dll` beside `GTAIV.exe`, then confirm a `GTAIV_d3d9.log` (or
  `DXVK_LOG_PATH`) appears on launch. If there is no DXVK log, the run is on native
  D3D9 and must not be collected — see the note at the top of this file. Record the
  DXVK version and whether pipeline libraries are supported:
  `Select-String -Path "<game>\GTAIV_d3d9.log" -Pattern 'DXVK|pipeline librar'`
  If the tester only has the source, they must build the `.asi` first (out of
  scope here) or supply a prebuilt one; note its path.
- All harness paths below are relative to the repo root (this folder).

## Step 1 — Configure

Copy the example config and set the game path + how the precompiler toggles.

```powershell
Copy-Item config\test.config.example.psd1 config\test.config.psd1 -Force
notepad config\test.config.psd1      # or edit it yourself
```

Fill in:
- `GamePath` — the folder with `GTAIV.exe`. **Leave `$null` and let it auto-detect**:
  the harness asks Steam and the Rockstar Games Launcher where the game is rather
  than guessing Program Files. Run it directly first and confirm the answer:

  ```powershell
  .\run\Find-GtaivInstall.ps1 -Json .\results\raw\installs.json
  ```

  It reads Steam's root from the registry, walks **every** library in
  `libraryfolders.vdf` (the game is often on a second drive), resolves `installdir`
  from `appmanifest_12210.acf` (12210 = GTA IV / Complete Edition, 12220 = EFLC),
  and also checks the Rockstar Games Launcher / retail registry keys and the Windows
  uninstall entries. It only returns a folder that really contains `GTAIV.exe`.

  If **more than one** install is found it uses the first (Steam preferred) and warns
  — set `GamePath` explicitly to pick the other. If **none** is found, set `GamePath`
  by hand; don't let the harness run against a guessed path.
- `AsiPath` — the built precompiler `.asi`, if it isn't already in `plugins\`.
- **Toggle** — how to turn the precompile step ON/OFF:
  - Preferred `ToggleMode='ConfigKey'`: set `ConfigFile`/`ConfigSection`/
    `ConfigKey` to the precompiler's real INI setting. **If you don't know it,**
    open the FusionFix `.ini` in the game folder and look for a shader/precompile
    option (`Select-String -Path "<game>\plugins\*.ini" -Pattern 'precompile|shader'`).
  - Or `ToggleMode='AsiPresence'` if the precompiler is a standalone `.asi`
    (OFF just unloads it).

## Step 2 — Get PresentMon

```powershell
.\tools\presentmon\Get-PresentMon.ps1
```
Downloads the pinned PresentMon (MIT, Intel/MS) to `tools\presentmon\PresentMon.exe`.
If the download is blocked, tell the tester to grab it from
`https://github.com/GameTechDev/PresentMon/releases` and save it as that exact
path. **Record the printed SHA256** in your message so it's on the record.

## Step 3 — Collect hardware info

```powershell
.\run\Get-HardwareInfo.ps1 -Json .\results\raw\hardware.json
```
Report the GPU + driver, CPU, OS to the tester.

## Step 4 — Precompile **OFF** run (the cold baseline)

Run the phase; it deploys OFF, clears the shader cache, then pauses for the tester.

```powershell
.\run\Invoke-PrecompileTest.ps1 -Phase off
```

At the gates, instruct the tester precisely:
1. **Fully close GTA IV** (and the Rockstar launcher) before the cache is cleared.
2. After the cache clears, **launch GTA IV**, load a save, and **drive to the
   FIXED route start** you both agree on (see "Choosing a route" below). Keep the
   game **focused/foreground**.
3. When they confirm they're at the start, the capture begins and runs for the
   configured seconds (default 90). Tell them: **"Drive the route now, the same
   way you will on the second run."**

Output: `results\raw\off.csv`.

## Step 5 — Precompile **ON** run

**The precompile toggle only applies on the next launch**, so the game must be
fully closed and relaunched. Then:

```powershell
.\run\Invoke-PrecompileTest.ps1 -Phase on
```

Same gates, plus: after launch, the harness runs `Verify-Precompiler` — confirm
with the tester that the **"Building shaders…" overlay appeared** and that the log
shows ~1734 shaders. If it says **NOT verified**, the ASI may not have loaded —
fix the install before trusting the result (`.\run\Verify-Precompiler.ps1
-GamePath "<game>" -LogPath "<precompile log>"`). The tester drives the **same
route the same way**.

Output: `results\raw\on.csv` (+ `results\raw\verify.json`).

## Step 6 — Analyze (PASS/FAIL)

```powershell
.\run\Invoke-PrecompileTest.ps1 -Phase analyze
```
This runs `Analyze-FrameTimes.ps1 off.csv on.csv` → `results\raw\verdict.json`
and prints the A/B table + **VERDICT: PASS/FAIL** (exit 0/1). Summarize it for
the tester in plain language (how many spikes OFF, how many ON, p99.9 before/after).

> If the OFF run shows **no** spikes, the baseline never went cold (cache not
> cleared, or the driver pre-warmed) — the result is INCONCLUSIVE. Re-do Step 4
> ensuring the game was fully closed before clearing the cache, or pick a route
> that visits more first-time content.

## Step 7 — Build the shareable result

```powershell
.\run\Invoke-PrecompileTest.ps1 -Phase report
```
Produces **`results\result.md`** (the issue comment) + `results\result.json`.
Show `results\result.md` to the tester.

## Step 8 — Post it to the pinned issue (#1)

Prefer the GitHub CLI if available:

```powershell
gh issue comment 1 --repo emansom/gtaiv-precompile-test --body-file results\result.md
```
(Replace `1` if the owner pinned a different issue number; ask if unsure.)

If `gh` isn't installed or authenticated, tell the tester to:
1. open `https://github.com/emansom/gtaiv-precompile-test/issues/1`,
2. paste the contents of `results\result.md` into a new comment, and submit.

Confirm the comment posted. Thank them — every GPU/driver combo helps.

---

## Choosing a route (make it repeatable)

The two runs must cover the **same path** so their frame times compare. Good
route = one that triggers lots of **first-time** rendering on the OFF run:
- Start from a fixed, memorable spot (e.g. the first safehouse, or a specific
  landmark you can reach the same way each time).
- Drive a loop through a **dense area** (downtown Algonquin/Star Junction),
  changing direction so new geometry/effects load; if easy, fire a weapon or
  cause a small explosion once. ~90 s.
- Do it the **same way both times**. Exactness matters less than covering the
  same content cold; the analyzer's rolling baseline tolerates minor differences.

## Troubleshooting

- **"PresentMon produced no CSV"** — shell not elevated, or GTA IV wasn't
  presenting when capture started. Ensure admin + the game is in active gameplay.
- **CSV has few rows** — capture started before the game was running; relaunch
  the phase once GTA IV is in-world.
- **Locked files during cache clear** — the game/launcher/driver was still
  running. Fully close them and re-run the phase.
- **No Python needed.** Analysis is pure PowerShell. (A richer optional Python
  analyzer is in `python\` if the tester has Python — not required.)
- **Different PresentMon (2.x)** — pass `-PresentMon2` to `Capture-Frames.ps1`;
  the analyzer reads both the 1.x `msBetweenPresents` and 2.x `FrameTime` columns.

## Guardrails

- Only run scripts from this repo and the pinned PresentMon download. Don't modify
  the tester's GTA IV install beyond deploying the precompiler ASI + toggling its
  setting (the harness scripts do exactly that).
- Never fabricate numbers. If a step failed, say so and post nothing.

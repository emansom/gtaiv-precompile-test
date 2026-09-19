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

---

## Run 0: X0, the driver unit test (no game)

Run this before Run 1. It takes about a minute and needs no game, no DXVK, no
elevation and no toolchain. It is separate from the two game runs below.

It answers one question by itself: **does AMD's Windows Vulkan driver refuse to
fast-link a pixel shader that declares `PointCoord`?** DXVK's shader compiler declares
it in every GTA IV pixel shader. If the answer is yes, every new pipeline on this driver
is a full compile. The Linux side calls this hypothesis H0.

```powershell
.\run\Invoke-X0.ps1
```

It runs the prebuilt `tools\x0-llpc-pointcoord\x0.exe` three times, each with a fresh
AMD pipeline-cache folder, and writes `results\raw\x0.json`.

- **Check the printed sha256** against `tools\x0-llpc-pointcoord\README.md` first. A
  stale `x0.exe` still runs; it just tests the wrong thing.
- **Close GTA IV first.** It does not break X0, but it competes for CPU.
- **Report two lines to the tester:** the last one (`X0 VERDICT: ...`) and the
  `driverInfo` line. That README explains the verdicts. Do not analyse further; the
  Linux side reads the JSON off the mount.

---

## Run 1 of 2: the shader-cache run

There are **two** runs in this file and both are wanted. This one is short and comes
first; the PresentMon stutter A/B (Step 0 onwards, below) comes after and reuses the
same install, saves and DXVK setup, so its marginal cost is small.

They answer different questions:

- **This run** — does this machine resolve the same shader directory, and what
  pipeline keys does it produce? If it resolves a *different* directory, caches
  cannot be pooled across machines at all, which changes what the project ships.
  That is why it goes first.
- **The A/B** — does precompiling actually remove in-gameplay stutter here? That is
  the whole reason the precompiler exists, and it is **still unanswered on Windows**.

Do this one, then that one. If only one is possible, do this one and say so — but do
not treat the A/B as optional busywork; it is the outstanding validation.

1. **Clone both repos.** This one, and `emansom/GTAIV.EFLC.FusionFix` at branch
   **`shader-precompile-cache`** (not `shader-precompile`, an older diverged line).
   Read [`HANDOFF.md`](HANDOFF.md) for the why.
2. **Find the game** — confirm the path *before* anything writes to it:
   ```powershell
   .\run\Find-GtaivInstall.ps1 -Json .\results\raw\installs.json
   ```
   Its Steam VDF parsing is verified against real data; its **registry reads have no
   test coverage**. If the answer looks wrong, set `GamePath` by hand.
3. **Install the latest DXVK** — 32-bit `d3d9.dll` beside `GTAIV.exe`. Confirm a
   `GTAIV_d3d9.log` appears on launch. No log = native D3D9 = do not collect.
4. **Deploy** into `<game>\plugins\`:
   - `prebuilt\GTAIV.EFLC.FusionFix.asi` — already built from that branch, so no
     toolchain needed. **Check it is not stale first** (`prebuilt\README.md` has the
     commit and hash); a stale ASI still appears to work and would silently measure
     the wrong build.
   - `cache\linux-amd-dxvk\FusionFix.pipelinecache.baseline.bin` — the baseline
     **only**, see that folder's README for why not the full capture.

   The current ASI uses **cache format v2**. On first launch it moves any older
   capture in `plugins\` aside as `FusionFix.pipelinecache.f21-ms0.bin.unmerged` and
   starts a new one; the log says so. That is expected, not an error. To continue
   the first Windows session's capture instead, create `plugins\pipelinecache\` and
   copy `cache\windows-amd-dxvk\FusionFix.pipelinecache.f21-ms0.bin` into it before
   launching. That folder is where caches from a player's other PCs go: the replay
   warms them and capture merges them in. Note which you did.

   If GTA IV does not already have FusionFix installed, deploy the branch's
   `data\plugins\` and `data\update\` first, then overwrite the `.asi`.
5. **Install the saves.** Launch GTA IV once and quit (that creates the profile
   folder), then:
   ```powershell
   .\run\Install-Saves.ps1
   ```
   This matters for the measurement, not just convenience: if Windows starts
   somewhere else in the world, a difference in the key sets could be a genuine
   platform difference *or* just different scenery, and the experiment cannot tell
   those apart. Same save, same starting point, clean comparison.
6. **Check the frame limit matches.** The Linux rig runs FusionFix's **75 FPS** cap
   (`FpsLimitPreset = 8` in `plugins\GTAIV.EFLC.FusionFix.cfg`). Set the same on
   Windows. It does not change which pipeline keys are recorded, but it does change
   frame pacing, so leaving them different would make any timing comparison
   meaningless.
7. **Run once** with `PrecompileShaders = 1` and `CaptureDrawKeys = 1`. Load a save,
   drive a few minutes, quit **through the pause menu** (never kill the process).
8. **Optionally run again** with `PrecompileShaders = 0` for a clean coverage
   capture — at `1`, most of what gets recorded is the replay's own draws.

**Do not analyse the result here.** The owner mounts this partition from Linux and
reads `plugins\FusionFix.pipelinecache.f*-ms*.bin`, `plugins\FusionFix.shaders.log`,
`GTAIV_d3d9.log` and the Claude Code transcript directly. The line that decides
the experiment is `shader directory in use:` in the log.

The replay's `no-shader` count **is** a portability check again, since build `567b3cb`.
Cache files no longer carry the game's `.fxc` shader bytecode, so a key naming a
game shader this install does not have is skipped and counted there. With the
shipped baseline on this FusionFix-release install, **expect exactly 4**: they name
the branch's newer `gta_radar` shader. Report the number; anything well above 4 is
worth flagging.

**Then continue to Run 2**, the PresentMon stutter A/B below, while the game is set
up and the saves are in place. Keep the cache file produced above — it is what that
A/B's ON run will be warming from, so the two results describe the same pipeline set
and can be read together.

---

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

**Record whether `VK_EXT_graphics_pipeline_library` is active.** Grep the DXVK log
for `Graphics pipeline libraries`, and record the Vulkan driver too: the precompiler
logs it as `vulkan driver:`. How much GPL removes on its own **depends on the
driver**, so GPL being on does not tell you what to expect:

| stack | GPL | cold OFF | cold ON |
|---|---|---|---|
| Linux, RADV (Mesa) | on | +2 isolated spikes vs warm, i.e. almost nothing to remove | — |
| Windows 11, AMD proprietary | on | 56–68 spikes, ~18.4 s lost per 90 s | 12–19 spikes, ~5.0 s lost |

**A flat OFF run is only a real result if the run was provably cold.** Before you
report "nothing to fix", check that the DXVK log says `Created cache file`, not
`Found cache file`, and that `Clear-ShaderCache` reported every store empty. A warm
driver cache produces exactly the flat OFF run a GPL-friendly driver would. On
Windows it did: Steam's AMD `.parc` cache stayed warm and cut the OFF stutter
roughly 20-fold. If the run is provably cold and still flat, report it as "nothing
to fix on this stack" rather than retrying until it looks bad.

This does **not** affect the cache data: the keys are identical either way, so a
contributor never needs to change their DXVK config to contribute coverage.

---

# Run 2 of 2: the PresentMon stutter A/B

This is the measurement the precompiler exists to justify, and it has **never been
run on Windows**. Do it after the cache run above; the install, saves, DXVK and
`.asi` are already in place by then, so most of the setup below is already done.

## Step 0 — Preconditions (check, don't assume)

**Windows 11 only.** Windows 10 is legacy and is not a supported platform here; do
not collect a result from it.

Install the toolchain with winget (all four are needed; none require Administrator
to install):

```powershell
winget install Microsoft.WindowsTerminal     # the terminal to run everything in
winget install Microsoft.PowerShell          # PowerShell 7.x (pwsh), not Windows PowerShell 5.1
winget install Anthropic.ClaudeCode          # the CLI that drives this harness
winget install Intel.PresentMon              # frame-time capture
winget install Python.Python.3.13            # for tools\cache\*.py (cacheinfo etc.)
```

Then **reopen Windows Terminal as Administrator** and run `pwsh` there — PresentMon
captures via ETW and needs elevation, and the harness is run from PowerShell 7.

> **PresentMon: app vs CLI.** `Intel.PresentMon` installs Intel's PresentMon
> application. The harness drives the *command-line* `PresentMon.exe` at
> `tools\presentmon\PresentMon.exe`, which `.\tools\presentmon\Get-PresentMon.ps1`
> downloads at a pinned version. Run that too — the winget app is useful for a live
> overlay, but the pinned CLI is what produces the CSV the analyzer parses, and
> pinning is what keeps results comparable between machines.

Verify, and report what you find; stop and ask the tester if something's wrong:

```powershell
$PSVersionTable.PSVersion                      # expect 7.x
[System.Environment]::OSVersion.Version        # expect build >= 22000 (Windows 11)
# Elevated? PresentMon needs Administrator:
([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Get-Command gh -ErrorAction SilentlyContinue   # optional: lets you post automatically
```

- **Not elevated?** Tell the tester to reopen Windows Terminal **as Administrator**
  (right-click → Run as administrator). PresentMon captures via ETW and needs it.
- **Build < 22000?** That is Windows 10. Stop — it is not supported.
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
shows ~1706 shaders (FusionFix's stock set; more only if the install has extra `.fxc`
files). If it says **NOT verified**, the ASI may not have loaded —
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

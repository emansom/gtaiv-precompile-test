# Windows stutter A/B: the precompiler works here, and the harness had a false-negative bug

Run 2 (the PresentMon A/B) on the Windows side, 2026-09-19. This is the measurement
`HANDOFF.md` calls the outstanding validation. It had never been run on Windows.

Companion: `2026-09-19-windows-shaderdir.md` (Run 1, the cache run).

## Result: replicated, n=2 per arm

Driver + DXVK pipeline caches cleared before EVERY run. No overlays, `CaptureDrawKeys = 0`,
same TBoGT save and same downtown Algonquin / Star Junction route every time, 90 s.

| run | median | p99 | p99.9 | max | ISO spikes | stutter |
|---|---:|---:|---:|---:|---:|---:|
| OFF #1 | 13.32 | 16.07 | 26.36 | 72.45 | 18 | 343 ms |
| OFF #2 (control) | 13.32 | 19.12 | 44.10 | 168.15 | 26 | 879 ms |
| ON #1 | 13.32 | 14.85 | 16.81 | 75.85 | 3 | 81 ms |
| ON #2 (60 s settle) | 13.32 | 14.78 | 16.76 | 106.15 | 2 | 117 ms |

Mean: isolated compile spikes **22.0 -> 2.5 (-89%)**, lost frame time **611 ms -> 99 ms (-84%)**.

The cleanest signal is p99.9: the OFF arm swings 26.4 -> 44.1 ms between runs while the ON
arm lands at 16.81 and 16.76 against a 13.32 ms median shared by all four runs. In the
primary pair every one of the 18 mid-route OFF spikes (t = 16..56 s) disappeared and the ON
run is flat for 80 of its 90 s.

**`max` does NOT improve** (OFF 72.45 / 168.15 vs ON 75.85 / 106.15). Rare large outliers
survive in both arms and are probably GTA IV streaming hitches, not compiles. That is the
only reason the harness verdict is FAIL: it trips one gate, `isolated spikes <= 0`, because
2-3 remain. The other three gates pass.

## This contradicts the GPL expectation in CLAUDE.md

`CLAUDE.md` says that with `VK_EXT_graphics_pipeline_library` active there is largely
nothing to remove, citing +2 isolated spikes cold vs warm on Linux, and warns not to treat a
flat OFF run as a failure. **GPL is active here** (`Graphics pipeline libraries supported`)
and the cold OFF baseline still produced **18 and 26** isolated spikes, up to 168 ms against
a 13.3 ms median.

So "GPL on => nothing to fix" does not generalise from Linux/RADV to Windows/AMD-proprietary.
Worth softening that guidance: it currently tells a Windows tester to expect a no-op and to
report a flat OFF run rather than investigate it, which on this stack would have been wrong.

## MEASURED BUG in the harness: the cold baseline was not cold

`Clear-ShaderCache.ps1` did not clear **DXVK's own** pipeline cache. DXVK 2.x/3.x keeps it
per-application at:

```
%LOCALAPPDATA%\dxvk\<hash>.dxvk.bin   (+ .lut)
```

Measured here: **10 MB, 1728 shaders**, reported at startup as
`Found cache file: ... / Cache: 1728 shaders`. The script only looked for the DXVK **1.x**
`*.dxvk-cache` beside the executable, which 2.x dropped — so it always printed the reassuring
`absent ... (expected on DXVK 2.x)` while the real cache sat untouched.

Left in place, the OFF baseline starts warm, shows no spikes, and the A/B reads as a no-op —
**indistinguishable from the legitimate GPL-on "nothing to fix here" result**. That is a
silent false negative in exactly the configuration `CLAUDE.md` tells the tester to accept
without retrying. Fixed in `run\Clear-ShaderCache.ps1`.

Two further gaps found and fixed: `AMD\DX9Cache` (9.2 MB, 70 files) and `AMD\OglCache`
(36 files), neither in the vendor map. Note `AMD\VkCache` was **empty even mid-Vulkan-session**,
so it is not where the Windows AMD driver caches — do not rely on it as the tell.

Confirming the fix works: after clearing with the corrected script, the OFF control came back
at **26 isolated spikes / 879 ms**, i.e. MORE stutter than the first OFF run. Nothing survives
the clear.

## Rejected hypothesis: the residual spikes are not precompiler drain

The precompiler enqueues work that DXVK compiles asynchronously (the ini documents this:
"DXVK does not block a draw call on pipeline compilation, it enqueues the work"). In ON #1 all
three residual spikes sat at t < 10 s, which looked exactly like its own compilation spilling
past the loading screen into early gameplay.

Tested directly: repeated the ON run with a **60 s stationary settle** in-world before
capturing, so the compiler threads could drain. The spikes did **not** vanish — they moved
later into the route (t = 21.4 s, t = 78.2 s) and `max` got worse (106 ms). So it is not
drain, and no "hold the loading screen until the queue empties" change is justified by this
data.

## Precompile pass timing is NOT a proxy for compile work

Three passes, all with a freshly cleared DXVK cache:

```
Run 1   38.7 s   767 overlay frames  19.8/s   max frame gap 2997 ms
ON #1    7.2 s   230 overlay frames  32.1/s   max frame gap 3116 ms
ON #2    3.3 s   210 overlay frames  63.7/s   max frame gap   39 ms
```

The tester reasonably read the 3.3 s pass as evidence a cache had survived. It is not: the
duration is dominated by overlay refresh pacing and duplicate-state skipping (Run 1 skipped 0
duplicate-state draws; the ON runs skipped 1685), and the multi-second frame gaps look as much
like cold-file-cache disk stalls as compile stalls. The control run settled it empirically
instead. Do not infer cache state from pass duration.

## Harness bugs fixed to get a result at all

All three were unconditional — each one broke every run:

1. `Analyze-FrameTimes.ps1` — `Invoke-Analyze` built `$notes` but never returned it, while
   `Format-Report` reads `$rep.notes` under `Set-StrictMode -Version Latest`. Every analysis
   crashed.
2. `Invoke-PrecompileTest.ps1` — the analyze phase called `& Analyze-FrameTimes.ps1 $off $on`,
   but `-Logs` is `[string[]]` at Position 0, so the second path had no positional slot.
3. `New-ResultReport.ps1` — `N()` did `'{0:' + $fmt + '}' -f $v`; `-f` binds tighter than `+`,
   so it parsed as `'{0:' + $fmt + ('}' -f $v)` and threw "Format item ends prematurely".
   `N()` formats every number in the report.

Plus: `Deploy-Precompiler.ps1`'s `Set-IniKey` matched section headers with `^\[(.+)\]$`, but
FusionFix's ini documents itself with trailing `//` comments **on the section headers**
(`[SHADERS]   // Launch-time ...`). The end-anchored match never fired, so `$inSec` stayed
false, the key was never found, and the fallback appended a **second `[SHADERS]` section** —
leaving the original `PrecompileShaders = 1` intact while adding `PrecompileShaders=0` at the
end of the file. **The OFF run could have silently run with the precompiler ON**, and with a
GPL-on machine predicted to show no difference, that would have looked like a legitimate
result. Caught before the first capture; fixed by matching `^\[([^\]]+)\]` and preserving the
trailing comment.

Also pinned output formatting to invariant culture in the analyzer and report generator: this
tester's locale writes decimal commas, and `result.md` gets pasted into a public issue where
`94,83` reads as a different number.

## Environment notes for the next Windows tester

- **Close the Rockstar Games Launcher stack before launching.** With it left running from an
  earlier session, `GTAIV.exe` crashed at startup four times with `0xc0000005` at a fixed
  offset in `module: unknown`, before DXVK initialised (no new `GTAIV_d3d9.log`). Killing
  `Launcher`, `LauncherPatcher`, `SocialClubHelper`, `RockstarSteamHelper` and
  `RockstarErrorHandler` fixed it immediately. Not the upstream `caf11e5` page-fault
  signature (`read 6A535630 at PC 0x439651`) — that was **not** reproduced.
- **`UnlockFramerateDuringLoadscreens = 1` ruins a capture that starts too early.** GTA IV
  runs load screens uncapped (~2600 fps); one attempt had 70.3% of its frames sub-3 ms. Wait
  until the load screen fully finishes, then settle, then capture. Sub-3 ms frame share is a
  reliable contamination check.
- **Saves are episode-scoped.** `SGTA413` is "TLAD - Angels In America" and simply does not
  appear in the load menu unless you launch The Lost and Damned. The files were byte-identical
  to `saves/profile/` before and after every run; cloud sync never touched them. Worth adding
  to `saves/README.md`: installing the files is not enough, the matching episode must be
  launched.

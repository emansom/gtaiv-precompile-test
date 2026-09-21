# The re-sited warm pass: what four runs say, and why the session stopped early

The engine warm phase was moved off the first loading screen (where RAGE has no render
phases yet) to the return of `rageBoot_InitSession` — after the main menu and the
episode/DLC menu, with the game's own loading screen up and the engine's phases,
targets and state readable. This is the measurement of what that is worth on the driven
route, on the same rig and the same route as
`state/2026-09-20-linux-engine-warm-test.md`.

**Short answer: the gate does everything it was asked to do, the warming it produces is
the best measured so far over the part of the route that was measured — and both arms
that turned it on ended with the game dead a minute or two into gameplay.** That is the
result. It is n = 1 per arm, because the second of those deaths left the Proton session
in a state this agent is not permitted to clear, and no further launch was possible
(§7).

Build: `e3f42ce` in the FusionFix fork (`a532e24` re-sited the gate, `e3f42ce` is the
review pass over it), ASI sha256 `b8419b58c6840323…`, deployed and unchanged for all
four runs. Machine: Arch, KDE Plasma Wayland, RX 9070 XT (RDNA4), RADV Mesa 26.2.3,
GTA IV Steam Complete Edition 1.2.0.59 under GE-Proton11, DXVK 3.1.1, **graphics
pipeline libraries off**, Steam Shader Pre-Caching off. 4 runs, 2026-09-21 00:25–01:54.

## 1. Method, and what changed in the harness

One run = one launch driven along `lc-districts-v1`, started by
`run/linux/gameplay_run.py`, summarised by `run/linux/gpparse.py` — the 09-19/09-20
method exactly: recordings restored from `/tmp/ff-tools/snapshot` before and after,
`CaptureDrawKeys = 0` and `CaptureVulkanPipelines = 0`, drop-in folders emptied,
`~/.cache/mesa_shader_cache` emptied before every run (all four verified `cold`), the
ini edited by hand per condition and asserted by the runner.

Three harness changes were needed for this build and are committed with this note:

- **`gameplay_run.py` waits for the right line.** The boot gate ends with
  `gate: released after <s> s, <n> slices`; the old `gate: ran after` never appears, so
  without this every run would have failed at the pass timeout. `PASS_DONE` now covers
  the boot gate, its `FALLBACK` arm and the old line, and `PASS_NONE` covers
  `gate: the pass will not run from here` (the new give-up path) so a run is not left
  waiting for a pass that was abandoned.
- **The warm fingerprint is state.** `FusionFix.enginewarm.stamp` decides between the
  full pass and a 512-job probe, so a cold run that meets one is not a first launch. It
  (and `FusionFix.enginewarm.emitted.jsonl`) are now in `_state_files`, removed before
  and after every run; `--keep-state GLOB` / a condition's `"keep_state"` keeps one,
  which is how the repeat-launch arm is meant to be measured.
- **`gpparse.py` reads the new lines**: `gate_phases`, `gate_slices`, `gate_held_s`,
  `gate_fallback`, `gate_abandoned`, `eng_contexts`, `eng_ctx_shipped`, `eng_targets`,
  `eng_cheap`, `eng_probe_made`, `overlay_frames`, and `eng_jobs` for the reworded
  "level N emits …" line.

**The route did not need the menus driven.** This install autoloads straight into the
session, so `rageBoot_InitSession` fires by itself and the gate opens on the game's own
loading screen; the runner only has to wait longer. Every run's log shows the gate
firing there, at t ≈ 12–21 s after the device exists.

New condition `engine-only` (C10). The 09-20 `engine` arm could not isolate the phase,
because with `PrecompileReplayCapturedKeys = 0` the pass still ran the old synthetic
dummy-draw pass, which measured *worse than doing nothing*. `PrecompileCoverage = 0`
makes `DummyDrawPass` return on its first line, so C10 here is the engine walk with
nothing else warming — the arm 09-20 wanted and could not have.

| arm | `PrecompileShaders` | `Coverage` | `…ReplayCapturedKeys` | `ReplayVulkanPipelines` (+`…Foreign`) | `PrecompileEngineWarm` | runs |
|---|---|---|---|---|---|---|
| C1 `off` | 0 | – | – | 0 | 0 | 1 |
| C4 `full` | 1 | 2 | 1 | 1 | 0 | 1 |
| C10 `engine-only` | 1 | **0** | 0 | 0 | **1** | 1 |
| C11 `full+engine` | 1 | 2 | 1 | 1 | **1** | 1 |

## 2. The gate itself: everything it was asked for, it did

Identical in both engine runs, and matching the build's own smoke run:

- `gate: game viewport …, render phases 0 -> 27 (built here, by the engine's own vtable
  slot 12; its own build is now suppressed by the viewport's word[+0x404] guard)` —
  the phases exist at the gate, built by the engine's own code.
- `engine: 18 target-bearing render phases and 62 registry targets from the boot gate`
  → **18 contexts, 6 from phase sets, 9 from the registry, 3 shipped stand-ins** (each
  marked `<- SHIPPED` in the log). The axes that used to be guessed are read.
- Enumeration identical on every axis to the build's smoke run: 61,191 jobs after
  dedup; vs+ps 1499, proj 150, rt 4, blend 17, prim 3, spec0 6, psTypes 41, vsTypes 4,
  clip 2.
- **61,191 of 61,191 jobs drawn, 0 failed, 0 faulted, 0 no render target, 0 no
  declaration**, in both runs; `state verified: device handed back byte-identical
  across 58 render states, 20 samplers, shaders, streams (incl. frequency) and targets`.
- **`precompile complete … (0 overlay frames)`** — the progress is drawn into the
  game's own loading-screen frame and the pass presents nothing of its own. 68,894
  (C10) and 71,076 (C11) slices were lent to it by the loading-screen thread.
- No `FALLBACK`, no `gate: the pass will not run from here`, no fault, in any run.

So the mechanical part of the user's instruction — run after the engine has its render
phases, read the contexts from the engine, draw the progress inside the native loading
screen — is done and is reproducible.

## 3. Loading

| | C1 `off` | C4 `full` | C10 `engine-only` | C11 `full+engine` |
|---|---|---|---|---|
| launch → pass over (s) | 31.2 | **67.6** | **1015** | **1025** |
| gate held the loading screen (s) | – | 28.6 | 970.2 | 988.2 |
| … recorded D3D9 replay (s) | – | 15 | – | 15 |
| … engine warm draw loop (s) | – | – | **968** | **960** |
| … Fossilize replay, screen held (s) | – | 10.3 | – (none running) | 9.6 |
| loading-screen slices lent to the pass | – | 3248 | 68894 | 71076 |
| pipelines DXVK created before gameplay | 20 | 735 | **60838** | **61081** |
| … of those, compiles ≥ 5 ms | 2 | 562 | **34370** | **34543** |

The engine phase costs **+960 s (16 minutes)** on a first cold launch at level 1, which
is what the ini claims, and the pass is ~34,500 real driver compiles.

**The repeat-with-fingerprint cost was not measured here.** The warm-floor arm is the
one that meets a stamp, and it never ran (§7). The only number that exists for it is the
build's own smoke measurement — 7.0 s instead of 957 s, `PATH = CHEAP` — which is not
this harness's measurement and should not be quoted as one.

## 4. What each layer removes — the comparison all four runs support

Two of the four runs ended when the game died mid-route, so there are no route-window
numbers for them. What every log does have, at the same cadence, is vkcapture's
cumulative report every 15 s of play. Taken at the **same amount of gameplay** — about
60 s, which is the settle plus legs 1–3, the same warp and the same road in every run —
this is a like-for-like comparison of all four arms
(`run/linux/samewindow.py`, written for this and committed with it):

| at play ≈ 60 s | pipelines | ≥ 1 ms | **compiles ≥ 5 ms** | ≥ 20 ms | worst ms | **frames > 50 ms** | spikes | p99 ms | fps |
|---|---|---|---|---|---|---|---|---|---|
| C1 `off` | 365 | 362 | **275** | 143 | 43.8 | **34** | 54 | 45.1 | 67.4 |
| C4 `full` | 50 | 14 | **14** | 13 | 46.5 | **6** | 9 | 14.9 | 72.3 |
| C10 `engine-only` | 137 | 121 | **84** | 33 | 44.0 | **17** | 23 | 15.2 | 71.6 |
| C11 `full+engine` | **40** | 5 | **5** | 5 | 42.3 | **6** | 6 | 14.9 | 72.4 |

Read as containment applied to the run itself — how much of what C1 has to build cold
each arm had already built:

| | creations removed | compiles ≥ 5 ms removed |
|---|---|---|
| C4 `full` | 315 / 365 = **86 %** | 261 / 275 = **95 %** |
| C10 `engine-only` | 228 / 365 = **62 %** | 191 / 275 = **69 %** |
| C11 `full+engine` | 325 / 365 = **89 %** | 270 / 275 = **98.2 %** |

Every one of those `> 50 ms` counts includes the harness's own start warp
(`LOAD_SCENE`, a 1.4–1.9 s frame present in every condition), so C4's and C11's "6" are
really five ordinary long frames plus the warp.

For the two runs that finished the route, the route-window numbers are:

| over the whole route | C1 `off` | C4 `full` |
|---|---|---|
| DXVK pipeline creations | 402 | 96 |
| compiles ≥ 5 ms | 356 | 29 |
| creations ≥ 20 ms (one line each) | 154 | 26 |
| frames > 50 ms | 53 | 7 |
| worst route frame (ms) | 810 | 247 |
| route duration (s) | 300 | 304 |
| session spikes / p99 / avg fps | 108 / 15.3 / 73.1 | 19 / 15.0 / 74.4 |

## 5. Both engine-warm runs killed the game

| | C10 `engine-only` | C11 `full+engine` |
|---|---|---|
| gameplay before it died | 134.3 s | 71.3 s |
| how far the route got | end of leg 4, died in leg 5 (Broker Bridge) | leg 2 done, died in leg 3 (Rotterdam Hill) |
| how it died | process exited; Steam removed the app's processes at 01:01:50 | process became an **unreaped zombie**; its window stayed mapped as `GTAIV (Not Responding)`; Steam never removed the app |
| the route driver | exited with `InvalidOperationError: script has been destroyed` | hung on the dead frida link |

Both logs end with vkcapture's `gameplay frames final …` line, so the mod's exit path
ran in both: this is a process termination, not a hard kernel-level kill. There is **no
kernel OOM, no GPU reset, no coredump** in the journal for either moment; what the
journal does show is kmix re-enumerating its mixers at the second of death, i.e. the
game's audio device going away. Both non-engine arms (C1, C4) completed their routes
clean in the same session, on the same save, the same route and the same binary.

Two candidate causes, neither confirmed, both testable:

1. **Address space.** GTA IV is a 32-bit process and the pass leaves ~61,000 live DXVK
   pipelines behind it. The one number in the logs that measures this is vkcapture's
   free-address-space report at the start of the Vulkan replay:

   | | free address space at the Vulkan replay |
   |---|---|
   | C4 `full`, this session | 3088 MB |
   | C11 `full+engine`, this session | **2329 MB** |
   | C4 `full`, 09-20 (old gate) | 3193 MB |
   | C9 `full+engine`, 09-20 (old gate, 48,140 pipelines, pass *before* the session load) | 2597 MB |

   So the pass costs ~760 MB of address space here against ~600 MB on 09-20, and it now
   spends it *after* the session has loaded its world rather than before. 09-20's eight
   engine runs never died, which is the argument against this being the whole story —
   but it is 270 MB less headroom than the configuration that survived.
2. **The engine intervention.** The new gate asks `CViewportGame` to build its render
   phases and allocate its targets (0 → 27) and then suppresses the engine's own build
   through the viewport's `word[+0x404]` guard. That is the one thing the old gate never
   did, it is done **only** when `PrecompileEngineWarm > 0` — i.e. in exactly the two
   arms that died and neither that lived — and a death that arrives when the car reaches
   a new district is consistent with a phase or target that was built at the wrong
   moment.

The two are separable with runs this session could not make: an arm with
`PrecompileEngineWarm = 1` and `PrecompileGateMaxSeconds` set low enough to build only a
few thousand pipelines (phase build yes, address space no) against one with the phase
build suppressed and the full draw loop. Until one of those runs, **`PrecompileEngineWarm
= 1` cannot be recommended on this build**, whatever its warming is worth.

## 6. C4 also moved, and not in the direction the gate should move it

| C4 `full` | route creations | compiles ≥ 5 ms | route frames > 50 ms |
|---|---|---|---|
| 09-20, `4c85a78`, old gate, 4 runs | 42.3 (35–47) | 12.0 (8–15) | 2.75 (1–5) |
| here, `e3f42ce`, boot gate, 1 run | **96** | **29** | **7** |

n = 1 against n = 4, so this is a flag, not a finding. What can be said from the logs:
the recorded replay warmed **exactly the same set** — `replay: drew 1093 of 1093
pipelines`, same 14,543 keys, same two sources, same `13450 duplicate-state` — and the
Fossilize replay was identical too (`3351 entries created`, same five files). So the
difference is not in what the pass built. Pipelines created before gameplay fell 786 →
735, and 51 is about the size of the overlay's own pipelines: the boot gate presents
nothing of its own, so the backdrop, the font and the bar are never built. That accounts
for the fall, not for the rise in the route.

This wants two or three more C4 runs and, to separate the build from the session, one
`4c85a78` C4 in the same session.

## 7. Why the session stopped after four runs

C11's death left `PlayGTAIV.exe`, the Rockstar launcher, the Proton wrappers and Steam's
reaper alive with an unreaped `GTAIV.exe` zombie and a mapped "Not Responding" window.
Steam therefore still believes the app is running, and the next run's
`steam steam://rungameid/12210` did nothing: the runner waited five minutes and reported
`the game never started` (`full+engine/run2`, removed from the results so it does not
sit in the tables as an empty row).

Clearing that needs one of: ending the leftover `PlayGTAIV.exe`/`Launcher.exe`, a
`wineserver -k` on the prefix, or asking KWin to close the dead window. **All three were
refused by this agent's permission layer** (`[Interfere With Workloads]`), as was reading
process state with `ps -p`. The harness's own rule — never `kill`/`pkill` GTA IV, quit
only with the `gtaiv-quit` skill — does not cover a process that has already died, and
the quit skill needs a live game to write to. So the session ends here with one run per
arm.

**Everything else was cleaned up**: the ini is back to `/tmp/ff-tools/ini.pristine`
(`cmp`-identical), the snapshot recordings were restored by the runner after every run
and are `cmp`-identical to `/tmp/ff-tools/snapshot`, `plugins\d3d9cache\` and
`plugins\pipelinecache\` are empty, no `FusionFix.enginewarm.stamp` or
`…emitted.jsonl` is left, and the deployed ASI is the build under test.

## 8. The answers, as far as four runs can give them

**Does C11 reach zero?** No, and the route-level question is unanswered. Over the first
minute of the route — the only window all four arms share — C11 is the best arm ever
measured on this rig: **5 compiles ≥ 5 ms and 5 long frames besides the harness's own
warp**, against C4's 14 and 5, and C1's 275 and 33. That is 98.2 % of C1's compiles
removed, against C4's 95 %. But the run died in leg 3, so what happens in East Hook,
over the Broker Bridge and in Chinatown was not measured, and "zero stutter over a
five-minute route" was not tested.

**What is C10 worth alone?** Much more than the old engine arm, and not enough to
replace a recording. At the same window it removes **69 % of the compiles and 62 % of
the creations** against nothing warmed — 09-20's `engine` arm removed 19 % of the
session's compiles and 6 % of the long frames, and it was measuring the old table
contexts plus a synthetic pass that hurt. Reading the contexts from the engine is worth
that difference. But 84 compiles against C4's 14 in the same window means the recorded
cache is still six times better on its own, for 28.6 s of loading instead of 970 s.

**Loading cost, first run:** launch to gameplay **1015 s (C10) / 1025 s (C11)** against
67.6 s for C4 and 31.2 s for C1 — the pass itself is 960–970 s, of which ~34,500 driver
compiles. **On a repeat with the fingerprint skip: not measured here** (§3).

**Is the recorded cache still needed?** Yes, on every reading. C10 without it is 84
compiles where C4 is 14; C11 is C4 plus the phase, not the phase alone; and the 16 % of
a route's identities that belong to FusionFix's and other mods' own shaders are outside
any engine enumeration by construction.

Results are in `/tmp/ff-results-v2/<arm>/run1/` and copied to
`/tmp/ff-tools/enginewarm-v2-measure/` (tmpfs — copy anything worth keeping before a
reboot). Both crashed runs' `FusionFix.shaders.log` are there; they are the only
evidence of §5 besides this note.

## 9. What to run next, in order

1. **Two runs of `full+engine` with `PrecompileGateMaxSeconds` around 60–90 s.** The
   pass unwinds mid-flight (proven on 09-20), so the phase build happens and the address
   space does not fill. If the game still dies, it is the engine intervention; if it
   lives, it is the pipelines.
2. **Two more `full` runs** to say whether 96 / 29 / 7 is this build's C4 or one bad run,
   and one `4c85a78` `full` run in the same session as the control.
3. Only then the arms this task asked for and this session could not finish: C10 and C11
   to a completed route, ≥ 2 each, and the warm floor straight after a C11 run with
   `--keep-state FusionFix.enginewarm.stamp` on **both** runs.
4. If the phase survives all that, the level-2 question is still open and still costs
   about an hour of first load.

# Does the engine warm phase remove the stutter a recording cannot?

The engine-driven warm phase enumerates RAGE's own effect/technique/pass tables and
draws every permutation it believes the game can draw, so warming stops depending on
what somebody has already played. It is merged, correct and cheap to reason about —
this is the measurement of what it is worth on real gameplay, on the same route as
`state/2026-09-19-linux-realworld-stutter-test.md`.

Short answer: **with everything on it reaches the warm floor, and almost none of that
is the engine phase.** On its own the phase closes ~6 % of the gap to the floor in long
frames, for 7.7 minutes of extra loading. It builds 48 140 pipelines and about seven of
them turn out to be ones the route needed and the recording lacked.

Build: `4c85a78` in the FusionFix fork (the merged engine-warm + quick-wins work), ASI
sha256 `dd2794e2724e5a43`, deployed and unchanged for all 17 runs. Machine: Arch, KDE
Plasma Wayland, RX 9070 XT (RDNA4), RADV Mesa 26.2.3, GTA IV Steam Complete Edition
1.2.0.59 under GE-Proton11, DXVK 3.1.1, **graphics pipeline libraries off**, Steam
Shader Pre-Caching off. 17 runs, 2026-09-20 16:59–20:01.

## Method

Identical to the 09-19 session: one run = one launch driven along `lc-districts-v1`
(`run/linux/routes/lc-districts.json`), started by `run/linux/gameplay_run.py`,
summarised by `run/linux/gpparse.py`. Every run restores the player's recordings from
`/tmp/ff-tools/snapshot` before and after, has capture off (`CaptureDrawKeys = 0`,
`CaptureVulkanPipelines = 0`), empties `~/.cache/mesa_shader_cache` first unless it is a
warm arm, and is refused unless the ini's `[SHADERS]` keys match the condition. The ini
was edited by hand per condition and is back to `/tmp/ff-tools/ini.pristine`
(`cmp`-identical). Rounds were interleaved (C1 C4 C8 C9 C6, twice), then the
tie-breakers, then the two control arms.

| condition | `PrecompileShaders` | `…ReplayCapturedKeys` | `ReplayVulkanPipelines` (+`…Foreign`) | `PrecompileEngineWarm` | Mesa | runs |
|---|---|---|---|---|---|---|
| C1 `off` | 0 | – | 0 | 0 | cold | 2 |
| `synth` (control) | 1 | 0 | 0 | 0 | cold | 2 |
| C8 `engine` | 1 | 0 | 0 | **1** | cold | 2 |
| C4 `full` | 1 | 1 | 1 | 0 | cold | 4 |
| C9 `full+engine` | 1 | 1 | 1 | **1** | cold | 3 |
| `warm` (recorded floor) | 1 | 1 | 1 | 0 | **warm**, after a C4 run | 1 |
| C6 `warm+engine` | 1 | 1 | 1 | **1** | **warm**, after a C9 run | 3 |

Two arms the task did not ask for, both needed to read the result honestly:

- **`synth`** is C8 with the engine phase off. C8 cannot be run "engine only": the phase
  lives inside the `PrecompileShaders` pass, and with `PrecompileReplayCapturedKeys = 0`
  that pass still runs the old synthetic dummy-draw pass. Without this control, the
  synthetic pass's effect would be credited to the engine phase.
- **`warm`** is the recorded-only warm floor, the 09-19 C6, re-measured on this build so
  "reaches the floor" can be checked against a floor from the same session. It ran
  straight after `full/run4` with no clearing.

Harness changes made for this session (committed with the report): `conditions.json`
gains `PrecompileEngineWarm` in `_defaults` and the four conditions above; `gpparse.py`
gains the engine phase's lines (`eng_jobs`, `eng_drawn`, `eng_draw_s`, `eng_off`,
`eng_capped`, …) and its `faults` regex no longer counts the phase's own
"0 faulted" as a fault.

Run quality: **17 of 17 routes completed and were clean** — no deviation, no freeze, no
loss of focus, no hang inside a route. Every run with the pass logged `state verified:
device handed back byte-identical…`, none logged `state NOT restored`, and no run
logged a fault. Every cold run's `cold_verified` is true. The engine phase drew
`58515 of 58515 jobs (0 failed, 0 faulted, 0 no render target, 0 no declaration)` in all
eight runs that had it, and its enumeration was identical every time: 112 effects
(112 joined to .fxc), 1696 techniques (1696 by index, 0 by hash, 0 unmatched), 1809
passes, 912 VS + 1064 PS, 1864 of 1864 shader objects read, 14 render-target sets,
29 vertex declarations, 33 state vectors, 58 515 jobs after dedup, never capped.

## Results

Means over the runs of a condition, range in brackets. "Compiles" are DXVK pipeline
creations of ≥ 5 ms. Route rows count only what happened inside the route window, so the
harness's own start warp (a 1.4–1.7 s `LOAD_SCENE` frame present in every condition) is
excluded, as on 09-19.

| | C1 `off` | `synth` | C8 `engine` | C4 `full` | C9 `full+engine` | `warm` | C6 `warm+engine` |
|---|---|---|---|---|---|---|---|
| runs | 2 | 2 | 2 | 4 | 3 | 1 | 3 |
| **loading** | | | | | | | |
| launch → pass done (s) | 29.7 | 161 | **624** | 58.0 | **519** | 33.2 | **117** |
| pass total (s) | – | 134 | 596 | 30.3 | 490 | 5.5 | 89.6 |
| … engine phase draw loop (s) | – | – | 460 | – | 457 | – | 81.3 |
| loading screen held for the Vulkan replay (s) | – | – | – | 9.8 | 9.6 | 1.2 | 1.2 |
| quiet waits (s, summed) | – | 53.9 | 1.0 | 2.0 | 2.0 | 2.0 | 2.0 |
| **before gameplay** | | | | | | | |
| pipelines DXVK created | 20 | 9033 | 55966 | 786 | 48140 | 787 | 48140 |
| of those, compiles ≥ 5 ms | 1 | 5457 | 21967 | 620 | 16769 | 0 | 0.7 |
| **in the route** | | | | | | | |
| DXVK pipeline creations | 414 | 438 | 320 | 42.3 | 35.7 | 72 | 41.0 |
| **compiles ≥ 5 ms** | **367** | **395** | **291** | **12.0** | **6.0** | **13** | **4.7** |
| **in the session** | | | | | | | |
| compiles ≥ 5 ms | 409 (403-415) | 440 (429-450) | 333 (309-357) | 12.0 (8-15) | 6.0 (1-11) | 13 | 4.7 (1-7) |
| compiles ≥ 20 ms | 233 | 252 | 168 | 10.3 | 4.7 | 13 | 4.0 |
| worst compile (ms) | 47.6 | 49.1 | 48.7 | 43.6 | 35.7 | 45.8 | 40.2 |
| **frame times** | | | | | | | |
| **route frames > 50 ms** | **58.5** (56-61) | **70.5** (67-74) | **55.0** (54-56) | **2.75** (1-5) | **1.67** (0-3) | **4** | **1.67** (0-4) |
| … per 100 s of route | 18.2 | 25.6 | 17.3 | 0.94 | **0.54** | 1.43 | **0.55** |
| … with a DXVK creation behind them | 57.0 | 68.5 | 53.5 | 2.50 | 1.33 | 4 | 1.00 |
| worst route frame (ms) | 506 | 447 | 346 | 225 | 199 | 232 | 122 |
| session spikes | 120 | 128 | 109 | 10.0 | 8.0 | 9 | 8.3 |
| p99 (ms) | 15.3 | 15.5 | 15.25 | 14.9 | 14.93 | 14.9 | 14.9 |
| average fps | 73.1 | 72.7 | 73.5 | 74.45 | 74.53 | 74.5 | 74.5 |
| route duration (s) | 321 | 276 | 319 | 294 | 307 | 279 | 302 |

"With a creation behind them" uses the 09-19 rule: a creation counts as behind a frame
when it started inside the frame's own span or in the 0.5 s before it
(`scratchpad/behind.py`, one run at a time).

## Conclusion

**C9 reaches the floor.** Everything on, cold: 6.0 compiles and 1.67 route frames over
50 ms, against its own warm floor of 4.7 and 1.67 measured immediately after it
(`warm+engine`), and against the recorded-only warm floor of 13 and 4 measured in the
same session (09-19 read 11.3 and 3.0). Per 100 s of route the two are 0.54 and 0.55
long frames: the same number. One of the three C9 runs had **no** frame over 50 ms
inside the route at all, which no run of any other cold condition managed.

**But almost none of that is the engine phase.** C4, the shipping default, is already at
0.94 long frames per 100 s. C9's improvement over it — 12 → 6 compiles, 2.75 → 1.67 long
frames — points the right way in all three pairs but sits **inside the run-to-run
spread** (C4 8–15 compiles, C9 1–11; C4 1–5 long frames, C9 0–3; a rank test on n = 4
against n = 3 does not separate them). What the numbers do support is the weaker, still
useful claim: with the phase on, the cold route is statistically indistinguishable from
a warm cache, and C4 is about 1.7× the floor.

**C8 on its own closes essentially nothing.** 55.0 route long frames against 58.5 with
nothing warmed at all: **6 %**, or 5 % once normalised per 100 s (17.3 vs 18.2). Compiles
fall 409 → 333, 19 %. For reference the recorded replay alone was worth −77 % on 09-19.
Against its own control the phase looks better — `synth`, the same pass with the phase
off, is *worse than doing nothing* (70.5 long frames, 25.6 per 100 s), so the engine
phase removes 15.5 of the long frames the synthetic pass adds — but the net against C1 is
nil. On a machine with no recording, this phase is not a substitute for one.

**The mechanism is visible in the route's own creations.** The route makes DXVK create
414 pipelines when nothing is warmed. The engine phase, 58 515 draws and 48 140 pipelines
later, removes 94 of them (23 %). The recorded replay, 1093 draws, removes 372 (90 %).
Together they remove 378 (91 %) — the phase's marginal contribution on top of the
recording is about **7 pipelines**, and it pays 16 769 driver compiles for them. The
route's residue is not in the engine's cross product.

**Why, on this install, is not a mystery.** Every engine run logs
`engine: 0 render phases after waiting 2003 ms`: at FusionFix's gate the render phases do
not exist yet, so 12 of the 14 render-target/depth sets are the shipped constant table,
and at level 1 only 4 of the 33 state vectors are used (`forward` 56 472 jobs,
`gbuf_std` 860, `gbuf_alphaclip` 451, `depthonly` 732). The axes the effect system cannot
see — render-target and depth formats, the blend and write-mask half of the state — are
exactly the ones this enumeration is still guessing, and they are what a pipeline key is
mostly made of. The phase is drawing the game's real shaders through the wrong frame.

**Loading cost.** The engine phase costs **+461 s** on a cold first launch (58.0 → 519 s,
that is 7.7 minutes) and **+84 s** on a warm one (33.2 → 117 s). Of the cold 457 s,
about 80 s is the draw loop itself (the warm arms run the identical 58 515 jobs in
81 s); the other ~376 s is the driver compiling 16 769 pipelines. At C9's measured gain
that is roughly 77 s of loading per gameplay compile removed, and about 420 s per route
frame over 50 ms removed. C8 is worse still: 624 s of loading to remove 3.5 long frames.

**Recommendation.** Leave `PrecompileEngineWarm = 0` as it ships. The phase is correct,
survivable and reproducible — 8 runs, 58 515 of 58 515 jobs, no fault, no state leak, no
visible artefact — but on this rig it does not buy measurable smoothness on top of the
recorded replay, and it does not replace the replay. The one number that would change
this verdict is the render-target axis: the open issue from the engine-warm branch
(move the gate past `ragePhase_CreateAllPhasesAndTargets` @ `0x00B00B60`, so the sets and
the phase state come from the engine instead of a constant table) is the change that
would make the enumeration key-accurate. Level 2 (the other 29 state vectors) is the
other untested lever, and at level 1's 460 s it would cost tens of minutes.

## Notes and caveats

- **The C4 baseline moved.** On 09-19 C4 was 27.3 compiles / 6.25 long frames; here it is
  12.0 / 2.75 over four runs. Same route, same recordings, same conditions — what
  changed is the build: `4c85a78` carries the quick-wins vertex-sampler mask, which
  collapses the replay from 2421 to 1093 drawn pipelines, and the merge's state work.
  So the target quoted for this session ("27.3 and 6.25") is not the number C4 produces
  on the build under test, and every comparison above is against this session's own C4.
- **The `synth` control is n = 2 and its route was short** (276 s both runs). Its long-frame
  figure is above C1 both per run and per 100 s, so "the synthetic pass is worse than
  nothing" is what the data says, but it rests on two runs.
- **C8's loading screen is pathological.** The phase probe, which waits 2.0 s in every
  C9/C6 run, waited 96.2 s and 50.9 s in the two C8 runs, and the overlay logged frame
  gaps of up to 96 s. The synthetic pass ahead of it leaves DXVK's compiler queue
  saturated, and the probe's presents block behind it. It does not affect the phase's
  output (identical 58 515 jobs), only C8's loading time.
- **No Mesa cache eviction.** The cache peaked at 197 MB after a C8 run and 171 MB after
  a C9 run, well under Mesa's 1 GB default, so the engine phase's 22 000 compiles did not
  push the route's own entries out. A larger enumeration (level 2) would need this
  checked again.
- **`gp_pipes` and the route-window counters disagree slightly** because the session
  counters include the 15 s settle and the 20 s tail. The route-window rows are the ones
  to quote.
- Results are in `/tmp/ff-results-engine/<condition>/run<N>/` (tmpfs — copy anything
  worth keeping). The two foreign `.foz` files in `plugins\pipelinecache\` are deleted by
  the runner before every run; they were preserved and put back, `cmp`-identical, at the
  end of the session.

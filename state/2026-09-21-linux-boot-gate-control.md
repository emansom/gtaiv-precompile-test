# The boot gate and the default path: the control the last session asked for

`state/2026-09-20-linux-engine-warm-v2-test.md` left one flag up. The engine warm pass was
re-sited to the boot gate at `rageBoot_InitSession`, and at that gate the **default** arm —
`PrecompileEngineWarm = 0`, the shipping configuration — measured worse than it had on the
build before: 96 pipeline creations, 29 compiles and 7 long frames over the route against
42.3, 12.0 and 2.75. One run against four, and unexplained, so the note called it a flag
rather than a finding and asked for repeats plus a control on the old build.

**This is that control, and the flag is a finding.** Three runs of each build, interleaved,
cold, same ini, same route:

| | `new` e3f42ce (boot gate) | `old` 4c85a78 (loading-screen gate) |
|---|---|---|
| DXVK pipelines before gameplay | **735, 735, 735** | **786, 787, 786** |
| route pipeline creations | **90.7** (81–99) | **44.7** (31–59) |
| route compiles >= 5 ms | **23.7** (22–25) | **12.0** (6–20) |
| route creations >= 20 ms | **20, 20, 20** | **8.3** (3–15) |
| route frames > 50 ms (quiet runs) | 5.5 (5–6) | 2.5 (2–3) |

Non-overlapping on creations and on the >= 20 ms count, three runs each, and the
before-gameplay number is the same integer in every run of a build. It is the build, not
the machine and not the route.

**What the difference is: 51 pipelines.** The boot-gate build leaves 51 fewer DXVK
pipelines built when it hands the loading screen back — and the route then builds them,
most of them in one place, the walk into the Cluckin' Bell. A fifth arm run here
(`pass-only`, below) rules out the obvious suspect and puts the cause inside the replay's
own draws.

## 1. Method

Two binaries, one game, one ini, runs interleaved `new, old, new, old, …`.

- **`new`** = `e3f42ce`, current HEAD of the fork's `shader-precompile-cache`: the boot
  gate. Built in `/tmp/ff-regr/new`, ASI sha256 `d679f76ae699de41…`.
- **`old`** = `4c85a78`, the control: the same pass at the loading-screen gate. Built in
  `/tmp/ff-regr/old`, ASI sha256 `80c99c47397e584d…`.

Both were built in this session from `/tmp` copies of the repo at those two commits, same
toolchain and flags (`./build-asi.sh /p:TrackFileAccess=false /maxcpucount:4`), never in
the main repo; both trees `git status`-clean at their commit with identical submodule
commits. The `new` binary is not byte-identical to the one the 09-20 note measured
(`b8419b58…`, 6 650 368 bytes against 6 649 856): the build path is embedded, and that is
the only difference the source can produce. Every number `new` produces here matches that
note's single run, which is the check that matters.

Condition `full` for every measurement run — the shipping default: `PrecompileShaders = 1`,
`PrecompileCoverage = 2`, `PrecompileReplayCapturedKeys = 1`, `ReplayVulkanPipelines = 1`
(+ foreign), `PrecompileEngineWarm = 0`, capture off. One ini for the whole session
(`/tmp/ff-tools/ini.pristine` with `CaptureDrawKeys` and `CaptureVulkanPipelines` at 0,
sha256 `bc7401b8…`), asserted by the runner before every run. Cold every run:
`~/.cache/mesa_shader_cache` emptied, `cold_verified` true in all eight; recordings
restored from `/tmp/ff-tools/snapshot` before and after; drop-in folders emptied;
FusionFix's state files (including `FusionFix.enginewarm.stamp`) removed before and after.
Route `lc-districts-v1`, `route_sha256 fdfc5649…`, the same route file, driver and goal
runner as the 09-19, 09-20 and 09-21 sessions — checked, not assumed. All eight routes
completed and are `clean`; no freeze, no focus loss, no respawn; the watchdog unstuck a
stalled car 0–3 times per run, evenly across both builds.

Results in `/tmp/ff-results-regr/{new,old}/`, with the driver and machine-load logs beside
them (tmpfs — copy before a reboot).

## 2. Per run

`before` is `created by DXVK before gameplay`; route columns count only what happened
inside the route window. "machine" is what the load sampler saw during the route
(§6): a foreign four-way MSVC build on this shared machine costs the game frame time
but not pipelines.

| build | run | launch→gameplay s | pass s | before | of those compiled | creations | compiles >= 5 ms | >= 20 ms | frames > 50 ms | spikes | p99 ms | fps | route s | machine |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| new | 1 | 63.6 | 28.5 | 735 | 564 | 92 | 24 | 20 | (261) | (300) | (61.9) | (62.6) | 291 | **foreign build** |
| new | 2 | 65.6 | 28.8 | 735 | 569 | 81 | 22 | 20 | 6 | 17 | 15.1 | 74.5 | 355 | quiet |
| new | 3 | 63.6 | 28.5 | 735 | 566 | 99 | 25 | 20 | 5 | 17 | 15.3 | 74.3 | 301 | quiet |
| old | 1 | 59.5 | 32.0 | 786 | 635 | 59 | 20 | 15 | (9) | (104) | (25.1) | (71.4) | 321 | build in the last 20 s |
| old | 2 | 57.6 | 30.2 | 787 | 620 | 31 | 6 | 3 | 3 | 8 | 15.0 | 74.5 | 291 | quiet |
| old | 3 | 107 | 73.5 | 786 | 710 | 44 | 10 | 7 | 2 | 25 | 15.5 | 74.2 | 306 | **build over the load** |

Bracketed frame-time columns met a foreign build and are not evidence of anything. Neither
is `old/run3`'s 107 s load and its 710 compiled-before-gameplay: a build ran across its
warm pass, which stretched the pass from ~30 s to 73.5 s and pushed creations over the 5 ms
line. Its **735/786 and its route numbers are unaffected**, which is the point of keeping
the two kinds of metric apart.

Means, three runs each: creations **90.7 (81–99)** against **44.7 (31–59)**; compiles
**23.7 (22–25)** against **12.0 (6–20)**; >= 20 ms creations **20 (20–20)** against
**8.3 (3–15)**. Over the two quiet runs of each build, frames over 50 ms are 5.5 against
2.5. With three runs each and no overlap on creations, a rank test gives the smallest p a
3-against-3 comparison can produce (1/20); the archived runs below make the question moot.

## 3. The pass does the same work in both builds

Every line the pass logs about what it warmed is identical, run for run, on both builds:

| | `old` 4c85a78 | `new` e3f42ce |
|---|---|---|
| recorded keys loaded | 14 543 from 2 files | 14 543 from 2 files |
| vertex-sampler mask | 2421 keys without it, 1093 with | 2421 without, 1093 with |
| D3D9 replay | `drew 1093 of 1093 pipelines` | `drew 1093 of 1093 pipelines` |
| skipped as duplicate state | 13 450 | 13 450 |
| own Fossilize recording | 765 entries created | 765 entries created |
| Fossilize replay, all files | 3351 entries created | 3351 entries created |
| device state handed back | byte-identical, 58 render states | byte-identical, 58 render states |
| overlay frames the pass presented | 1616 / 2351 | **0** |
| **DXVK pipelines when the foreign replay starts** | **1551** | **1500** |
| **DXVK pipelines before gameplay** | **786** | **735** |

Two things fall out of that table.

- `learned first` minus `before gameplay` is **765 in every run of both builds** — the own
  recording's entries, which are created through raw Vulkan and are not DXVK's own. So the
  pipeline count is already 786 / 735 when the D3D9 pass ends, and **nothing the game
  itself draws between the end of the pass and the start of gameplay adds a single
  pipeline** on either build. The whole difference is made inside the pass.
- The pass is asked to build exactly the same thing on both builds and builds it: same
  keys, same 1093 draws, same Fossilize entries. What differs is what those draws *become*.

## 4. The 51 are pipelines the route needs, and it needs them in one place

`run/linux/legsplit.py` (new, committed with this note) maps FusionFix's session clock onto
`route.json`'s legs. Cumulative creations / compiles at the end of each leg, the two quiet
runs of each build:

| leg | new/2 | new/3 | old/2 | old/3 |
|---|---|---|---|---|
| lancet → chinatown-north (driving, 8 legs) | 57 / 10 | 75 / 13 | 33 / 6 | 46 / 9 |
| cluckin-bell (the last drive) | 57 / 10 | 75 / 13 | 33 / 6 | 46 / 9 |
| counter (walk in) | 72 / 14 | 78 / 13 | 33 / 6 | 48 / 10 |
| eat | 72 / 14 | 87 / 13 | 33 / 6 | 48 / 10 |
| street (walk out) | **83 / 22** | **101 / 25** | **33 / 6** | **48 / 10** |

The on-foot segment — walk into the Cluckin' Bell, buy a Fowl Burger, walk back out — costs
the boot-gate build **+26 creations and +12 compiles** in each of its three runs (+32 / +12
in run 1), and the loading-screen-gate build **+0 / +0, +2 / +1 and +5 / +5**. The
driving part of the route differs by far less. So the missing 51 are not a random slice of
the pipeline space: they are largely the ones the interior, its props and its prompt need,
and the route meets them in a place where they hurt.

## 5. What in the gate move explains it — one candidate eliminated, one left

Ruled out by §3: the recorded key set, the replay's draw list, the vertex-sampler mask, the
Fossilize replay, and the engine phase (off in every run). `ReplayPass` is the same function
in the two builds apart from the budget check the boot gate needs.

That left two candidates, and they are separable by an arm with nothing to warm.

**Candidate 1 — the pass no longer presents.** At the loading-screen gate the pass owns the
frame loop and presents 1616–2351 frames of its own through the hooked device, each running
everything FusionFix does at present time. At the boot gate it presents nothing at all, by
design: `the pass presented 0 frames of its own (0 is correct on this gate) … 0 presents
were seen on the device, and the loading screen does not go through the hooked one`.

**The new `pass-only` condition tests exactly that** — the pass with nothing to warm
(`PrecompileCoverage = 0`, no recorded keys, no Fossilize replay, no engine phase), so what
is left is the pass's own scaffolding, and on the old gate its presents:

| | before gameplay | of those compiled | the pass | route creations |
|---|---|---|---|---|
| `off` (no pass at all, 09-21 archive) | 20 | 2 | – | 402 |
| `new` `pass-only` (boot gate, **0 presents**) | **20** | 1 | 1.3 s, 177 slices | 456 |
| `old` `pass-only` (old gate, **58 presents**, 24 text rebuilds) | **18** | 3 | 1.6 s | 439 |

**The pass's own presents build nothing.** 18 against 20 against 20 — the old gate's arm is
if anything one pipeline lower. Candidate 1 is dead: the 51 do not come from the overlay,
the backdrop, the D3DX font or anything the present path does.

**Candidate 2 — the replay's draws specialise differently, and it is the one left
standing.** A DXVK D3D9 pipeline is not keyed only on what the recorded key carries.
`D3D9SpecData` (dxvk 3.1.1, `src/d3d9/d3d9_state.h`) specialises on `vsBoolConstants` and
`psBoolConstants` — the shader `b#` registers — on `psIsShaderModel3`, and on the
fixed-function stage ops and args. `pipelinekeys.h` records none of those. The pass
therefore draws its 1093 identities with whatever the device happens to be holding, and the
two gates hand it different state: the first loading screen's, or the session loading
screen's with a full save/restore around every 8 ms slice. Same draws, different
specialisation, 786 pipelines or 735.

That is consistent with everything measured: the difference exists only when the replay
draws (§5's `pass-only` arms are identical), it is the same integer every run (a state
difference, not a race), and the pipelines it misses are ones real gameplay asks for in a
specific place (§4).

## 6. The same number from the archive: three builds, one column

The archived sessions say it from the other side. Same route, same route driver, same rig,
`full` in all three:

| build | gate | before gameplay | route creations | compiles >= 5 ms | route frames > 50 ms | runs |
|---|---|---|---|---|---|---|
| `141a876` (09-19/20) | loading screen | 735 | 91.8 (81–101) | 27.3 (18–39) | 6.25 (5–9) | 4 |
| `4c85a78` (09-20) | loading screen | **786** | **42.3 (35–47)** | **12.0 (8–15)** | **2.75 (1–5)** | 4 |
| `e3f42ce` (the v2 note) | boot gate | 735 | 96 | 29 | 7 | 1 |
| `e3f42ce` (here) | boot gate | 735 | 90.7 (81–99) | 23.7 (22–25) | 5.5 (5–6) | 3 |
| `4c85a78` (here) | loading screen | 786 | 44.7 (31–59) | 12.0 (6–20) | 2.5 (2–3) | 3 |

**735 goes with ~90 route creations and ~25 compiles; 786 goes with ~43 and ~12.** The
boot-gate build is not worse than the mod has ever been — it is back where `141a876` was.
What `4c85a78` gained, the boot gate lost. Somewhere between `141a876` and `4c85a78` the
vertex-sampler mask landed (2421 draws → 1093, and 735 → 786 pipelines): it taught the
replay to bind the sampler pattern each key really used, which is the one axis of DXVK's
specialisation the key *does* carry — and the boot gate has given back the equivalent of
that gain on the axes it does not.

## 7. Harness

Three things this session had to fix or record; all are committed with this note.

- **`route()` and `quit()` had no timeouts.** `route.py` drives the game over frida, and a
  game that dies mid-route can leave it hung on a destroyed script (09-21,
  `full+engine/run1`); the runner read the driver's stdout to EOF, so a dead game blocked
  the whole session. The route now runs under a supervising loop: `--route-timeout`
  (1800 s) ends it however far it got, and once GTA IV is gone the driver gets
  `--route-grace` (30 s) to write `route.json` itself before it is ended; `meta.json`
  records why in `route_killed`. One `gtaiv-quit` attempt gets `--quit-timeout` (60 s) and
  is retried as before. A live game is still only ever quit with the skill's memory write.
- **A foreign build wrecks frame times, and only frame times.** Several agents share this
  machine. A four-way MSVC build under Wine alongside a run cost the game 12 fps and put
  265 frames over 50 ms into `new/run1`'s route, in one 100 s burst that lines up exactly
  with the build's compile phase and has no pipeline creation behind any of it; another
  stretched `old/run3`'s warm pass from 30 s to 73.5 s. Creations and the before-gameplay
  count come through both untouched. Sample `/proc/loadavg`, `/proc/pressure/cpu` and
  `ps -eo comm= | grep -E '^(CL\.exe|msbuild)$'` every 10 s through a session and score each
  run's route window against it (`machine-load.log` beside the results here); throw the
  frame times of any run that met a build.
- **`flock /tmp/ff-build.lock ./build-asi.sh` leaks the lock.** The build's `wineserver`,
  `services.exe` and the rest of that prefix's daemons inherit the open descriptor and
  outlive the build, so the lock stays held by processes nobody is watching and the next
  build waits forever. `WINEPREFIX=$XDG_RUNTIME_DIR/fusionfix-msbuild-wine wineserver -k`
  frees it — that prefix is the build's, never the game's. Holding the lock does not in
  practice stop other agents building (two did so here while this session held it), so
  measure the contamination rather than trusting the lock.

New: `run/linux/legsplit.py` (where in the route a run built its pipelines) and the
`pass-only` condition.

## 8. What to do about it

1. **Record the specialisation the key is missing.** Put the `b#` register masks (and
   `psIsShaderModel3`, and the fixed-function stage state where it applies) in the pipeline
   key, capture them, and set them per draw in `ReplayPass`. That makes the replay build the
   same pipelines wherever the pass runs, which is worth having whatever the gate ends up
   being — and on these numbers it is worth ~12 compiles and ~3 long frames per route on the
   shipping default.
2. **Cheap confirmation first, if one is wanted**: log the current `b#` masks (and the FF
   stage ops) at the moment the pass starts, on both gates, on one run each. If they differ,
   §5's candidate 2 is proven rather than inferred, and the fix in 1 is the fix.
3. Until then the boot gate's default path is ~51 pipelines short of what `4c85a78`
   managed. That is not a reason to move the gate back — the gate is what makes the engine
   warm pass possible at all, and the loss is a recording/replay bug the gate merely
   exposed — but it should be fixed before the engine arm's own numbers are quoted against
   a default measured at either gate.
4. Only then is the engine arm's own question (the ~61 000 live pipelines and the two runs
   that killed the game) worth returning to.

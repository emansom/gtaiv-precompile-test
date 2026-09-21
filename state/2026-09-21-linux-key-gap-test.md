# The key gap, measured on the route: the boot gate's 51 pipelines are back

`state/2026-09-21-linux-boot-gate-control.md` measured a defect and named a fix: moving the
warm pass to the boot gate left DXVK with **735** pipelines instead of **786**, and the
route then built the missing ones — 90.7 creations and 23.7 compiles against the old
gate's 44.7 and 12.0, concentrated in the walk into the Cluckin' Bell. The fix landed on
`key-gap` and was merged; **this note is the route measurement that says whether it
recovered what the gate cost.**

**It did. The gap is closed.** Nine cold runs, three arms, interleaved, one ini, one route:

| | **new** `6cb1e33` boot gate + key fix | **old** `4c85a78` loading-screen gate (the number to recover) | **pre** `02e0182` boot gate, no fix (the number to beat) |
|---|---|---|---|
| DXVK pipelines when the pass ends | **786, 786, 786** | **787, 786, 786** | **735, 735, 735** |
| route pipeline creations | **44.0** (42–46) | 47.0 (34–54) | 86.3 (77–99) |
| route compiles >= 5 ms | **12.7** (10–15) | 13.0 (7–17) | 23.7 (18–30) |
| route creations >= 20 ms | **9.3** (7–11) | 10.3 (5–14) | 20.3 (14–26) |
| route frames > 50 ms | **2.3** (2–3) | 2.7 (2–3) | 5.7 (5–7) |
| **the Cluckin' Bell interior** (creations / compiles) | **+2.7 / +2.7** | +0.7 / +0.3 | **+31.3 / +13.0** |
| p99 frame time (ms) | 14.97 | 14.97 | 15.0 |
| avg fps over the route | 74.5 | 74.4 | 74.4 |
| launch -> gameplay (s) | 69.7 | 58.8 | 69.7 |
| the pass itself (s) | 30.3 | 30.3 | 28.6 |

The three answers the round asked for, plainly:

1. **Is the gap closed?** **Closed.** The new build matches the old gate on every route
   metric — marginally ahead on all four of them, well inside each other's ranges — while
   the unfixed boot gate is about double on every one. `new` and `pre` do not overlap on a
   single route column (creations 42–46 against 77–99, >= 20 ms 7–11 against 14–26, long
   frames 2–3 against 5–7), and the before-gameplay count is the same integer in every run
   of every arm.
2. **What does the replay now cost in loading time?** **+1.7 s**, on a ~30 s pass that
   sits inside a ~70 s load. The pass is 30.3 s (30.1–30.4) against 28.6 s (28.3–28.8)
   before the fix; the D3D9 draw phase alone is 17 s in all three new runs against 15 s in
   all three pre runs. Nothing else moved.
3. **Is the Cluckin' Bell interior fixed?** **Yes.** The on-foot segment — walk to the
   counter, eat, walk back out — cost the unfixed boot gate **+31.3 creations and +13.0
   compiles** per run (28/30/36 and 9/12/18, and 6 of the route's long frames across the
   three runs). On the fixed build it costs **+2.7 / +2.7** (1/1/6, one long frame in
   three runs) against the old gate's **+0.7 / +0.3**. The interior is no longer where the
   route builds its pipelines.

## 1. Method

`run/linux/gameplay_run.py`, condition `full` (the shipping default: `PrecompileShaders = 1`,
`PrecompileCoverage = 2`, `PrecompileReplayCapturedKeys = 1`, `ReplayVulkanPipelines = 1`
plus foreign, `PrecompileEngineWarm = 0`, capture off), route `lc-districts-v1`
(`route_sha256 fdfc5649…` — the same route file, driver and goal runner as the 09-19,
09-20 and 09-21 sessions), summarised with `run/linux/gpparse.py` and `run/linux/legsplit.py`.

Three binaries, one game, one ini, runs interleaved `new, old, pre, new, old, pre, …`
between 13:15 and 14:32 on 2026-09-21.

| arm | commit | what it is | ASI sha256 | built |
|---|---|---|---|---|
| `new` | `6cb1e33` (`shader-precompile-cache` HEAD) | the boot gate **with** the key fix — the shipping default | `e7814a64477aa8ab…` | the fork's own `bin/`, deployed unchanged |
| `old` | `4c85a78` | the loading-screen gate, before the boot gate existed | `80c99c47397e584d…` | the **same binary** the 09-21 control measured (`/tmp/ff-regr/asi/`) |
| `pre` | `02e0182` | the boot gate **before** the key fix | `771de239b1bbef61…` | `/tmp/ff-meas/pre`, `git status`-clean at that commit |

The `old` binary is deliberately the archived artifact of the 09-21 control rather than a
rebuild: it is the file that produced the number this round has to recover, so nothing
about the toolchain can have drifted under it. The `pre` binary was rebuilt here from a
clean tree (the 09-21 note's `e3f42ce` is the same gate one commit family earlier; `02e0182`
is what the round was commissioned against). All three agree on their inputs, below.

One ini for the whole session: `/tmp/ff-tools/ini.pristine` with `CaptureDrawKeys` and
`CaptureVulkanPipelines` set to 0 — sha256 `bc7401b82bf27af7…`, **byte-identical to the
ini the 09-21 control used**, asserted by the runner before all nine runs and never edited
between them. Every run cold (`~/.cache/mesa_shader_cache` emptied, `cold_verified` true in
all nine); recordings restored from `/tmp/ff-tools/snapshot` before and after each run;
drop-in folders emptied; FusionFix's state files removed before and after.

**All nine routes COMPLETED and are `clean`**: no freeze, no focus loss, no respawn, 0
deviations, 0 faults, every quit clean through the `gtaiv-quit` memory write. A 10 s
sampler took 612 samples across the session and saw **zero** `CL.exe`/`msbuild` in 608 of
them (`/tmp/ff-results-meas/machine-load.log`); the four non-zero samples are this session's
own control build, the last at 13:14:25, before run 1 launched at 13:15:45. Peak load
average during the runs was 5.25, which is the game. No frame time here met a foreign
build.

Results in `/tmp/ff-results-meas/{new,old,pre}/full/run{1,2,3}/` (tmpfs — copy before a
reboot).

## 2. Every run

`before` is `created by DXVK before gameplay`; the route columns count only what happened
inside the route window.

| arm | run | launch→gp s | pass s | gate | before | of those compiled | creations | >= 5 ms | >= 20 ms | frames > 50 ms | p99 ms | fps | route s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| new | 1 | 71.7 | 30.4 | 3328 slices | **786** | 610 | 46 | 10 | 7 | 2 | 14.9 | 74.6 | 347 |
| new | 2 | 69.7 | 30.3 | 3316 slices | **786** | 610 | 44 | 13 | 10 | 2 | 14.9 | 74.5 | 307 |
| new | 3 | 67.6 | 30.1 | 3287 slices | **786** | 606 | 42 | 15 | 11 | 3 | 15.1 | 74.4 | 292 |
| old | 1 | 59.5 | 29.9 | 1606 own frames | **787** | 625 | 53 | 17 | 14 | 3 | 14.9 | 74.5 | 321 |
| old | 2 | 59.5 | 30.9 | 1649 own frames | **786** | 633 | 34 | 7 | 5 | 2 | 15.2 | 74.3 | 276 |
| old | 3 | 57.5 | 30.2 | 1617 own frames | **786** | 615 | 54 | 15 | 12 | 3 | 14.8 | 74.5 | 305 |
| pre | 1 | 71.7 | 28.8 | 3266 slices | **735** | 564 | 83 | 23 | 21 | 7 | 15.0 | 74.3 | 306 |
| pre | 2 | 67.7 | 28.7 | 3242 slices | **735** | 563 | 77 | 18 | 14 | 5 | 15.0 | 74.4 | 298 |
| pre | 3 | 69.7 | 28.3 | 3180 slices | **735** | 565 | 99 | 30 | 26 | 5 | 15.0 | 74.4 | 341 |

**This session reproduces both archived controls.** The 09-21 note measured the broken boot
gate at 90.7 creations / 23.7 compiles / 20 over-20 ms / 5.5 long frames and the old gate at
44.7 / 12.0 / 8.3 / 2.5. This session's `pre` arm gives 86.3 / 23.7 / 20.3 / 5.7 and its
`old` arm 47.0 / 13.0 / 10.3 / 2.7, on a different day with a different `pre` binary. The
rig, the route and the effect are all where they were, which is what makes the third arm
readable.

## 3. The pass does the same work in all three builds

Every line about what the pass was asked to warm is identical in all nine runs:

| | new | old | pre |
|---|---|---|---|
| recorded keys loaded | 14 543 from 2 files | 14 543 from 2 files | 14 543 from 2 files |
| vertex-sampler mask | 2421 without, 1093 with | 2421 / 1093 | 2421 / 1093 |
| unique pipelines to build | 1093 (599 base + 494 variants) | 1093 (599 + 494) | 1093 (599 + 494) |
| D3D9 replay | `drew 1093 of 1093` | `drew 1093 of 1093` | `drew 1093 of 1093` |
| skipped as duplicate state | 13 450 | 13 450 | 13 450 |
| Fossilize replay, all files | 3351 entries created | 3351 | 3351 |
| **DXVK pipelines when the foreign replay starts** | **1551** | **1551** | **1500** |
| **DXVK pipelines before gameplay** | **786** | 786/787 | **735** |
| device state handed back | byte-identical | byte-identical | byte-identical |

Same keys, same 1093 draws, same Fossilize work — and 51 more pipelines out the other end,
on the second independent counter (`learned first`) as well as the first. The cost of those
51 is the 1.7 s in §5 and nothing else.

**The old hypothesis stays dead, in this session's own logs.** Both boot-gate builds print
what the device was holding when the pass started: `vsBools 0x0000 psBools 0x0000, texture
transform flags 00000000, stage ops (colour/alpha, 0-3) 4/2 1/1 1/1 1/1, … clip planes
enabled 0x0 non-zero 0x0 -> DXVK would count 0`, at the gate, at the first slice and at
slice 64 — **identical text in the `pre` and `new` runs**. The two builds do not meet
different ambient state; the fixed one stops inheriting it and writes the specialisation
state per draw. The axis that mattered was the clip planes: DXVK counts only planes that
are enabled *and* non-zero, the pass set six of them once in `CreateScratchResources`, and
at the boot gate the loading screen's `D3DSBT_ALL` block put them back between every 8 ms
slice — so from the second slice on, every clip-plane key built the same pipeline as its
no-clip sibling. 473 of the 14 543 keys carry a clip plane; collapsing that axis was
modelled at 61 of the 1093 identities and measures 51 on the GPU, the difference being the
identities the first slice and the synthetic coverage pass still reached.

## 4. Where the route builds them: the Cluckin' Bell interior is fixed

`legsplit.py`, cumulative creations / compiles at the end of each leg. The number that
matters is the last three rows — the on-foot segment where the 09-21 note found the gap
concentrated.

| arm / run | at the end of the drive (`cluckin-bell`) | at the end of the route | **the interior costs** |
|---|---|---|---|
| new 1 | 47 / 9 | 48 / 10 | **+1 / +1** |
| new 2 | 45 / 12 | 46 / 13 | **+1 / +1** |
| new 3 | 38 / 9 | 44 / 15 | **+6 / +6** |
| old 1 | 55 / 17 | 55 / 17 | +0 / +0 |
| old 2 | 37 / 7 | 37 / 7 | +0 / +0 |
| old 3 | 55 / 14 | 57 / 15 | +2 / +1 |
| pre 1 | 57 / 14 | 85 / 23 | **+28 / +9** |
| pre 2 | 49 / 6 | 79 / 18 | **+30 / +12** |
| pre 3 | 65 / 12 | 101 / 30 | **+36 / +18** |

Frames over 50 ms inside the interior, over the three runs of each arm: **new 1, old 0,
pre 6**. The three `pre` runs put 8, 9 and 0 of their `>= 20 ms` creations in the `counter`
step alone; the three `new` runs put 1, 0 and 0 there.

The segment that used to be 36 % of the boot-gate build's route creations is now 6 % of a
route total that is itself half the size. What is left on the new build is spread over the
drive — the first two legs (Lancet and the Algonquin Bridge) carry 4–5 of the `>= 20 ms`
creations in eight of the nine runs, `old` and `pre` included — which is where the shipped
default has always had it.

## 5. What the fix costs in loading time

| | new | pre | difference |
|---|---|---|---|
| D3D9 replay draw phase | 17 s, 17 s, 17 s | 15 s, 15 s, 15 s | **+2 s** |
| whole pass (`precompile complete in`) | 30.4, 30.3, 30.1 | 28.8, 28.7, 28.3 | **+1.7 s** |
| launch → gameplay | 71.7, 69.7, 67.6 | 71.7, 67.7, 69.7 | **0** |

Per-draw specialisation state — bool constants, clip planes, the projected/texture-stage
block and the sampler modes, re-applied after every slice boundary — costs 2 s across 1093
draws and 13 450 skipped keys, and it disappears into the load: launch→gameplay is the same
~70 s either way. Against the user's standing rule (gameplay smoothness matters, loading
time does not) this is free.

The `old` arm loads **11 s faster to gameplay** (58.8 s against 69.7 s) while running the
same 30 s pass. That is the gate's position, not the fix: the boot gate sits past the
frontend and the episode menu, so the game walks further before the pass starts. `pre`
loads exactly as slowly as `new`.

## 6. Statistics, such as they are

Three runs per arm, interleaved, cold, one ini, one route. `new` against `pre` does not
overlap on creations (42–46 against 77–99), on `>= 20 ms` creations (7–11 against 14–26),
on route frames over 50 ms (2–3 against 5–7) or on the interior cost (1–6 against 28–36);
a 3-against-3 rank test gives the smallest p such a comparison can produce, 1/20. `new`
against `old` overlaps on everything, which is the point: the arms are indistinguishable
and the fixed build's ranges are the tighter of the two (creations 42–46 against 34–54).
The before-gameplay count is not statistics at all — it is the same integer in every run of
every arm, and it is the number the fix was aimed at.

## 7. The bonus arm: what the key fix does to the engine warm pass

One cold `full+engine` run on the new build, after the nine (14:32–14:55, route COMPLETED
and clean, 0 faults). Against the same arm measured on `02e0182` in
`state/2026-09-21-linux-engine-warm-v3-test.md`, which is the build this round's `pre` arm is:

| | `02e0182` + engine (2 runs) | **`6cb1e33` + engine (1 run)** | `6cb1e33` default (3 runs) |
|---|---|---|---|
| gate held | 967 s | 973 s | 30.3 s |
| jobs walked | 61 191 | 61 191 | — |
| pipelines before gameplay | 61 725 | 61 776 | 786 |
| route creations | 110 (103–117) | **41** | 44 (42–46) |
| route compiles >= 5 ms | 19 (12–26) | **9** | 12.7 (10–15) |
| route creations >= 20 ms | 16.5 (10–23) | **3** | 9.3 (7–11) |
| route frames > 50 ms | 5.5 | 4 | 2.3 (2–3) |
| the Cluckin' Bell interior | — | +2 / +1 | +2.7 / +2.7 |

**The key fix changes the engine arm as much as it changes the default.** Before it, the
engine walk's route numbers were *worse* than its own default's on creations (110 against
90.5) — 61 725 pipelines warmed and the route still built 110, because the walk's 1093
recorded-key draws were specialising the same wrong way. After it the same walk leaves 41,
and the `>= 20 ms` creations — the ones that are actually a compile the player can feel —
fall from 16.5 to 3, the lowest number any cold arm has produced on this route.

That is **one run**, and it is the only number in this note with an n of 1. It does not
change the v3 note's verdict (973 s of loading for a difference the default arm mostly
already has: 41 against 44 creations, 9 against 12.7 compiles), but the `>= 20 ms` column
is the one that was worth 3 against 9.3 here, and it deserves the three runs this session
did not have time for. The address space still comes back: the gameplay floor was 1825 MB
free, no fault, clean quit.

## 8. What this does not show

- **Windows is untouched.** Every number here is Linux / Proton GE-Proton11 / DXVK 3.1.1 /
  RADV Mesa 26.2.3 on an RX 9070 XT, graphics pipeline libraries off.
- **One route, one save, one episode.** The route is `lc-districts-v1` in TBoGT (this
  install autoloads it); the interior finding is about the Cluckin' Bell in The Triangle,
  which is the place the 09-21 note found the gap in. Another interior may hold pipelines
  no arm here has warmed.
- **The engine arm is one run** (§7). Everything else is three.
- **The replayed data is still v2-widened.** The 14 543 recorded keys predate the v3
  specialisation fields, so `clipPlaneCount` is the only new field carrying real values in
  these runs; the others sit at their widened defaults. A v3 capture exists now
  (`/tmp/ff-tools/v3capture/`) and says those defaults are what this install records
  anyway, but a re-measured route on a genuinely v3 corpus has not been run.
- **Results live in `/tmp/ff-results-meas`** (tmpfs) — copy them before a reboot. The
  control binaries are in `/tmp/ff-meas/asi/`.

## 9. Harness

No harness change was needed: `gameplay_run.py` already had the timeouts the task asked
about (`--route-timeout` 1800 s, `--route-grace` 30 s, `--quit-timeout` 60 s, from the
09-21 session), and they were not exercised — every run finished on its own.

Two notes for whoever measures next:

- **`flock /tmp/ff-build.lock ./build-asi.sh` still leaks the lock**; `flock -o` (close the
  descriptor before exec) is the fix the integration session found, and it worked here —
  the control build held and released the lock cleanly, with `fuser` clean afterwards.
- **Waiting on a background run with `pgrep -f "<marker>"` matches the waiting shell
  itself.** Nine minutes of this session were spent watching a loop wait for its own
  command line. Wait on a marker *file* or on `tail --pid`.

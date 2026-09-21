# The engine warm pass, measured again: it is safe now, and it still should not ship on

Ten runs, one rig, one route, one binary, 2026-09-21 07:22–09:35. The question this round
had to answer is the one the 2026-09-20 note could not: the engine-driven warm phase
(`PrecompileEngineWarm = 1`) killed the game twice in gameplay on build `e3f42ce`, and the
fix — give the walk a D3D9 device of its own and rotate it every 8192 jobs — had been
measured once. **It does not kill the game any more. Seven engine-arm launches drove the
whole route and quit cleanly, with no fault of any kind logged.** The address space it
takes comes back, with one qualification that matters and is quantified below.

What it is *worth* is a smaller number than the last two notes implied, and that is the
part of this report that changes a decision.

Build under test: `02e0182` in the FusionFix fork (`shader-precompile-cache`), ASI sha256
`bccc1fb94849d75e…`, built in `/tmp/ff-m` (embedded PDB path confirms it) from a tree clean
at that commit, deployed unchanged for all ten runs. Machine: Arch, KDE Plasma Wayland, RX
9070 XT (RDNA4), RADV Mesa 26.2.3, GTA IV Steam Complete Edition 1.2.0.59 under
GE-Proton11, DXVK 3.1.1, graphics pipeline libraries **off**, Steam Shader Pre-Caching off.
No foreign compiler ran on this machine during the session: a 10 s sampler took 818
samples and every one reported zero `CL.exe`/`msbuild`
(`/tmp/ff-results-v3/machine-load.log`). Peak load average was 5.16, which is the game.

## 1. Method

`run/linux/gameplay_run.py` per run, route `lc-districts-v1`, summarised by
`run/linux/gpparse.py` and `run/linux/legsplit.py` — the 09-19/09-20/09-21 method exactly.
Recordings restored from `/tmp/ff-tools/snapshot` before and after every run,
`CaptureDrawKeys = 0` and `CaptureVulkanPipelines = 0`, drop-in folders emptied, the ini
edited by hand per arm and asserted by the runner, `~/.cache/mesa_shader_cache` emptied
before every cold run. Music was left at its shipped default (`PrecompileWarmMusic = 1`)
in every engine run, because that is the configuration that would ship.

Six arms. The four the round was commissioned for, plus two the evidence needed:

| arm | condition | what it is |
|---|---|---|
| C4 | `full` | the shipped path: engine arm **off**, cold driver cache |
| C11 | `full+engine` | engine arm **on**, cold driver cache — a player's first launch |
| C11-repeat | `warm+engine` | the launch straight after a C11 run: warm cache **and** the fingerprint stamp, so the cheap path fires |
| warm floor | `floor+engine` | C11 settings on a warm cache with **no** stamp: the whole walk again on a driver that already has everything |
| *(new)* | `warm` | **C4 on a warm cache.** The control that separates "the engine walk warmed it" from "the driver cache remembered it". Without this arm the repeat arm's near-zero numbers are unreadable. |
| *(new)* | `engine-abort` | C11 cold with `PrecompileGateMaxSeconds = 180`: the safety valve, which had never been run, and the 09-20 report's second crash candidate (the engine's render-phase build) with only a few thousand pipelines built. |

Harness changes committed with this note: `conditions.json` gains the build's new keys in
`_defaults` (`PrecompileWarmDevice`, `PrecompileCrashLog`, `PrecompileWarmMusic`,
`PrecompileWarmMusicTracks`) — the gap the integration session flagged — plus the two new
conditions, and `PrecompileWarmDevice: 1` is now asserted by every engine arm because it is
the whole safety mechanism. `gpparse.py` gains a `min` combiner and the address-space
columns (`mem_gate_mb`, `mem_pass_over_mb`, the derived `mem_pass_cost_mb`,
`mem_walk_end_mb`, `mem_walk_freed_mb`, `mem_gp_first_mb`, `mem_gp_min_mb`), because the
arm that died on 2026-09-20 died of a failed allocation and no frame time shows that.

## 2. Every run

| arm | run | cold | load s | gate held s | walk (jobs / s) | pipelines before gameplay | of those compiled | route creations | route compiles ≥5 ms | route long frames | frames >50 ms | p99 ms | route | live s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `full` | 1 | cold | 65.6 | 28.8 | — | 735 | 562 | 86 | **21** | 6 | 9 | 15.1 | clean | 328 |
| `full` | 2 | cold | 65.6 | 28.4 | — | 735 | 564 | 95 | **33** | 5 | 8 | 15.0 | clean | 336 |
| `full+engine` | 1 | cold | **1003** | 968 | 61191 / 940 | 61725 | 34105 | 103 | **12** | 5 | 7 | 15.0 | clean | 312 |
| `full+engine` | 2 | cold | **1007** | 966 | 61191 / 938 | 61725 | 33985 | 117 | **26** | 6 | 8 | 14.9 | clean | 306 |
| `warm+engine` | 1 | warm | 47.4 | **10.0** | 512 / 4 (CHEAP) | 1255 | 0 | 87 | **2** | 2 | 4 | 15.0 | clean | 338 |
| `warm+engine` | 2 | warm | 47.4 | **10.1** | 512 / 4 (CHEAP) | 1255 | 0 | 87 | **0** | 0 | 2 | 14.9 | clean | 325 |
| `floor+engine` | 1 | warm | 165 | 126 | 61191 / 120 | 61725 | 16 | 104 | 13 | 3 | 5 | 15.3 | done¹ | 345 |
| `floor+engine` | 2 | warm | 160 | 125 | 61191 / 119 | 61725 | 0 | 86 | 0 | 0 | 2 | 14.9 | clean | 314 |
| `warm` (C4) | 1 | warm | 41.3 | 5.3 | — | 735 | 0 | 100 | **5** | 1 | 3 | 15.0 | clean | 293 |
| `engine-abort` | 1 | cold | 221 | 181 | 10950 / 164 (stopped) | 11701 | 6781 | 89 | 31 | 7 | 11 | 15.0 | clean | 300 |

¹ completed, not clean: two "player on foot, new chauffeur" deviations on leg east-hook,
11 s frozen and 15.2 s unfocused. A route-driving artefact, not a fault.

Every run exited 0, quit through `g_dwMenuAction = 0x34`, and logged `0 failed, 0 faulted,
0 no render target, 0 no declaration, 0 no shader mirror`. `faults` is 0 in all ten.

The enumeration is deterministic and identical in every engine run: 112 effects (112 joined
to `.fxc`), 1696 techniques, 1809 passes, 912 VS + 1064 PS programs; 18 target-bearing
render phases binding 36 targets plus 62 registry targets → **18 contexts** (6 from phases,
9 from the registry, 3 shipped stand-ins); 8 phase state vectors, all shipped;
**61,191 jobs after dedup** (49,413 collapsed onto an identity already emitted). The walk
draws all 61,191 of them, through **8 warm devices of 8192 jobs each**, and DXVK ends at
**61,725 pipelines** before gameplay against the default arm's **735** — the same integers
in both cold runs and both floor runs.

## 3. Does it still kill the game? No.

Seven launches with `PrecompileEngineWarm = 1` — two cold full walks, two warm full walks,
two cheap-path repeats and one aborted walk — **all completed the route and quit cleanly.**
Against 2026-09-20, where both engine arms died 134 s and 71 s into gameplay while the two
arms without it drove the same route clean on the same binary and save.

The 09-20 note left two candidates. Both are now retired:

- **Address space** was the cause, and the device rotation is the fix (§4).
- **The engine's render-phase build** — the `CViewportGame` 0 → 27 phase build the gate
  performs, which happened only in the two arms that died — is cleared by `engine-abort`.
  That run builds all 27 phases, suppresses the engine's own build exactly as the full arm
  does, and then stops the walk after 10,950 jobs and 11,701 pipelines. It drove the whole
  route clean. The phase build is survivable on its own; it was never the killer.

## 4. Does memory return to the clean level before gameplay? Almost — and the shortfall is
the first chunk, not the pipelines

The per-phase address-space report (`memory <where>: free N MB (largest run M MB, …)`,
`GlobalMemoryStatusEx` plus a `VirtualQuery` walk) makes the mechanism visible.

**Inside the walk, the rotation works exactly as designed.** Cold run 1, free MB after each
8192-job chunk's device was replaced:

| before the walk | chunk 1 | 2 | 3 | 4 | 5 | 6 | 7 | end of walk | after its device and resources went |
|---|---|---|---|---|---|---|---|---|---|
| 3094 | **2917** | 2917 | 2915 | 2914 | 2914 | 2913 | 2913 | 2912 | 2913 |

Largest contiguous free run: 580 MB before, **428 MB from chunk 1 onward, pinned there for
the rest of the walk**. Cold run 2 reproduces it to within 2 MB (3094 → 2918 → … → 2916).
**The whole 61,191-job walk costs what its first chunk costs — about 178 MB — and the other
seven chunks cost 1–4 MB between them.** That is the chunking working: the pipelines of a
destroyed device are gone (`0 references left`), and the Windows heap, which does not
decommit an interleaved free list, hands the space to the next chunk instead of to the OS.

**Across the whole pass, gate to gate:**

| arm | at the gate | with the pass over | pass cost | largest free run after | first gameplay report | gameplay floor |
|---|---|---|---|---|---|---|
| `full` cold 1 | 3144 | **2961** | 183 | 574 | 2630 | **1932** |
| `full` cold 2 | 3144 | **2964** | 180 | 571 | 2635 | **1943** |
| `full+engine` cold 1 | 3146 | **2817** | 329 | 428 | 2497 | **1794** |
| `full+engine` cold 2 | 3143 | **2811** | 332 | 440 | 2554 | **1803** |
| `warm+engine` 1 | 3155 | **3082** | 73 | 533 | 2752 | **2038** |
| `warm+engine` 2 | 3157 | **3079** | 78 | 538 | 2808 | **2063** |
| `warm` (C4) 1 | 3157 | **3108** | 49 | 572 | 2778 | **2056** |
| `floor+engine` 1 | 3156 | 3079 | 77 | 440 | 2739 | 2018 |
| `floor+engine` 2 | 3155 | 2947 | 208 | 437 | 2625 | 1926 |
| `engine-abort` 1 | 3145 | 2920 | 225 | 432 | 2644 | 1876 |

Read plainly:

- **On a cold first launch the answer is "no, about 145 MB short."** The engine arm hands
  gameplay 2811–2817 MB where the default hands it 2961–2964, and gameplay plateaus at
  1794–1803 MB against 1932–1943. That gap is the first chunk's high-water: memory the heap
  has committed and will reuse, but has not given back to the address map.
- **On every other launch the answer is yes, or better than the default.** The cheap path
  costs 73–78 MB against the default warm arm's 49 MB and plateaus at 2038–2063 MB against
  2056 MB — the same machine, within noise.
- **It is nothing like the configuration that died.** That run reached the Vulkan replay
  with 2329 MB free and fell to 1228 MB in gameplay with 27 MB contiguous before
  `ExitProcess(3)`. The worst number here is 1794 MB. The largest contiguous run collapses
  to 27 MB in gameplay in *every* arm including the default — that is the game's own
  allocation pattern, documented on 09-20 and unchanged.
- **The cost is the cold compiler, not the pipelines.** `floor+engine` run 1 runs the same
  61,191-job walk on a warm driver cache and costs **77 MB**, against 329 MB for the same
  walk cold. What the cold walk spends is RADV compiling, not DXVK holding.
- **It varies.** The same arm measured 77 and 208 MB on two warm-floor runs. A single pair
  of readings is not a measurement of this number; the two cold pairs (329/332 and 183/180)
  are tight enough to trust, the warm ones are not.

Disk, which no previous note measured. The runner records the driver cache's size around
every run (apparent size, from an empty cache on a cold run):

| after a cold run of | `~/.cache/mesa_shader_cache` |
|---|---|
| `full` (default) | **7.4 MB** |
| `engine-abort` (10,950 of 61,191 jobs) | 12.8 MB |
| `full+engine` (the whole walk) | **23.5 MB**, in **67,150 files** |

So the walk adds about 16 MB of data — but in 67,150 entries of ~390 bytes each, which is
**279 MB of 4 KB blocks**. That is the number a player's disk sees, and it is worth knowing
before shipping the feature on. (`du -sh` and apparent size differ by 12× for this reason;
`meta.json`'s `mesa_*_bytes` are apparent size, and an earlier reading of "279 MB" during
this session was briefly mistaken for cache growth.)

## 5. How close to zero does it get over the full route?

Not as close as the last two notes suggested, and the honest version needs the new `warm`
control.

| | route compiles ≥5 ms | ≥20 ms, exact route window | long frames in the route | frames >50 ms |
|---|---|---|---|---|
| `full` cold (C4) | 21, 33 | 19, 30 | 6, 5 | 9, 8 |
| `full+engine` cold (C11) | **12, 26** | **10, 23** | 5, 6 | 7, 8 |
| `warm` (C4 on a warm cache) | 5 | 3 | 1 | 3 |
| `warm+engine` repeat (C11-repeat) | **2, 0** | 2, 0 | 2, 0 | 4, 2 |
| `floor+engine` | 13, 0 | 12, 0 | 3, 0 | 5, 2 |
| `engine-abort` | 31 | 25 | 7 | 11 |

Three things follow.

**On a cold driver cache the engine arm removes about a third of the compiles and none of
the long frames.** 12 and 26 against 21 and 33 — the ranges overlap at 21–26, with n = 2
each, so the means (19 against 27) are suggestive and not separated. The long-frame count —
the thing a player actually sees — is 5, 6 against 6, 5. Whatever the walk is doing, it is
not removing the route's stutters at this scale.

**The one effect that is unambiguous, reproducible and mechanistic is the Cluckin' Bell
interior.** `legsplit.py`, compiles gained between the end of the drive and the end of the
on-foot segment (walk in, buy, walk out):

| run | interior compiles |
|---|---|
| `full` cold 1 / 2 | **+13 / +19** |
| `full+engine` cold 1 / 2 | **+3 / +0** |
| `engine-abort` (10,950 of 61,191 jobs) | **+12** |
| `warm`, `warm+engine`, `floor+engine` | +0 / +1 / +0 |

This is the same segment the 09-21 boot-gate control isolated as the difference between the
two gates. The full walk empties it; a partial walk does not. That is a real, engine-level
win on first-visit interior content, and it is the strongest argument the feature has.

**Most of the repeat arm's near-zero is the driver cache, not the walk.** This is what the
`warm` control was for. On a warm cache the *default* arm already reaches 5 compiles and 1
long frame; the engine arm reaches 2 and 0. The headline "1 compile on a warm cache" from
the integration session is true and almost entirely attributable to the driver having
compiled those pipelines during the previous run of the same route.

**The measurement cannot show the engine arm's real case.** The harness drives one route,
so a warm-cache run is "content this machine rendered ten minutes ago" — exactly the case
the walk is not needed for. The engine arm's claim is that its cache is warmed by
*enumeration* rather than by play, so it should hold its cold-run numbers on content the
player has never rendered, where the default arm falls back to 21–33. Nothing here tests
that. It would need a second route, driven cold on a cache warmed by the first.

## 6. What a first launch costs, and what a repeat costs

| | to gameplay | gate held | the walk | what the player sees |
|---|---|---|---|---|
| first launch, engine arm | **1003 / 1007 s** (16.7 min) | 966 / 968 s | 61,191 jobs, 938 / 940 s, 8 devices | 16 minutes of the game's own loading screen |
| first launch, default | **65.6 / 65.6 s** | 28.4 / 28.8 s | — | the same screen for a minute |
| repeat launch, engine arm | **47.4 / 47.4 s** | **10.0 / 10.1 s** | 512-job probe, 4 s, 0 compiles → `PATH = CHEAP` | seconds |
| repeat launch, default | 41.3 s | 5.3 s | — | seconds |
| warm cache, stamp lost | 160 / 165 s | 125 / 126 s | 61,191 jobs, 119 / 120 s | ~2 minutes |

(What that screen looks like — the band, the bar, the music — is the presentation branch's
result and was not re-checked here; this session measured time, memory and compiles only.
The pass presented 0 frames of its own in every run, as the boot gate intends.)

So the honest cost of shipping the feature on is **one 16-minute launch, then about 6
seconds on every launch after it** — plus 279 MB of disk — until the driver, DXVK or the
shader set changes, at which point the stamp stops matching and the 16 minutes are paid
again. The cheap path is real and it works: the stamp matched, the 512-job probe compiled
0 of 512, and the gate let go after 10 seconds, in both repeat runs.

The user's budget ("20 minutes to an hour is acceptable on first launch / cold cache") is
met on this machine with room to spare. It is met at 65 jobs/s on an RX 9070 XT; nothing
here bounds it on slower hardware, which is what the next section is for.

## 7. The safety valve, exercised for the first time

`PrecompileGateMaxSeconds = 180`, cold, engine on. The log:

```
gate: PrecompileGateMaxSeconds (180) reached after 180.0 s - asking the pass to stop and unwind
engine: drew 10950 of 61191 jobs in 164s [the gate asked the pass to stop] (0 failed, 0 faulted, …)
engine: the walk went through 2 warm device(s) of 8192 jobs each, …
memory at the gate, with the pass over: free 2920 MB (largest run 432 MB) …
precompile complete in 181.1s
gate: released after 181.1 s, 20902 slices
```

**The valve works.** The walk stopped where it was, its device went back, the pass finished
its normal ending (Vulkan replay, state restore, resource release), the loading screen came
down 1.1 s after the deadline, and the route ran clean. Address space came back to 2920 MB
— 225 MB of cost for a quarter of the walk, in line with the first chunk dominating.

**And it buys nothing.** 10,950 jobs of 61,191 left the interior burst fully intact (+12,
against the default's +13/+19) and the route's totals at the default's level (31 compiles,
25 at ≥20 ms, 11 frames over 50 ms). The enumeration is not ordered by usefulness, so a
truncated walk is a truncated load time and not a partial benefit. Anyone setting
`PrecompileGateMaxSeconds` to bound the load on slow hardware should understand they are
turning the feature off with extra steps.

## 8. The default path's own regression, unchanged

Not re-measured here — `state/2026-09-21-linux-boot-gate-control.md` settled it with three
interleaved runs per build. This round's two default runs sit where that control put the
boot-gate build: **735** pipelines before gameplay in both runs — the same integer it read
in all three of its own — and route compiles of 21 and 33 (mean 27) against its 23.7, where
`4c85a78` at the old gate measured 12.0. The 51 pipelines the boot gate costs the
default path are still lost, and they are worth about the same number of route compiles as
the engine walk is — at **no load-time cost at all**. The integration session's ambient-spec
instrumentation retired the leading hypothesis (the D3D9SpecData axes are byte-identical at
both sites) and left the overlay-interleaving one, which needs a build of `4c85a78`
carrying that instrumentation to confirm. That is the cheaper win and it is still on the
table.

## 9. Recommendation: `PrecompileEngineWarm` ships at 0

**Keep the shipped default off.** The arm is now *safe* — that is settled, and it is a real
result: seven clean launches, a bounded walk, a floor, a cap, an abort path that works, and
address space that comes back everywhere except a cold first launch where it is 145 MB
short of the clean arm. Nothing about it is a crash risk any more.

It is not *worth* being on by default:

1. **The benefit on the measured route is a third of the compiles and none of the long
   frames**, at n = 2 per arm with overlapping ranges (12/26 against 21/33; 5/6 long frames
   against 6/5).
2. **The one solid win is one interior segment.** Real, mechanistic and reproducible, but
   it is 13–19 compiles in a five-minute route, and it needs the *complete* walk.
3. **It costs every user a 16-minute first launch** on a fast machine, unbounded on slower
   ones, plus 279 MB of driver cache on disk, repaid whenever the driver, DXVK or the
   shader set moves.
4. **The cheaper win is still unclaimed.** Recovering the boot gate's 51 pipelines is worth
   a comparable number of route compiles and costs nothing at load time.
5. **The decisive experiment has not been run.** The engine arm's actual claim — that its
   warming generalises to content the player has never rendered, where the default arm's
   does not — is untestable with one route, and every warm number in this report is
   "content seen ten minutes ago".

For **this machine**, turning it on is a defensible choice and the user's stated budget
covers it: one 16-minute launch, then 47-second launches with 0–2 route compiles and 0–2
long frames, which is the best any arm measured. One line in the ini does it, and the ini
documents it. That is a user decision, not a shipping default.

**What would change the answer**, in order of value:

- A second route, driven cold on a driver cache warmed by the first. That is the only way
  to measure the thing the feature is actually for, and it would probably settle this
  either way.
- Two more cold `full+engine` runs. 12 and 26 is not a number; if the next two land near 12
  the arm is twice as good as this report can claim.
- The walk timed on a slower CPU, to know what "unbounded" means in practice.
- The 51-pipeline fix measured, so the two gains can be compared rather than guessed at.

## 10. Not verified

- One rig, one route, one save, one episode (TBoGT), n = 2 per arm and n = 1 for `warm` and
  `engine-abort`.
- `warm` (C4 on a warm cache) has one run. It is the control the whole "is the repeat arm's
  near-zero the walk or the cache?" argument rests on, and it deserves a second.
- Every warm arm's driver cache was warmed by the immediately preceding run of the *same*
  route. No arm here measures first-visit content on a warm cache.
- Level 2 enumeration (~290k jobs) is untested; the chunk size was not re-tuned.
- `PrecompileWarmMusic` was on in every engine run (the shipped default) and its
  contribution to load time was not isolated.
- `PrecompileWarmDevice = 0` (the unprotected A/B arm) was not run again. It is the
  configuration that killed the game and there was no reason to.
- The presentation branch's remaining open item — the cheap-path band text on screen — is
  not this report's; the cheap path fired twice here and both times the gate was released
  in 10 s, but no screenshot was taken.

## 11. Anomalies

1. **One launch never started.** `full` run 2, first attempt: the runner staged the run at
   08:17:57 and `GTAIV.exe` never appeared within its five-minute wait, although Steam's
   `reaper`, `pressure-vessel` and `PlayGTAIV.exe` were all up. It happened on the launch
   immediately after `floor+engine` run 1 quit. The orphaned Proton session was cleared
   with `wineserver -k` on the game prefix (no live `GTAIV.exe` existed), and the immediate
   retry launched normally in 24 s. Kept as
   `/tmp/ff-results-v3/_abandoned/full-run2-launch-failure/`.
2. **`floor+engine` run 1 is `completed` but not `clean`**: two "player on foot, new
   chauffeur" deviations on leg east-hook, 11 s frozen, 15.2 s unfocused. Route-driving
   artefact; its pipeline counts are unaffected and are used.
3. **`gpparse`'s route deltas can reach up to 15 s past the route's end.** FusionFix reports
   the cumulative counters every 15 s, so the `delta` window takes the first report after
   the route ends. It matters in exactly one run: `full+engine` run 2 reads 26 compiles by
   that rule and 17 at `legsplit`'s last in-route report. Both numbers are in this report;
   §5's ≥20 ms column is the exact byte-window count and is the one to trust for
   cross-arm comparison.
4. **`du` on the Mesa cache reads 12× its apparent size.** 67,150 entries of ~390 bytes in
   4 KB blocks: 23.5 MB apparent, 279 MB on disk. Both are true and they answer different
   questions ("what did the pass add" and "what does the player's disk lose"); a reading of
   one was briefly mistaken for the other during this session. `meta.json`'s
   `mesa_before_bytes` / `mesa_after_bytes` are apparent size.
5. **The game lock's 90-minute abandonment rule is still wrong for this feature.** A
   `full+engine` run holds the game for 25 minutes and the lock sits idle between runs; the
   rule breaks a lock older than 90 minutes whenever no game is running, which is the state
   between two runs of a 20-minute measurement. This session refreshed its own timestamp in
   `/tmp/gtaiv-game.lock.d/owner` between runs to work around it. The rule should account
   for the engine arm's load time, or the holder should refresh — as the memory session
   already reported.

## 12. Cleanup

Verified before the lock was released at 09:36:

- **Ini**: `cmp`-identical to `/tmp/ff-tools/ini.pristine`. The three keys this session
  added (`PrecompileEngineWarm`, `PrecompileWarmDevice`, `PrecompileGateMaxSeconds`) and
  the two it changed (`CaptureDrawKeys`, `CaptureVulkanPipelines`) were all put back with
  the Edit tool.
- **Recordings**: all three `cmp`-identical to `/tmp/ff-tools/snapshot`.
- **`plugins\d3d9cache` and `plugins\pipelinecache`**: empty. No `FusionFix.enginewarm.stamp`,
  no `.state`, no `.tmp`, no `.emitted.jsonl`.
- **Deployed ASI**: unchanged at `bccc1fb94849d75e…`, the build under test. Nothing was
  built during this session and the build lock was never taken.
- **Processes**: no `GTAIV.exe`, `PlayGTAIV.exe`, `Launcher.exe` or Steam reaper for 12210.
  The one orphan session (anomaly 1) was cleared at the time.
- **Lock**: released (`gtaiv-lock.sh release measure`); `status` reports free.
- **Results**: `/tmp/ff-results-v3/` (tmpfs) — ten run folders plus `_abandoned/` and the
  10 s machine-load sampler's log in this session's scratchpad. Copy before a reboot.

# Linux gameplay rig

A repeatable real-world stutter measurement on the development machine (Arch, KDE Wayland,
RX 9070 XT / RADV, GTA IV 1.2.0.59 under Proton through Steam). One run = one launch of the
game for one named condition, driven along the same route every time.

| file | what it is |
|---|---|
| `gameplay_run.py` | one run: preflight, stage, launch, route, quit, clean up |
| `route.py` | the route driver (Frida, on the goal runner in fusionfix-hdr) |
| `routes/lc-districts.json` | the route: Star Junction, the Algonquin Bridge, Broker, the Broker Bridge, the Cluckin' Bell |
| `conditions.json` | the conditions: the `[SHADERS]` keys each asserts, drop-ins, cold or warm |
| `gpparse.py` | result folders to markdown tables |
| `kwin-focus-gtaiv.js` | KWin script that gives the game window focus back |

Needs: the frida-gadget `.asi` in `plugins\` (the route and the quit both use it),
`python-frida`, the goal runner at `fusionfix-hdr/re/gtaiv-re-tools/scripts` (or
`$GTAIV_RE_TOOLS`), and the snapshot of the player's recordings in `/tmp/ff-tools/snapshot`.

## One run

```sh
/tmp/ff-tools/gtaiv-lock.sh acquire <you>
# set the condition's [SHADERS] keys in plugins/GTAIV.EFLC.FusionFix.ini with an editor
run/linux/gameplay_run.py --condition full --run 1 --owner <you>          # --dry-run first
# put the ini back exactly (editor), cmp it with /tmp/ff-tools/ini.pristine
/tmp/ff-tools/gtaiv-lock.sh release <you>
run/linux/gpparse.py /tmp/ff-results
```

The runner refuses to start unless `--owner` holds the game lock, the game is not running
and the ini matches the condition; it never edits the ini. Then it:

1. puts the snapshot recordings back into `plugins\`;
2. empties `plugins\d3d9cache\` and `plugins\pipelinecache\` and removes FusionFix's
   snapshot state files, then stages the condition's drop-ins (below);
3. for a cold condition, empties `~/.cache/mesa_shader_cache` (the game's Mesa cache while
   Steam Shader Pre-Caching is off; checked against the game's environment);
4. launches through Steam, waits for the loading-screen pass (`gate: ran after`, or `disabled
   via ini`) in a log newer than the launch, and runs `route.py`, which waits for gameplay
   and settles 15 live seconds before the route;
5. plays on 20 s (FusionFix reports every 15 s), copies the log, quits with the gtaiv-quit
   skill, copies the final log, cleans the drop-in folders and state files again, and puts
   the snapshot recordings back.

Results: `/tmp/ff-results/<condition>/run<N>/` with `meta.json` (what ran, hashes, the
asserted keys, staged and removed files, timings), `route.json`, `route.log`, `runner.log`,
`env.txt`, `FusionFix.shaders.prequit.log` and `FusionFix.shaders.log`.

Hands off the PC during a run. The route notices when the game loses focus or its simulation
freezes and asks KWin to focus the game again (within a second when tested), but every
second of it is logged and the run is no longer "clean".

## Drop-ins

`.bin` D3D9 captures go in `plugins\d3d9cache\`, `.foz` Fossilize databases in
`plugins\pipelinecache\`, flat, named `FusionFix.<h>.<ext>`: `<h>` is 16 lowercase hex digits
of FNV-1a-64 over the whole file (offset basis `0xcbf29ce484222325`, prime `0x100000001b3`).
`gameplay_run.py --name-of FILE...` prints the name. FusionFix writes this PC's own snapshot
there under the same rule, so every `FusionFix.<16 hex>.bin|foz` in those folders is a copy
and is deleted before and after a run. Anything else there, including a subfolder, was put
there by hand: the runner refuses to start rather than delete it.

State files: FusionFix remembers the snapshot it last wrote in a file next to the ASI, one
per side: `FusionFix.d3d9cache.state` and `FusionFix.pipelinecache.state`. The runner removes
those and the D3D9 side's crash leftover `FusionFix.d3d9cache.tmp` (`_state_files` in
`conditions.json`) and lists every file it removed in `meta.json`.

Not cleared: DXVK 3.x's own cache of translated shaders
(`compatdata/12210/.../AppData/Local/dxvk`) is in Steam's folder. A cold run only makes the
driver cold; `meta.json` records that cache's files so a change shows.

## The route

`routes/lc-districts.json`: out of any car, warp to a road node in Star Junction, stream it
in (`LOAD_SCENE`), clock 13:00, sunny, wanted level cleared and capped at 0, player
invincible. A spawned AI chauffeur (a Super Diamond or the episode's fallback car) drives
the player, as passenger, east through Lancet over the Algonquin Bridge to Rotterdam Hill,
south through East Hook, back over the Broker Bridge to Fishmarket South and Chinatown, and
north to the Cluckin' Bell in The Triangle: 3.4 km in 3.5 minutes. The player walks in to
the counter along the navmesh, eats, and walks back out to the street: the end, 4.5 minutes
after the start. A whole run, launch to quit, takes about 6 minutes warm. Watchdog: a car
that hasn't moved 5 m in 12 live seconds (`stall_s`) is snapped to the nearest road node and
re-tasked; stopped within `near` metres of a leg's end counts as arrived; a driver who left
or a player on foot gets a new chauffeur; a leg out of time warps the car to its end. Warps
and new chauffeurs are deviations.

Validated on 141a876, warm, the deployed ini, two runs of the final route: 271.3 and 269.2 s
(driving 208.3 and 208.4 s), no stall, no deviation, no freeze or focus loss; DXVK created
81 and 87 pipelines during the route, none of them a compile (>= 5 ms).

Two things the route file has to respect, both found the hard way: the AI plans only over
path data streamed in around the player, so each bridge is a leg of its own and the leg
after it ends at the foot of the ramp; and a node lookup only sees that streamed data too,
so every point is a fixed coordinate (a node read standing next to it, or a point on the
car's recorded path), never snapped at run time.

While `route.py` runs, its Frida hooks cost the game's main thread about 3,000 callbacks a
second (the input poll plus seven script natives; the goal runner's full set was 16,700). The
same in every condition, and gone once the route ends, before the tail.

`route.json` reports the route's live, wall and game-timer duration, every leg and on-foot
step, deviations, and three kinds of interval, each with the log's size at its start:

- **freeze**: frames go on but the game's own script calls stop for 2 s (paused, or
  unfocused on a setup that pauses then); leg timeouts and the watchdog don't count it;
- **hang**: no frame at all for 0.5 s (the main thread is busy); `route_hangs` in the
  table counts those inside the route, a rough stutter measure that needs no FusionFix;
- **unfocused**: the foreground window belongs to another process. Minimized, the game
  lost focus here but kept simulating, so this is checked on its own.

`route.py probe` prints the simulation, focus, clock, weather and player position of a
running game; `route.py run` drives the route by hand.

## The parser

`gpparse.py [results...]` prints a row per run and, per condition, the mean and range. Every
number comes from the `METRICS` table at its top: a column, a regex, and how to combine the
matching lines (`last`, `first`, `count`, `sum`, `max`, or `delta` of a cumulative counter
across the route) over the whole log or only the route's part of it. It already knows the
frame-time, long-frame, per-compile and quiet-wait lines of the build in progress; a new log
line is one more row in that table.

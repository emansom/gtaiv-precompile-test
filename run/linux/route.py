#!/usr/bin/env python3
"""Drive the fixed gameplay route in a running GTA IV (Linux rig), for the stutter A/B:
the same streets, time of day and weather on every run, whatever the save or where the
player happens to be.

  route.py run [--route FILE] [--out FILE] [--log FILE] [--settle S] [--ready-timeout S] [--no-refocus]
  route.py probe        simulation, focus, time of day, weather, player position + zone
  route.py wait-live    exit 0 once gameplay runs (scripts tick and a player exists)

Built on the goal runner in fusionfix-hdr (re/gtaiv-re-tools/scripts, or $GTAIV_RE_TOOLS):
its Frida JS -- the main-thread native invoker, the script-phase drain the chauffeur is
spawned from, the road-node unstick -- is loaded unchanged and extended below. It talks
to the frida-gadget .asi in plugins\\ on 127.0.0.1:27042.

THE ROUTE (routes/*.json)
  Out of any car, warp to a fixed road node, stream it in, hold the time of day and the
  weather, clear the wanted level and cap it at 0, make the player invincible. A spawned
  AI chauffeur drives the player (as passenger: the engine refuses to auto-drive the
  player's own car) through the legs without stopping. Watchdog: no progress for
  12 live seconds snaps the car to the nearest road node and re-tasks the driver; a
  driver who left or a player on foot gets a new chauffeur; a leg out of time warps the
  car to its end. Every one is counted, and a warp or a new chauffeur is a deviation.
  Then on foot: into the Cluckin' Bell in The Triangle, eat at the counter, back out
  to the street, which is the end.

FROZEN SIMULATION, LOST FOCUS
  GTA IV stops simulating while its window is unfocused (or paused). Its input poll (our
  CPad hook) keeps running and so, per the goal-runner notes, does the game timer; both
  are recorded. The game's own script-native calls (the goal runner's phase hooks) stop
  with the simulation, so a monitor thread samples three counters from the Frida JS
  thread, which answers even while the game's main thread is busy:
    frames  (CPad polls)   stopped >= 0.5 s          -> a HANG: the main thread is busy
    script calls           stopped >= 2 s, frames on -> FROZEN: the simulation is paused
    GetForegroundWindow    another process's window  -> UNFOCUSED
  Leg timeouts and the watchdog count live seconds only. Minimized under Proton's Wayland
  driver the game lost focus but did NOT freeze (measured); frame pacing is gone either
  way, so on any loss of focus the window is activated through KWin
  (kwin-focus-gtaiv.js) every 10 s, unless --no-refocus, and the run is not "clean".

RESULT
  --out gets JSON: completed / clean, the route's wall, live and game-timer duration,
  per-leg and on-foot records, deviations, watchdog counts, and every freeze, hang and
  focus loss. Each event carries the size of FusionFix.shaders.log at that moment
  ("log_at"), so gpparse.py can cut the log to the route. Exit 0 = completed, 1 = not
  completed, 2 = never reached gameplay.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.environ.get("GTAIV_RE_TOOLS", "/home/ewout/Projects/fusionfix-hdr/re/gtaiv-re-tools/scripts")
sys.path.insert(0, TOOLS)
import frida_goal_runner as gr   # noqa: E402  (needs the path above)

VERSION = 2
G = os.path.expanduser("~/.local/share/Steam/steamapps/common/Grand Theft Auto IV/GTAIV")
DEFAULT_LOG = os.path.join(G, "plugins", "FusionFix.shaders.log")
DEFAULT_ROUTE = os.path.join(HERE, "routes", "lc-districts.json")
KWIN_FOCUS = os.path.join(HERE, "kwin-focus-gtaiv.js")

# Natives the goal runner doesn't carry (Ghidra VA, 1.2.0.59). Each address is where
# GTAIV.exe registers the native ("push handler; push hash; call RegisterNative
# 0x86e820", hash -> name from artifacts/NativeHashes.h); the arguments were read off
# each handler's disassembly (m_pArgs[0], [1], ...).
XN = {
    "FORCE_TIME_OF_DAY":            0x00bd7190,  # (hour, minute)  sets the clock and holds it
    "GET_TIME_OF_DAY":              0x00bd7240,  # (&hour, &minute)
    "FORCE_WEATHER":                0x00b94290,  # (type)  0 extra sunny, 1 sunny, 2 windy, 3 cloudy, 4 rain ...
    "FORCE_WEATHER_NOW":            0x00b942a0,  # (type)
    "GET_CURRENT_WEATHER":          0x00b943d0,  # (&type)
    "SET_MAX_WANTED_LEVEL":         0x00bb2970,  # (level)
    "SET_POLICE_IGNORE_PLAYER":     0x00bb2d10,  # (playerId, on)
    "SET_CHAR_INVINCIBLE":          0x00ba15e0,  # (ped, on)
    "SET_CHAR_WILL_FLY_THROUGH_WINDSCREEN": 0x00ba1c70,  # (ped, on)
    "SET_CHAR_CANT_BE_DRAGGED_OUT": 0x00ba10c0,  # (ped, on)
    "SET_CHAR_HEADING":             0x00ba15a0,  # (ped, float heading)
    "SET_CAM_BEHIND_PED":           0x00b872b0,  # (ped)
    "LOAD_SCENE":                   0x00bb7480,  # (x, y, z)  streams the area in; blocks the main thread
    "CLEAR_AREA":                   0x00b93ff0,  # (x, y, z, radius, bool)
    "SET_CAR_PROOFS":               0x00bc7760,  # (car, bullet, fire, explosion, collision, melee)
    "SET_CAR_CAN_BE_DAMAGED":       0x00bc73e0,  # (car, on)
    "SET_CAR_CAN_BE_VISIBLY_DAMAGED": 0x00bc7400,  # (car, on)
    "SET_CAR_STRONG":               0x00bc7820,  # (car, on)
    # Walks through doors on the navmesh; TASK_GO_STRAIGHT_TO_COORD walks into the wall.
    # Move state 2 = walk (1 stands still); when `time` runs out the ped is put at the target.
    "TASK_FOLLOW_NAV_MESH_TO_COORD": 0x00bb98c0,  # (ped, x, y, z, moveState, time ms, float radius)
}
# The millisecond clock GET_GAME_TIMER returns: its worker (0xb962c0) is
# "mov eax, [0x011735b4]; mov [ecx], eax". Read straight from the JS thread.
GAME_TIMER = 0x011735b4

EXT_JS = r"""
// ---- route.py: what a fixed, timed route needs on top of the goal runner --------------------
var XN = %XN%;
for (var _xk in XN) XN[_xk] = BASE.add(XN[_xk]);
var GAME_TIMER = BASE.add(%TIMER%);

// The goal runner hooks every native it knows as its script-phase signal: ~16,700 calls/s
// in gameplay, 80% of them GET_PLAYER_ID, GET_PLAYER_CHAR and DOES_BLIP_EXIST. A timing
// run can't spend that on the game's main thread, so keep the input-poll hook and only
// phase hooks that fire a few times a frame (~3,000 calls/s together, measured 1.2.0.59).
Interceptor.detachAll();
Interceptor.attach(UPDATE, { onEnter: function () { g_frame++; if (g_drainCpad) drainQueue(); } });
['GET_GAME_TIMER', 'IS_CHAR_IN_ANY_CAR', 'GET_CHAR_COORDINATES', 'DOES_VEHICLE_EXIST', 'GET_CAR_CHAR_IS_USING',
 'IS_CHAR_SITTING_IN_ANY_CAR', 'HAS_MODEL_LOADED'].forEach(function (k) {
  Interceptor.attach(NAT[k], { onEnter: function () { phaseOnEnter(k); } });
});

// The game's own script-native calls. Our ops call hooked natives too, from inside
// drainQueue: those don't count. Both hooks look these functions up at call time.
var g_scriptCalls = 0, g_inOwnOp = false;
var _routePhase = phaseOnEnter;
phaseOnEnter = function (k) { if (!g_inOwnOp) g_scriptCalls++; _routePhase(k); };
var _routeDrain = drainQueue;
drainQueue = function () { g_inOwnOp = true; try { _routeDrain(); } finally { g_inOwnOp = false; } };

// Is the foreground window one of this process's? null = can't tell.
var FOCUS = null;
try {
  var _u32 = Process.getModuleByName('user32.dll'), _k32 = Process.getModuleByName('kernel32.dll');
  FOCUS = {
    fg:   new NativeFunction(_u32.getExportByName('GetForegroundWindow'), 'pointer', [], 'stdcall'),
    pid:  new NativeFunction(_u32.getExportByName('GetWindowThreadProcessId'), 'uint32', ['pointer', 'pointer'], 'stdcall'),
    self: new NativeFunction(_k32.getExportByName('GetCurrentProcessId'), 'uint32', [], 'stdcall'),
    out:  Memory.alloc(4)
  };
} catch (e) { FOCUS = null; }
function gameFocused() {
  if (FOCUS === null) return null;
  try {
    var w = FOCUS.fg();
    if (w.isNull()) return false;
    FOCUS.out.writeU32(0);
    FOCUS.pid(w, FOCUS.out);
    return FOCUS.out.readU32() === FOCUS.self();
  } catch (e) { return null; }
}

function envRead() {
  var t = Memory.alloc(8); t.writeU32(0); t.add(4).writeU32(0);
  callNative(XN.GET_TIME_OF_DAY, [{t:'p',v:t},{t:'p',v:t.add(4)}]);
  var w = getViaOut(XN.GET_CURRENT_WEATHER, [], 4).readS32();
  return { hour: t.readS32(), minute: t.add(4).readS32(), weather: w };
}

var _routeAction = doAction;
doAction = function (name, p) {
  if (name === 'route_env') {                   // clock, weather, no police, a player who can't die
    var pp = ped_of_player();
    callNative(XN.FORCE_TIME_OF_DAY, [{t:'i',v:p.hour},{t:'i',v:p.minute}]);
    callNative(XN.FORCE_WEATHER, [{t:'i',v:p.weather}]);
    callNative(XN.FORCE_WEATHER_NOW, [{t:'i',v:p.weather}]);
    callNative(NAT.CLEAR_WANTED_LEVEL, [{t:'i',v:pp.pid}]);
    callNative(XN.SET_MAX_WANTED_LEVEL, [{t:'i',v:0}]);
    callNative(XN.SET_POLICE_IGNORE_PLAYER, [{t:'i',v:pp.pid},{t:'i',v:1}]);
    callNative(XN.SET_CHAR_INVINCIBLE, [{t:'i',v:pp.ped},{t:'i',v:1}]);
    callNative(XN.SET_CHAR_WILL_FLY_THROUGH_WINDSCREEN, [{t:'i',v:pp.ped},{t:'i',v:0}]);
    callNative(XN.SET_CHAR_CANT_BE_DRAGGED_OUT, [{t:'i',v:pp.ped},{t:'i',v:1}]);
    return envRead();
  }
  if (name === 'env_read') return envRead();
  if (name === 'protect') {                     // a wreck or an explosion would end the route
    if (p.car) {
      callNative(XN.SET_CAR_PROOFS, [{t:'i',v:p.car},{t:'i',v:1},{t:'i',v:1},{t:'i',v:1},{t:'i',v:1},{t:'i',v:1}]);
      callNative(XN.SET_CAR_CAN_BE_DAMAGED, [{t:'i',v:p.car},{t:'i',v:0}]);
      callNative(XN.SET_CAR_CAN_BE_VISIBLY_DAMAGED, [{t:'i',v:p.car},{t:'i',v:0}]);
      callNative(XN.SET_CAR_STRONG, [{t:'i',v:p.car},{t:'i',v:1}]);
    }
    if (p.npc) {
      callNative(XN.SET_CHAR_INVINCIBLE, [{t:'i',v:p.npc},{t:'i',v:1}]);
      callNative(XN.SET_CHAR_CANT_BE_DRAGGED_OUT, [{t:'i',v:p.npc},{t:'i',v:1}]);
    }
    return { ok: true };
  }
  if (name === 'place') {                       // warp on foot, face, clear the area, camera behind
    callNative(NAT.SET_CHAR_COORDINATES, [{t:'i',v:p.ped},{t:'f',v:p.x},{t:'f',v:p.y},{t:'f',v:p.z}]);
    if (p.heading != null) callNative(XN.SET_CHAR_HEADING, [{t:'i',v:p.ped},{t:'f',v:p.heading}]);
    if (p.clear) callNative(XN.CLEAR_AREA, [{t:'f',v:p.x},{t:'f',v:p.y},{t:'f',v:p.z},{t:'f',v:p.clear},{t:'i',v:1}]);
    callNative(XN.SET_CAM_BEHIND_PED, [{t:'i',v:p.ped}]);
    return { ok: true };
  }
  if (name === 'load_scene') {
    callNative(XN.LOAD_SCENE, [{t:'f',v:p.x},{t:'f',v:p.y},{t:'f',v:p.z}]);
    return { ok: true };
  }
  if (name === 'car_warp') {                    // a car onto a given road node, facing along it
    callNative(NAT.SET_CAR_COORDINATES, [{t:'i',v:p.car},{t:'f',v:p.x},{t:'f',v:p.y},{t:'f',v:p.z}]);
    if (p.heading != null) callNative(NAT.SET_CAR_HEADING, [{t:'i',v:p.car},{t:'f',v:p.heading}]);
    callNative(NAT.SET_CAR_ON_GROUND_PROPERLY, [{t:'i',v:p.car}]);
    return { ok: true };
  }
  if (name === 'cam_behind') { callNative(XN.SET_CAM_BEHIND_PED, [{t:'i',v:p.ped}]); return { ok: true }; }
  if (name === 'navwalk') {
    callNative(NAT.CLEAR_CHAR_TASKS, [{t:'i',v:p.ped}]);
    callNative(XN.TASK_FOLLOW_NAV_MESH_TO_COORD, [{t:'i',v:p.ped},{t:'f',v:p.x},{t:'f',v:p.y},{t:'f',v:p.z},
                                                  {t:'i',v:p.move},{t:'i',v:p.time},{t:'f',v:p.radius}]);
    return { ok: true };
  }
  return _routeAction(name, p);
};

// Answered on the Frida JS thread: works while the sim is frozen or the main thread busy.
rpc.exports.live = function () {
  return { frame: g_frame, calls: g_scriptCalls, timer: GAME_TIMER.readU32(), focus: gameFocused(), queued: queue.length };
};
rpc.exports.purge = function () { var n = queue.length; queue = []; return n; };
rpc.exports.drain = function (mode) { g_drainCpad = (mode === 'cpad'); g_drainPhase = (mode === 'phase'); return mode; };
""".replace("%XN%", json.dumps({k: gr.RVA(v) for k, v in XN.items()})).replace("%TIMER%", str(gr.RVA(GAME_TIMER)))


def sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def dist(a, b):
    return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5


class Link:
    """The Frida session. RPCs are serialised: the monitor thread shares the script."""

    def __init__(self, timeout):
        import frida
        t0 = time.time(); last = None
        while True:
            try:
                dev = frida.get_device_manager().add_remote_device("127.0.0.1:27042")
                self.session = dev.attach("Gadget")
                script = self.session.create_script(gr.JS + EXT_JS)
                script.load()
                self.ex = script.exports_sync
                break
            except Exception as e:     # the gadget is not listening yet, or the game is gone
                last = e
                if time.time() - t0 >= timeout:
                    raise RuntimeError("no frida gadget on 127.0.0.1:27042 after %ds (%s)" % (timeout, last))
                time.sleep(3)
        self.lock = threading.Lock()
        self.mon = None

    def rpc(self, name, *args):
        with self.lock:
            return getattr(self.ex, name)(*args)

    def op(self, name, params=None, timeout=8.0, live=False, cap=180.0):
        """Run a goal-runner op on the game's main thread. The clock stops while the main
        thread is busy (a long frame, LOAD_SCENE) and, for an op that needs the script
        phase (live=True), while the simulation is frozen: the op stays queued and runs
        once the game moves again. cap bounds the whole wait."""
        jid = self.rpc("enqueue", name, params or {})
        t0 = last = time.time(); waited = 0.0
        while True:
            r = self.rpc("result", jid)
            if r is not None:
                if not r.get("ok"):
                    raise RuntimeError("op '%s' failed: %s" % (name, r.get("err")))
                return r["v"]
            time.sleep(0.03)
            now = time.time()
            m = self.mon
            if m is None or not (m.hung or (live and m.frozen)):
                waited += now - last
            last = now
            if waited > timeout or now - t0 > cap:
                raise RuntimeError("op '%s' not run after %.0fs (game stalled or gone?)" % (name, now - t0))

    def close(self):
        try:
            self.session.detach()
        except Exception:
            pass


def refocus():
    """Activate the GTA IV window through a KWin script (org.kde.kwin.Scripting), the way
    re/gtaiv-re-tools/scripts/kwin_run.sh runs one. Best effort: returns whether it ran."""
    # A fresh plugin name every time: KWin keeps a script by name, and running a script
    # loaded again under a name it had before did nothing (tested on Plasma 6).
    base = ["dbus-send", "--session", "--print-reply", "--dest=org.kde.KWin"]
    name = "gtaiv-route-focus-%d-%d" % (os.getpid(), time.monotonic_ns())
    try:
        out = subprocess.run(base + ["/Scripting", "org.kde.kwin.Scripting.loadScript", "string:" + KWIN_FOCUS,
                                     "string:" + name], capture_output=True, text=True, timeout=5).stdout
        sid = next((l.split()[-1] for l in out.splitlines() if "int32" in l), None)
        if sid is None or sid.startswith("-"):
            return False
        r = subprocess.run(base + ["/Scripting/Script" + sid, "org.kde.kwin.Script.run"], capture_output=True, timeout=5)
        time.sleep(0.3)
        subprocess.run(base + ["/Scripting", "org.kde.kwin.Scripting.unloadScript", "string:" + name],
                       capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


class Monitor(threading.Thread):
    """Samples frames, script calls, the game timer and focus every 0.25 s (see the module
    docstring). Intervals carry epochs; cmd_run adds times relative to the route."""
    PERIOD = 0.25
    HANG_S = 0.5
    FREEZE_S = 2.0
    KICK_EVERY_S = 10.0

    def __init__(self, link, logpath, kick=True):
        super().__init__(daemon=True)
        self.link, self.logpath, self.kick = link, logpath, kick
        self.hung = self.frozen = False
        self.focus = None
        self.sample = None
        self.samples = 0
        self.freezes, self.hangs, self.unfocused = [], [], []
        self.kicks = 0
        self._cur = {"freeze": None, "hang": None, "unfocus": None}
        self._stop = threading.Event()
        self._first = threading.Event()

    def log_at(self):
        try:
            return os.path.getsize(self.logpath)
        except OSError:
            return None

    def _open(self, kind, t, extra=None):
        c = {"start_epoch": round(t, 3), "log_at": self.log_at()}
        c.update(extra or {})
        self._cur[kind] = c
        return c

    def _close(self, kind, t, lst, extra=None):
        c = self._cur[kind]
        if c is None:
            return None
        c["seconds"] = round(t - c["start_epoch"], 2)
        c["log_at_end"] = self.log_at()
        c.update(extra or {})
        lst.append(c)
        self._cur[kind] = None
        return c

    def run(self):
        last = None
        t_frame = t_calls = time.time()
        last_kick = 0.0
        while not self._stop.is_set():
            try:
                s = self.link.rpc("live")
            except Exception:
                if not self._stop.wait(self.PERIOD):
                    continue
                break
            now = time.time()
            if last is not None and s["frame"] != last["frame"]:
                t_frame = now
            if last is not None and s["calls"] != last["calls"]:
                t_calls = now
            if last is None:
                t_frame = t_calls = now
            self.sample, self.samples = s, self.samples + 1
            self._first.set()
            hung = now - t_frame >= self.HANG_S
            if self.hung and not hung:
                t_calls = max(t_calls, now)     # the scripts get FREEZE_S to resume after a hang
            frozen = (not hung) and now - t_calls >= self.FREEZE_S
            if hung and not self.hung:
                self._open("hang", t_frame)
            if not hung and self.hung:
                self._close("hang", now, self.hangs)
            if frozen and not self.frozen:
                self._open("freeze", t_calls, {"timer_start": s["timer"], "focus_start": s["focus"], "kicks": 0})
                print("\n  [sim] FROZEN: no script call for %.0fs while frames run (focus %s)"
                      % (self.FREEZE_S, s["focus"]), flush=True)
            if not frozen and self.frozen:
                c = self._close("freeze", now, self.freezes, {"timer_end": s["timer"]})
                c["game_ms"] = s["timer"] - c["timer_start"]
                print("\n  [sim] running again after %.1fs frozen (game timer moved %d ms meanwhile)"
                      % (c["seconds"], c["game_ms"]), flush=True)
            if s["focus"] is False and self.focus is not False:
                self._open("unfocus", now)
                print("\n  [sim] UNFOCUSED: another process has the foreground window", flush=True)
            if s["focus"] is not False and self.focus is False:
                c = self._close("unfocus", now, self.unfocused)
                print("\n  [sim] focused again after %.1fs" % c["seconds"], flush=True)
            self.hung, self.frozen, self.focus = hung, frozen, s["focus"]
            # Whether the simulation stops without focus depends on the setup (minimized,
            # it ran on under Proton's Wayland driver); either way the run is spoiled, so
            # any loss of focus gets the window back.
            if self.kick and (s["focus"] is False or (frozen and s["focus"] is None)) \
                    and now - last_kick >= self.KICK_EVERY_S:
                last_kick = now
                ok = refocus()
                t_frame = t_calls = time.time()     # no samples while KWin was asked: not a hang
                self.kicks += 1
                for kind in ("freeze", "unfocus"):
                    if self._cur[kind] is not None:
                        self._cur[kind]["kicks"] = self._cur[kind].get("kicks", 0) + 1
                print("\n  [sim] focus lost: asked KWin to focus the game window: %s" % ("sent" if ok else "FAILED"),
                      flush=True)
            last = s
            self._stop.wait(self.PERIOD)

    def wait_first(self, timeout=10.0):
        return self._first.wait(timeout)

    @property
    def running(self):
        return self.samples > 0 and not self.hung and not self.frozen

    def frozen_seconds(self):
        """All frozen time so far, including an open interval."""
        s = sum(f["seconds"] for f in self.freezes)
        c = self._cur["freeze"]
        return s + (time.time() - c["start_epoch"] if c else 0.0)

    def wait_running(self, cap):
        t0 = time.time()
        while time.time() - t0 < cap:
            if self.running:
                return True
            time.sleep(0.25)
        return False

    def stop(self):
        self._stop.set()
        self.join(timeout=3)
        now = time.time()
        self._close("freeze", now, self.freezes, {"open_at_end": True})
        self._close("hang", now, self.hangs, {"open_at_end": True})
        self._close("unfocus", now, self.unfocused, {"open_at_end": True})


class Route:
    def __init__(self, link, mon, spec, res):
        self.L, self.mon, self.spec, self.res = link, mon, spec, res
        beh = gr.BEHAVIORS[spec.get("behavior", "fast")]
        self.speed = float(spec.get("speed", beh["speed"]))
        self.mode = int(spec.get("mode", beh["mode"]))
        self.style = int(spec.get("style", beh["style"]))
        self.colour = int(spec.get("car_colour", 68))
        self.stall_s = float(spec.get("stall_s", 12.0))
        self.car = self.npc = self.ped = 0
        self.model = None
        self.facing = None
        self.t0 = time.time()
        self.frozen0 = 0.0
        self.events, self.deviations = [], []
        self.chauffeurs = 0

    # ---- bookkeeping --------------------------------------------------------------
    def rel(self):
        return round(time.time() - self.t0, 2)

    def event(self, what, **kw):
        e = {"t": self.rel(), "epoch": round(time.time(), 3), "log_at": self.mon.log_at(), "what": what}
        e.update(kw)
        self.events.append(e)
        return e

    def deviate(self, what):
        self.deviations.append({"t": self.rel(), "what": what})
        print("\n  deviation: %s" % what, flush=True)

    def live_elapsed(self, since, frozen_since):
        return time.time() - since - (self.mon.frozen_seconds() - frozen_since)

    def live_sleep(self, seconds, cap=300.0):
        """Sleep until `seconds` of running simulation have passed."""
        t0 = time.time(); f0 = self.mon.frozen_seconds()
        while self.live_elapsed(t0, f0) < seconds:
            if time.time() - t0 > cap:
                return False
            time.sleep(0.25)
        return True

    def zone(self, x, y, z):
        try:
            return self.L.op("zone_at", {"x": x, "y": y, "z": z}).get("zone") or None
        except RuntimeError:
            return None

    def point(self, p):
        """{"x","y","z"[,"heading"]}, snapped to the nearest car node with "road": true.
        Only path data streamed in around the player is searched, so a snap is only the
        same every time for a point near the player: route files use exact nodes."""
        x, y, z = float(p["x"]), float(p["y"]), float(p.get("z", 20.0))
        h = p.get("heading")
        if p.get("road"):
            n = self.L.op("roadnode", {"x": x, "y": y, "z": z})
            if n["found"]:
                x, y, z = n["x"], n["y"], n["z"]
                h = n["heading"] if h is None else h
        return x, y, z, h

    def leave_car(self):
        d = self.L.op("diag")
        if d["in_any_car"] and d["car"]:
            self.L.op("leave", {"ped": self.ped, "car": d["car"]})
            t = time.time()
            while time.time() - t < 8 and self.L.op("status", {"ped": self.ped})["in_car"]:
                time.sleep(0.5)
            return d["car"]
        return 0

    # ---- the chauffeur ------------------------------------------------------------
    def spawn(self):
        """A freshly spawned car + AI driver, created in the script phase as the goal
        runner's spawn_chauffeur does it. An op queued for that phase waits while the
        simulation is frozen and runs when it moves again, so the drain only goes back
        to the input phase once nothing is left queued for the script phase (a CREATE
        drained there faults). Returns (car, npc) or (0, 0)."""
        L = self.L
        if self.model is None:
            self.model = L.op("pick_model", {"names": gr.CHAUFFEUR_CARS})
            if not self.model["available"]:
                raise RuntimeError("no chauffeur car model in this episode")
        pl = L.op("player")
        rn = L.op("roadnode", {"x": pl["x"] + 18.0, "y": pl["y"], "z": pl["z"]})
        sx, sy = (rn["x"], rn["y"]) if rn["found"] else (pl["x"] + 18.0, pl["y"])
        if not self.mon.wait_running(cap=180):
            return 0, 0
        L.rpc("drain", "phase")
        car = npc = 0
        try:
            L.op("request_model", {"hash": self.model["hash"]}, live=True)
            for _ in range(100):
                if L.op("model_loaded", {"hash": self.model["hash"]}, live=True)["loaded"]:
                    break
                time.sleep(0.1)
            r = L.op("spawn_in_phase", {"hash": self.model["hash"], "dx": sx - pl["x"], "dy": sy - pl["y"],
                                        "col": self.colour}, timeout=20, live=True)
            car = r.get("car", 0)
            if car:
                L.op("settle", {"car": car}, live=True)
                L.op("engine_on", {"car": car}, live=True)
                rd = L.op("spawn_driver_in_phase", {"car": car}, timeout=20, live=True)
                npc = rd.get("ped", 0)
                if not npc:
                    L.op("mark_car", {"car": car}, live=True)
                    car = 0
        except RuntimeError as e:
            print("  !! chauffeur spawn: %s" % e, flush=True)
            car = npc = 0
        finally:
            dropped = L.rpc("purge")
            L.rpc("drain", "cpad")
            if dropped:
                print("  !! dropped %d op(s) still queued for the script phase" % dropped, flush=True)
        return car, npc

    def acquire(self, tx, ty, tz, place=None):
        """Seat the player as passenger of a new chauffeur tasked to (tx, ty, tz). With
        `place` (x, y, z, heading) the car is put there first, so the route always
        starts from the same spot facing the same way."""
        for attempt in range(3):
            car, npc = self.spawn()
            if car and npc:
                break
            print("  chauffeur spawn failed (attempt %d)" % (attempt + 1), flush=True)
            self.live_sleep(3.0, cap=120)
        else:
            return False
        self.release()
        self.car, self.npc = car, npc
        self.chauffeurs += 1
        L = self.L
        L.op("protect", {"car": car, "npc": npc})
        L.op("warp_passenger", {"ped": self.ped, "car": car, "seat": -1})
        if L.op("driver_of", {"car": car})["driver"] != npc:
            print("  !! the spawned driver is not at the wheel", flush=True)
            return False
        if place is not None:
            L.op("car_warp", {"car": car, "x": place[0], "y": place[1], "z": place[2], "heading": place[3]})
        L.op("cam_behind", {"ped": self.ped})
        self.task(tx, ty, tz)
        print("  chauffeur #%d: %s %d, driver %d" % (self.chauffeurs, self.model["name"], car, npc), flush=True)
        return True

    def task(self, tx, ty, tz):
        self.L.op("task_drive_npc", {"npc": self.npc, "car": self.car, "tx": tx, "ty": ty, "tz": tz,
                                     "speed": self.speed, "mode": self.mode, "style": self.style})

    def release(self):
        """Let the current chauffeur go: the player gets out first, the driver drives off."""
        if not self.car:
            return
        try:
            if self.L.op("status", {"ped": self.ped})["in_car"]:
                self.L.op("leave", {"ped": self.ped, "car": self.car})
                t = time.time()
                while time.time() - t < 8 and self.L.op("status", {"ped": self.ped})["in_car"]:
                    time.sleep(0.5)
            self.L.op("chauffeur_stop", {"npc": self.npc, "car": self.car})
        finally:
            self.car = self.npc = 0

    # ---- the route ----------------------------------------------------------------
    def setup(self):
        s, L = self.spec, self.L
        pl = L.op("player")
        self.ped = pl["ped"]
        self.res["found_at"] = [round(pl["x"], 1), round(pl["y"], 1), round(pl["z"], 1)]
        env = s["env"]
        got = L.op("route_env", {"hour": env["hour"], "minute": env["minute"], "weather": env["weather"]})
        self.res["env_set"] = got
        if self.leave_car():
            self.live_sleep(2.0, cap=60)
        x, y, z, h = self.point(s["start"])
        L.op("place", {"ped": self.ped, "x": x, "y": y, "z": z, "heading": h,
                       "clear": float(s["start"].get("clear", 40.0))})
        L.op("load_scene", {"x": x, "y": y, "z": z}, timeout=120)
        self.res["start"] = [round(x, 1), round(y, 1), round(z, 1), round(h or 0.0, 1)]
        self.res["start_zone"] = self.zone(x, y, z)
        print("  start: %s (%.1f, %.1f, %.1f) heading %.0f; clock %02d:%02d, weather %d"
              % (self.res["start_zone"], x, y, z, h or 0.0, got["hour"], got["minute"], got["weather"]), flush=True)
        self.live_sleep(float(s.get("start_settle_s", 5.0)), cap=300)
        return (x, y, z, h or 0.0)

    def leg(self, i, lg, place):
        L = self.L
        tx, ty, tz, _ = self.point(lg["to"])
        name = lg.get("name", "leg%d" % (i + 1))
        arrive = float(lg.get("arrive", 20.0))
        # The AI parks at the node it thinks is the target, which can be across a divider
        # or under a ramp: stopped this close counts as arrived ("near").
        near = float(lg.get("near", max(3.0 * arrive, 60.0)))
        limit = float(lg.get("timeout_s", 180.0))
        rec = {"name": name, "target": [round(tx, 1), round(ty, 1), round(tz, 1)], "zone": self.zone(tx, ty, tz),
               "arrived": False, "near": False, "fallback": None, "stalls": 0, "unsticks": 0, "respawns": 0,
               "travelled_m": 0.0}
        rec["start"] = self.event("leg", name=name)["t"]
        print("\n--- leg %d %s -> (%.0f, %.0f) %s" % (i + 1, name, tx, ty, rec["zone"]), flush=True)
        if not self.car:
            if not self.acquire(tx, ty, tz, place):
                rec["fallback"] = "no-chauffeur"
                return rec
        else:
            self.task(tx, ty, tz)
        t0 = time.time(); f0 = self.mon.frozen_seconds()
        # Stuck = the car hasn't moved 5 m (a detour away from the target is progress too).
        anchor = stall_t = foot_t = None; prev = None; dd = None
        while self.live_elapsed(t0, f0) < limit:
            time.sleep(1.0)
            if not self.mon.running:
                stall_t = None                  # frozen or busy: the watchdog doesn't count it
                continue
            s = L.op("status", {"ped": self.ped, "tx": tx, "ty": ty, "tz": tz})
            here = (s["x"], s["y"], s["z"])
            if prev is not None:
                rec["travelled_m"] += dist(here, prev)
            prev = here
            dd = s["dist"] if s["dist"] is not None else 9999.0
            print("  %-14s %6.0f m to go  (%5.0f, %5.0f)  %3.0fs  %s"
                  % (name, dd, s["x"], s["y"], self.live_elapsed(t0, f0), "car" if s["in_car"] else "ON FOOT"),
                  end="\r", flush=True)
            if dd <= arrive:
                rec["arrived"] = True
                break
            now = time.time()
            if not s["in_car"]:
                foot_t = foot_t or now
                if now - foot_t > 4.0:
                    print("\n  on foot: a new chauffeur", flush=True)
                    rec["respawns"] += 1
                    self.deviate("leg %s: player on foot, new chauffeur" % name)
                    if not self.acquire(tx, ty, tz):
                        rec["fallback"] = "no-chauffeur"
                        break
                    foot_t = stall_t = None
                continue
            foot_t = None
            if stall_t is None or dist(here, anchor) > 5.0:
                anchor, stall_t = here, now
                continue
            if now - stall_t > (4.0 if dd <= near else self.stall_s):
                if dd <= near:
                    rec["arrived"] = rec["near"] = True
                    break
                rec["stalls"] += 1
                if L.op("driver_of", {"car": self.car})["driver"] != self.npc:
                    print("\n  the driver left: a new chauffeur", flush=True)
                    rec["respawns"] += 1
                    self.deviate("leg %s: driver left, new chauffeur" % name)
                    if not self.acquire(tx, ty, tz):
                        rec["fallback"] = "no-chauffeur"
                        break
                else:
                    u = L.op("unstick", {"car": self.car})
                    rec["unsticks"] += 1
                    print("\n  no progress for %.0fs at %.0f m: car to the nearest road node (%s)"
                          % (now - stall_t, dd, "moved" if u.get("ok") else u.get("reason")), flush=True)
                    self.task(tx, ty, tz)
                stall_t = None
        if not rec["arrived"] and rec["fallback"] is None and self.car:
            # Keep the route whole: the car goes to the node at the leg's end and the route
            # carries on. That stretch was not driven: a deviation.
            n = L.op("roadnode", {"x": tx, "y": ty, "z": tz})
            if n["found"]:
                L.op("car_warp", {"car": self.car, "x": n["x"], "y": n["y"], "z": n["z"], "heading": n["heading"]})
            rec["fallback"] = "warp"
            self.deviate("leg %s: out of time at %.0f m, car warped to its end" % (name, dd or -1))
            self.live_sleep(2.0, cap=60)
        rec["end"] = self.event("leg_end", name=name, arrived=rec["arrived"])["t"]
        rec["live_s"] = round(self.live_elapsed(t0, f0), 1)
        rec["end_dist_m"] = round(dd, 1) if dd is not None else None
        rec["travelled_m"] = round(rec["travelled_m"], 1)
        print("\n  leg %s: %s in %.0fs live, %.0f m driven, %d stalls, %d unsticks, %d new chauffeurs"
              % (name, ("arrived near (%.0f m)" % dd if rec["near"] else "arrived") if rec["arrived"]
                 else "NOT arrived (%s)" % rec["fallback"], rec["live_s"],
                 rec["travelled_m"], rec["stalls"], rec["unsticks"], rec["respawns"]), flush=True)
        return rec

    def walk(self, step):
        """On foot along the navmesh, through doors ('any means' would let the player steal
        a car). The task's own time limit, which puts the ped at the target, is set past
        ours, so a walk that doesn't get there shows up as our warp, a deviation."""
        L = self.L
        x, y, z, _ = self.point(step["to"])
        radius = float(step.get("radius", 2.0)); limit = float(step.get("timeout_s", 60.0))
        rec = {"name": step["name"], "kind": "walk", "reached": False, "fallback": None}
        rec["start"] = self.event("walk", name=step["name"])["t"]
        go = {"ped": self.ped, "x": x, "y": y, "z": z, "move": int(step.get("move", 2)),
              "time": int((limit + 60) * 1000), "radius": min(radius, 1.0)}
        L.op("navwalk", go)
        t0 = time.time(); f0 = self.mon.frozen_seconds(); best = 1e9; stall_t = None; dd = None; reissued = 0
        while self.live_elapsed(t0, f0) < limit:
            time.sleep(0.5)
            if not self.mon.running:
                stall_t = None
                continue
            s = L.op("status", {"ped": self.ped, "tx": x, "ty": y, "tz": z})
            dd = s["dist"] if s["dist"] is not None else 9999.0
            print("  walking to %-10s %5.1f m" % (step["name"], dd), end="\r", flush=True)
            if dd <= radius:
                rec["reached"] = True
                break
            now = time.time()
            if best - dd > 0.5 or stall_t is None:
                best = min(best, dd); stall_t = now
            elif now - stall_t > 8.0:          # a ped in the way: go again
                reissued += 1
                L.op("navwalk", go)
                stall_t = now
        if not rec["reached"]:
            L.op("warp", {"ped": self.ped, "x": x, "y": y, "z": z})
            rec["fallback"] = "warp"
            self.deviate("walk to %s: out of time at %.1f m, player warped there" % (step["name"], dd or -1))
        rec["reissued"] = reissued
        rec["end"] = self.event("walk_end", name=step["name"], reached=rec["reached"])["t"]
        rec["live_s"] = round(self.live_elapsed(t0, f0), 1)
        print("\n  %s: %s in %.0fs live" % (step["name"], "reached" if rec["reached"] else "WARPED", rec["live_s"]),
              flush=True)
        self.facing = (x, y, z)
        return rec

    def eat(self, step):
        """The Cluckin' Bell counter: the eat animation, and the buy's own effects ($1 off
        the wallet, full health) the way the goal runner reproduces them."""
        L = self.L
        rec = {"name": step["name"], "kind": "eat"}
        rec["start"] = self.event("eat", name=step["name"])["t"]
        f = self.facing
        if f:
            L.op("face", {"ped": self.ped, "x": f[0], "y": f[1], "z": f[2]})
            self.live_sleep(1.5, cap=60)
        adict, anim = "AMB@BNCH_EAT_DEF", "Bnch_Eat_Default"
        for _ in range(25):
            if L.op("anims_ready", {"dict": adict})["loaded"]:
                break
            time.sleep(0.2)
        L.op("play_anim", {"ped": self.ped, "anim": anim, "dict": adict, "loop": True, "time": -1})
        try:
            b = L.op("buy_fowlburger", {"ped": self.ped, "cost": 1})
            rec["bought"] = {k: b.get(k) for k in ("charged", "money_before", "money_after", "hp_before", "hp_after")}
        except RuntimeError as e:
            rec["bought"] = {"error": str(e)}
        self.live_sleep(float(step.get("dwell_s", 6.0)), cap=120)
        L.op("clear_tasks", {"ped": self.ped})
        rec["end"] = self.event("eat_end", name=step["name"])["t"]
        print("  ate at the counter: %s" % rec["bought"], flush=True)
        return rec

    def run(self):
        s, res = self.spec, self.res
        place = self.setup()
        self.t0 = time.time()
        self.frozen0 = self.mon.frozen_seconds()
        timer0 = self.mon.sample["timer"] if self.mon.sample else None
        res["start_epoch"] = round(self.t0, 3)
        res["log_at_start"] = self.event("route_start")["log_at"]
        res["legs"], res["on_foot"] = [], []
        for i, lg in enumerate(s["legs"]):
            if self.live_elapsed(self.t0, self.frozen0) > float(s.get("timeout_s", 600)):
                res["errors"].append("route out of time before leg %s" % lg.get("name"))
                break
            rec = self.leg(i, lg, place if i == 0 else None)
            res["legs"].append(rec)
            if rec["fallback"] == "no-chauffeur":
                res["errors"].append("leg %s: no chauffeur" % rec["name"])
                break
        drove = len(res["legs"]) == len(s["legs"]) and all(r["fallback"] != "no-chauffeur" for r in res["legs"])
        self.event("get_out")
        self.release()
        if drove:
            for step in s.get("on_foot", []):
                res["on_foot"].append(self.eat(step) if step.get("eat") else self.walk(step))
        end = self.event("route_end")
        res["end_epoch"], res["log_at_end"] = end["epoch"], end["log_at"]
        res["route_wall_s"] = round(end["epoch"] - self.t0, 1)
        res["route_frozen_s"] = round(self.mon.frozen_seconds() - self.frozen0, 1)
        res["route_live_s"] = round(res["route_wall_s"] - res["route_frozen_s"], 1)
        if timer0 is not None and self.mon.sample:
            res["route_game_s"] = round((self.mon.sample["timer"] - timer0) / 1000.0, 1)
        res["completed"] = drove and len(res["on_foot"]) == len(s.get("on_foot", []))
        try:
            res["env_end"] = self.L.op("env_read")
            p = self.L.op("player")
            res["end_pos"] = [round(p["x"], 1), round(p["y"], 1), round(p["z"], 1)]
            res["end_zone"] = self.zone(p["x"], p["y"], p["z"])
            if s.get("end"):
                e = s["end"]
                res["end_dist_m"] = round(dist((p["x"], p["y"], p["z"]), (e["x"], e["y"], e["z"])), 1)
        except RuntimeError as e:
            res["errors"].append("end read: %s" % e)


def wait_ready(link, mon, timeout):
    """Gameplay = frames AND the game's own script calls advancing, and a player ped.
    (The monitor gets the window back if it loses focus meanwhile.)"""
    t0 = time.time(); ok_run = 0
    while time.time() - t0 < timeout:
        time.sleep(1.0)
        if mon.running:
            try:
                ok = link.op("player", timeout=3.0)["ped"] > 0
            except RuntimeError:
                ok = False
            ok_run = ok_run + 1 if ok else 0
            if ok_run >= 3:
                return time.time() - t0
        else:
            ok_run = 0
    return None


def cmd_run(args):
    spec_path = os.path.abspath(args.route)
    with open(spec_path) as f:
        spec = json.load(f)
    res = {"tool": "route.py", "version": VERSION, "route": spec["name"], "route_file": spec_path,
           "route_sha256": sha256(spec_path), "route_py_sha256": sha256(os.path.abspath(__file__)),
           "goal_runner_sha256": sha256(os.path.join(TOOLS, "frida_goal_runner.py")),
           "launched_epoch": round(time.time(), 3), "completed": False, "clean": False, "errors": []}

    def write():
        if args.out:
            with open(args.out, "w") as f:
                json.dump(res, f, indent=1)

    try:
        link = Link(args.ready_timeout)
    except RuntimeError as e:
        res["errors"].append(str(e)); write()
        print("ROUTE_RESULT " + json.dumps({"route": res["route"], "completed": False, "errors": res["errors"]}),
              flush=True)
        return 2
    mon = Monitor(link, args.log, kick=not args.no_refocus)
    link.mon = mon
    mon.start()
    mon.wait_first()
    rt = None
    rc = None
    try:
        print("waiting for gameplay (frames + script calls + a player ped)...", flush=True)
        waited = wait_ready(link, mon, args.ready_timeout)
        if waited is None:
            res["errors"].append("gameplay never started within %ds" % args.ready_timeout)
            rc = 2
        else:
            res["ready_epoch"] = round(time.time(), 3)
            res["ready_wait_s"] = round(waited, 1)
            print("in gameplay after %.0fs; settling %.0fs" % (waited, args.settle), flush=True)
            rt = Route(link, mon, spec, res)
            rt.live_sleep(args.settle, cap=args.settle + 300)
            print("\n=== route %s" % spec["name"], flush=True)
            rt.run()
    except Exception as e:                        # keep whatever was measured
        res["errors"].append("%s: %s" % (type(e).__name__, e))
        if rt is not None:
            try:
                rt.release()
            except Exception:
                pass
    finally:
        mon.stop()
        # Every interval also as seconds from the route's start (negative = before it)
        # and whether it overlaps the route.
        r0, r1 = res.get("start_epoch"), res.get("end_epoch")
        for c in mon.freezes + mon.hangs + mon.unfocused:
            if r0 is not None:
                c["t"] = round(c["start_epoch"] - r0, 2)
                c["in_route"] = c["start_epoch"] + c["seconds"] > r0 and (r1 is None or c["start_epoch"] < r1)
        res["freezes"], res["hangs"], res["unfocused"] = mon.freezes, mon.hangs, mon.unfocused
        res["focus_kicks"] = mon.kicks
        res["frozen_s"] = round(sum(f["seconds"] for f in mon.freezes), 1)
        if rt is not None:
            res["events"], res["deviations"], res["chauffeurs"] = rt.events, rt.deviations, rt.chauffeurs
            res["chauffeur_model"] = rt.model["name"] if rt.model else None
            legs = res.get("legs", [])
            res["watchdog"] = {k: sum(r.get(k, 0) for r in legs) for k in ("stalls", "unsticks", "respawns")}
            res["driven_m"] = round(sum(r.get("travelled_m", 0.0) for r in legs), 1)
            res["route_unfocused_s"] = round(sum(c["seconds"] for c in mon.unfocused if c.get("in_route")), 1)
            res["clean"] = bool(res["completed"] and not rt.deviations and not res["errors"]
                                and res.get("route_frozen_s", 0) == 0 and res["route_unfocused_s"] == 0)
        write()
        link.close()
    print("\n=== route %s: %s, %s s live (%s s wall, %s s frozen), %s m driven, watchdog %s, %d deviation(s)"
          % (res["route"], "COMPLETED" if res["completed"] else "NOT COMPLETED", res.get("route_live_s"),
             res.get("route_wall_s"), res.get("route_frozen_s"), res.get("driven_m"), res.get("watchdog"),
             len(res.get("deviations", []))), flush=True)
    print("ROUTE_RESULT " + json.dumps({k: res.get(k) for k in ("route", "completed", "clean", "route_live_s",
                                                                  "route_wall_s", "route_frozen_s", "errors")}),
          flush=True)
    return rc if rc is not None else (0 if res["completed"] else 1)


def cmd_probe(args):
    link = Link(30)
    try:
        a = link.rpc("live"); time.sleep(1.0); b = link.rpc("live")
        print("frames %d/s, game script calls %d/s, game timer +%d ms, focus %s -> %s"
              % (b["frame"] - a["frame"], b["calls"] - a["calls"], b["timer"] - a["timer"], b["focus"],
                 "RUNNING" if b["calls"] > a["calls"] else "FROZEN / not in gameplay"))
        if b["calls"] > a["calls"] or b["frame"] > a["frame"]:
            print("clock + weather: %s" % link.op("env_read"))
            p = link.op("player")
            z = link.op("zone_at", {"x": p["x"], "y": p["y"], "z": p["z"]})
            print("player ped %d at (%.2f, %.2f, %.2f) heading %.0f, zone '%s', area '%s'"
                  % (p["ped"], p["x"], p["y"], p["z"], p["heading"], z["zone"], z["area"]))
    finally:
        link.close()
    return 0


def cmd_wait_live(args):
    link = Link(args.timeout)
    mon = Monitor(link, args.log, kick=not args.no_refocus)
    link.mon = mon
    mon.start()
    try:
        waited = wait_ready(link, mon, args.timeout)
    finally:
        mon.stop()
        link.close()
    print("gameplay %s" % ("after %.0fs" % waited if waited is not None else "NOT reached in %ds" % args.timeout))
    return 0 if waited is not None else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--route", default=DEFAULT_ROUTE)
    r.add_argument("--out", default=None, help="write the result JSON here")
    r.add_argument("--log", default=DEFAULT_LOG, help="FusionFix.shaders.log, for the log offsets")
    r.add_argument("--settle", type=float, default=15.0, help="live seconds in gameplay before the route")
    r.add_argument("--ready-timeout", type=float, default=900.0, help="seconds to wait for gameplay")
    r.add_argument("--no-refocus", action="store_true", help="report freezes, never focus the window")
    sub.add_parser("probe")
    w = sub.add_parser("wait-live")
    w.add_argument("--timeout", type=int, default=600)
    w.add_argument("--log", default=DEFAULT_LOG)
    w.add_argument("--no-refocus", action="store_true")
    args = ap.parse_args()
    return {"run": cmd_run, "probe": cmd_probe, "wait-live": cmd_wait_live}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

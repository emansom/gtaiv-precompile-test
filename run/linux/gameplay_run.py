#!/usr/bin/env python3
"""One gameplay measurement run of GTA IV on the Linux rig, for one named condition.

  gameplay_run.py --condition full --run 1 --owner <lock owner> [--cold | --warm] [options]
  gameplay_run.py --name-of FILE...      print the drop-in name FusionFix would give each file

In order:
  1. preflight, read only: the game lock is held by --owner, GTA IV is not running, the
     frida gadget is installed, the snapshot is complete, the drop-in folders hold nothing
     but FusionFix.<h> files, and the ini's [SHADERS] keys match the condition (a key the
     ini lacks counts as the build's default, see conditions.json). The runner NEVER
     edits the ini: set the keys first, with an editor.
  2. put the snapshot recordings (/tmp/ff-tools/snapshot) back into plugins\\, remove
     FusionFix's snapshot state files, empty plugins\\d3d9cache\\ and
     plugins\\pipelinecache\\, stage the condition's drop-ins there, and for a cold run
     empty ~/.cache/mesa_shader_cache.
  3. launch through Steam; wait for the loading-screen pass (the log's mtime must be newer
     than the launch); drive the route (route.py), which waits for gameplay and settles
     first; play on for --tail seconds.
  4. copy FusionFix.shaders.log, quit with the gtaiv-quit skill (never a kill), copy the
     final log, clean the drop-in folders and the state files again, put the snapshot
     recordings back.
Results go to <results>/<condition>/run<N>/: meta.json, route.json, route.log, runner.log,
env.txt, FusionFix.shaders.prequit.log and FusionFix.shaders.log. Summarise with gpparse.py.

DROP-INS (the user's decisions 1-4)
  .bin D3D9 captures go in plugins\\d3d9cache\\, .foz Fossilize databases in
  plugins\\pipelinecache\\, flat, named FusionFix.<h>.<ext>: <h> = 16 lowercase hex
  digits of FNV-1a-64 (basis 0xcbf29ce484222325, prime 0x100000001b3) over the whole
  file. FusionFix itself writes this PC's own snapshot there under the same rule, and
  remembers it in a state file next to the ASI (one for each side). So everything in
  those folders that matches FusionFix.<16 hex>.(bin|foz) is a copy, ours or FusionFix's,
  and is deleted before and after a run. Anything else (a subfolder, another name) is a
  file somebody put there by hand: the runner refuses to start rather than touch it.
  State files: plugins\\ files matching the "_state_files" globs in conditions.json.

Exit: 0 = done and the route completed, 3 = done but the route did not complete,
2 = refused (preflight or ini assertion), 1 = the run failed (see runner.log).
"""
import argparse
import fnmatch
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
G = os.path.join(HOME, ".local/share/Steam/steamapps/common/Grand Theft Auto IV/GTAIV")
PLUGINS = os.path.join(G, "plugins")
INI = os.path.join(PLUGINS, "GTAIV.EFLC.FusionFix.ini")
LOG = os.path.join(PLUGINS, "FusionFix.shaders.log")
ASI = os.path.join(PLUGINS, "GTAIV.EFLC.FusionFix.asi")
GADGET = os.path.join(PLUGINS, "frida-gadget.asi")
DXVK_LOG = os.path.join(G, "GTAIV_d3d9.log")
# DXVK 3.x keeps its own on-disk cache of translated shaders in the Wine prefix. It is
# Steam's folder, so the runner only reports it (see meta "dxvk_shader_cache").
DXVK_CACHE = os.path.join(HOME, ".local/share/Steam/steamapps/compatdata/12210/pfx/drive_c/users/steamuser"
                                "/AppData/Local/dxvk")
MESA_CACHE = os.path.join(HOME, ".cache", "mesa_shader_cache")
LOCK_OWNER = "/tmp/gtaiv-game.lock.d/owner"
QUIT = "/home/ewout/Projects/fusionfix-hdr/.claude/skills/gtaiv-quit/gtaiv_quit.py"
GAME_RE = r"[\\/]GTAIV\.exe"
LAUNCHER_RE = r"[\\/]PlayGTAIV\.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ROUTE_PY = os.path.join(HERE, "route.py")
DROP_DIRS = {".bin": "d3d9cache", ".foz": "pipelinecache"}
COPY_NAME = re.compile(r"^FusionFix\.[0-9a-f]{16}\.(bin|foz)(\..+)?$")   # incl. a write's temp name
# The loading-screen pass is over: "gate: ran" follows the pass however it ended. None
# at all: disabled, or the hook failed (then the game just loads).
PASS_DONE = ("gate: ran after",)
PASS_NONE = ("disabled via ini", "FAILED to hook loadscreen render")
ENV_KEYS = re.compile(r"^(MESA_|RADV_|DXVK_|VKD3D_|XDG_CACHE_HOME|STEAM_COMPAT_SHADER|__GL_SHADER|"
                      r"PROTON_|WINEDLLOVERRIDES|SteamAppId|SteamGameId|STEAM_COMPAT_APP_ID)")


def fnv1a64(data):
    h = 0xcbf29ce484222325
    for b in data:
        h = ((h ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def dropin_name(path):
    """FusionFix.<h>.<ext> for a drop-in file (decision 4)."""
    with open(path, "rb") as f:
        return "FusionFix.%016x%s" % (fnv1a64(f.read()), os.path.splitext(path)[1].lower())


def sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def du(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def pids(pattern):
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(p) for p in r.stdout.split()]


def read_shaders_ini(path):
    """[SHADERS] key -> list of values, as FusionFix's CIniReader (mINI) sees them: keys
    case-sensitive, a later duplicate wins, the value read with stoi (leading integer)."""
    vals, sec = {}, None
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line[0] in ";#":
                continue
            m = re.match(r"^\[(.+)\]$", line)
            if m:
                sec = m.group(1).strip()
                continue
            if sec != "SHADERS" or "=" not in line:
                continue
            k, v = line.split("=", 1)
            m = re.match(r"\s*(-?\d+)", v)
            vals.setdefault(k.strip(), []).append(int(m.group(1)) if m else v.strip())
    return vals


class Runner:
    def __init__(self, args, table, cond, rundir):
        self.a, self.table, self.cond, self.rundir = args, table, cond, rundir
        self.meta = {"condition": args.condition, "run": args.run, "argv": sys.argv}
        self.logf = open(os.path.join(rundir, "runner.log"), "a")
        # Drop-in folders that did not exist before the run are removed again once empty,
        # whoever made them (the runner staging a file, or FusionFix writing its snapshot).
        self.dirs_before = {d: os.path.isdir(os.path.join(PLUGINS, d)) for d in set(DROP_DIRS.values())}
        self.t0 = None

    def say(self, msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        self.logf.write(line + "\n"); self.logf.flush()

    @staticmethod
    def game_running():
        return bool(pids(GAME_RE))

    @staticmethod
    def install(src, dst):
        """Binary artifacts are copied with install(1), as the project's rules ask."""
        subprocess.run(["install", "-m644", src, dst], check=True)

    def log_size(self):
        try:
            return os.path.getsize(LOG)
        except OSError:
            return None

    # ---- preflight ----------------------------------------------------------------
    def expectations(self):
        exp = dict(self.table.get("_common", {}))
        exp.update(self.cond.get("expect", {}))
        for kv in self.a.expect:
            k, _, v = kv.partition("=")
            exp[k.strip()] = int(v) if v.strip().lstrip("-").isdigit() else v.strip()
        return exp

    def check_ini(self, exp):
        ini = read_shaders_ini(INI)
        defaults = self.table.get("_defaults", {})
        eff, bad = {}, []
        for k, v in sorted(exp.items()):
            if k in ini and len(ini[k]) > 1:
                bad.append("%s is set %d times in [SHADERS] (%s): remove the duplicates" % (k, len(ini[k]), ini[k]))
                continue
            if k in ini:
                got, src = ini[k][0], "ini"
            elif k in defaults:
                got, src = defaults[k], "default"
            else:
                bad.append("%s: not in the ini and no known default (expected %s)" % (k, v))
                continue
            eff[k] = {"value": got, "from": src}
            if str(got) != str(v):
                bad.append("%s = %s (%s), condition wants %s" % (k, got, src, v))
        self.meta["ini_shaders"] = {k: v[-1] for k, v in ini.items()}
        self.meta["asserted"] = eff
        return bad

    def dropin_folders_state(self):
        """(copies, foreign): FusionFix.<h> files we may delete, and anything else."""
        copies, foreign = [], []
        for d in sorted(set(DROP_DIRS.values())):
            p = os.path.join(PLUGINS, d)
            if not os.path.isdir(p):
                continue
            for e in sorted(os.listdir(p)):
                full = os.path.join(p, e)
                (copies if os.path.isfile(full) and COPY_NAME.match(e) else foreign).append(full)
        return copies, foreign

    def state_files(self):
        pats = self.table.get("_state_files", [])
        snap = set(os.listdir(self.a.snapshot)) if os.path.isdir(self.a.snapshot) else set()
        return sorted(os.path.join(PLUGINS, e) for e in os.listdir(PLUGINS)
                      if os.path.isfile(os.path.join(PLUGINS, e)) and e not in snap
                      and any(fnmatch.fnmatchcase(e, p) for p in pats))

    def preflight(self, exp):
        a = self.a
        try:
            with open(LOCK_OWNER) as f:
                owner = f.read().split()[0]
        except (OSError, IndexError):
            owner = None
        lock = None
        if owner is None:
            lock = "the game lock is not held (/tmp/ff-tools/gtaiv-lock.sh acquire <owner> first)"
        elif owner != a.owner:
            lock = "the game lock is held by '%s', not by --owner '%s'" % (owner, a.owner)
        if lock and not a.dry_run:
            return [lock]
        if lock:
            self.say("dry run, would refuse: " + lock)
        why = []
        if self.game_running():
            why.append("GTA IV is already running")
        if not os.path.exists(GADGET):
            why.append("the frida gadget is not installed (%s); the route and the quit need it" % GADGET)
        for f in self.table.get("_snapshot_files", []):
            if not os.path.isfile(os.path.join(a.snapshot, f)):
                why.append("snapshot %s has no %s" % (a.snapshot, f))
        for src in self.dropin_sources():
            if not os.path.isfile(src):
                why.append("drop-in source missing: %s" % src)
            elif os.path.splitext(src)[1].lower() not in DROP_DIRS:
                why.append("drop-in %s: only .bin and .foz go in the drop-in folders" % src)
        _, foreign = self.dropin_folders_state()
        if foreign:
            why.append("the drop-in folders hold files this runner did not put there (it never deletes "
                       "them): %s" % ", ".join(os.path.relpath(f, G) for f in foreign))
        why += self.check_ini(exp)
        return why

    # ---- staging ------------------------------------------------------------------
    def dropin_sources(self):
        srcs = list(self.cond.get("dropins", [])) + list(self.a.dropin)
        return [s if os.path.isabs(s) else os.path.join(REPO, s) for s in srcs]

    def clean_copies(self, when):
        copies, _ = self.dropin_folders_state()
        states = self.state_files()
        for f in copies + states:
            os.remove(f)
        for d, existed in self.dirs_before.items():
            p = os.path.join(PLUGINS, d)
            if not existed and os.path.isdir(p) and not os.listdir(p):
                os.rmdir(p)
        if copies or states:
            self.say("removed %s (%s)" % (", ".join(os.path.relpath(f, G) for f in copies + states), when))
        return [os.path.relpath(f, G) for f in copies + states]

    def stage(self):
        out = []
        for src in self.dropin_sources():
            ext = os.path.splitext(src)[1].lower()
            d = os.path.join(PLUGINS, DROP_DIRS[ext])
            os.makedirs(d, exist_ok=True)
            name = dropin_name(src)
            dst = os.path.join(d, name)
            self.install(src, dst)
            out.append({"src": os.path.relpath(src, REPO) if src.startswith(REPO) else src,
                        "dst": os.path.relpath(dst, G), "size": os.path.getsize(dst), "sha256": sha256(dst)})
            self.say("staged %s -> %s" % (src, os.path.relpath(dst, G)))
        return out

    def restore_snapshot(self, when):
        for f in sorted(os.listdir(self.a.snapshot)):
            self.install(os.path.join(self.a.snapshot, f), os.path.join(PLUGINS, f))
        self.say("snapshot recordings put back (%s)" % when)

    def recordings(self):
        return {f: {"size": os.path.getsize(os.path.join(PLUGINS, f)) if os.path.exists(os.path.join(PLUGINS, f))
                    else None, "sha256": sha256(os.path.join(PLUGINS, f))}
                for f in sorted(os.listdir(self.a.snapshot))}

    def plugin_files(self):
        return {e: os.path.getsize(os.path.join(PLUGINS, e)) for e in os.listdir(PLUGINS)
                if e.startswith("FusionFix.") and os.path.isfile(os.path.join(PLUGINS, e))}

    def dxvk_cache(self):
        if not os.path.isdir(DXVK_CACHE):
            return None
        return {e: {"size": os.path.getsize(os.path.join(DXVK_CACHE, e)),
                    "mtime": int(os.path.getmtime(os.path.join(DXVK_CACHE, e)))} for e in sorted(os.listdir(DXVK_CACHE))}

    def clear_mesa(self):
        if not os.path.isdir(MESA_CACHE):
            return {"dir": MESA_CACHE, "bytes_before": None}
        size = du(MESA_CACHE)
        subprocess.run(["find", MESA_CACHE, "-mindepth", "1", "-delete"], check=True)
        self.say("cleared %s (%.1f MB)" % (MESA_CACHE, size / 1e6))
        return {"dir": MESA_CACHE, "bytes_before": size, "bytes_after": du(MESA_CACHE)}

    # ---- the game -----------------------------------------------------------------
    def launch(self):
        self.t0 = time.time()
        subprocess.Popen(["steam", "steam://rungameid/12210"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(100):
            time.sleep(3)
            p = pids(GAME_RE)
            if p:
                self.say("game up after %.0fs (pid %d)" % (time.time() - self.t0, p[0]))
                return p[0]
        return None

    def dump_env(self, pid):
        lines = []
        try:
            with open("/proc/%d/environ" % pid, "rb") as f:
                lines = sorted(s for s in (kv.decode("utf-8", "replace") for kv in f.read().split(b"\0"))
                               if ENV_KEYS.match(s))
        except OSError as e:
            lines = ["# environ not readable: %s" % e]
        with open(os.path.join(self.rundir, "env.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        env = dict(l.split("=", 1) for l in lines if "=" in l and not l.startswith("#"))
        # Cold only counts if the game's Mesa cache is the folder we emptied.
        where = env.get("MESA_SHADER_CACHE_DIR") or (os.path.join(env["XDG_CACHE_HOME"], "mesa_shader_cache")
                                                     if env.get("XDG_CACHE_HOME") else MESA_CACHE)
        self.meta["game_mesa_cache"] = where
        self.meta["mesa_cache_disabled"] = env.get("MESA_SHADER_CACHE_DISABLE", "").lower() in ("1", "true")
        if self.meta["cold"]:
            ok = os.path.realpath(where).startswith(os.path.realpath(MESA_CACHE)) and not self.meta["mesa_cache_disabled"]
            self.meta["cold_verified"] = ok
            if not ok:
                self.say("WARNING: the game's Mesa cache is %s, which this cold run did not clear" % where)

    def wait_pass(self):
        t = time.time()
        while time.time() - t < self.a.pass_timeout:
            time.sleep(2)
            if not self.game_running():
                self.say("GAME EXITED during loading")
                return None
            try:
                if os.path.getmtime(LOG) <= self.t0:
                    continue
                with open(LOG, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            for m in PASS_DONE:
                if m in text:
                    self.say("loading-screen pass done ('%s') %.0fs after launch" % (m, time.time() - self.t0))
                    return "ran"
            for m in PASS_NONE:
                if m in text:
                    self.say("no loading-screen pass ('%s')" % m)
                    return "none"
        self.say("loading-screen pass not done after %.0fs" % self.a.pass_timeout)
        return None

    def route(self):
        cmd = [sys.executable, "-u", ROUTE_PY, "run", "--route", self.a.route, "--log", LOG,
               "--out", os.path.join(self.rundir, "route.json"), "--settle", str(self.a.settle),
               "--ready-timeout", str(self.a.ready_timeout)] + (["--no-refocus"] if self.a.no_refocus else [])
        # Bytes, so the driver's "\r" progress lines stay whole in route.log and can be left
        # out of the console (text mode would turn every "\r" into a line of its own).
        with open(os.path.join(self.rundir, "route.log"), "ab") as sink:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for raw in p.stdout:
                sink.write(raw); sink.flush()
                line = raw.decode("utf-8", "replace").rstrip("\n").split("\r")[-1]
                if line.strip():
                    print("    " + line.rstrip(), flush=True)
            return p.wait()

    def quit(self):
        for _ in range(3):
            if not self.game_running():
                break
            r = subprocess.run([sys.executable, QUIT], capture_output=True, text=True)
            self.say("gtaiv-quit exit %d: %s" % (r.returncode, (r.stdout + r.stderr).strip()))
            if r.returncode == 0:
                break
            time.sleep(10)
        t = time.time()
        while time.time() - t < 180:
            if not pids(GAME_RE) and not pids(LAUNCHER_RE):
                time.sleep(3)
                return True
            time.sleep(1)
        return False

    def sleep_watch(self, seconds, what):
        end = time.time() + seconds
        while time.time() < end:
            time.sleep(min(2.0, max(0.0, end - time.time())))
            if not self.game_running():
                self.say("GAME EXITED during %s" % what)
                return False
        return True

    # ---- the run ------------------------------------------------------------------
    def run(self):
        a, m = self.a, self.meta
        m["cold"] = a.cold if a.cold is not None else bool(self.cond.get("cold", True))
        exp = self.expectations()
        m["expect"] = exp
        m["asi_sha256"] = sha256(ASI)
        m["ini_sha256"] = sha256(INI)
        m["route_file"] = a.route
        why = self.preflight(exp)
        if why:
            for w in why:
                self.say("REFUSED: " + w)
            m["refused"] = why
            self.write_meta()
            return 2
        if a.dry_run:
            self.say("dry run: preflight passed; would stage %s, cold=%s"
                     % ([dropin_name(s) for s in self.dropin_sources()], m["cold"]))
            self.write_meta()
            return 0

        rc = 1
        try:
            self.restore_snapshot("before the run")
            m["removed_before"] = self.clean_copies("before the run")
            m["dropins"] = self.stage()
            m["recordings_before"] = self.recordings()
            m["plugins_before"] = self.plugin_files()
            m["dxvk_shader_cache"] = self.dxvk_cache()
            m["mesa_before_bytes"] = du(MESA_CACHE) if os.path.isdir(MESA_CACHE) else None
            if m["cold"]:
                m["mesa_cleared"] = self.clear_mesa()

            pid = self.launch()
            m["launch_epoch"] = round(self.t0, 3)
            if not pid:
                self.say("the game never started")
                return 1
            time.sleep(5)
            self.dump_env(pid)
            m["pass"] = self.wait_pass()
            m["pass_done_s"] = round(time.time() - self.t0, 1)
            m["log_at_pass"] = self.log_size()
            if m["pass"] is None:
                return 1
            rr = self.route()
            m["route_exit"] = rr
            m["route_done_s"] = round(time.time() - self.t0, 1)
            if not self.game_running():
                self.say("GAME EXITED during the route")
                return 1
            self.say("route done (exit %d); playing on for %ds" % (rr, a.tail))
            if not self.sleep_watch(a.tail, "the tail"):
                return 1
            m["log_at_prequit"] = self.log_size()
            shutil.copy2(LOG, os.path.join(self.rundir, "FusionFix.shaders.prequit.log"))
            rc = 0 if rr == 0 else 3
        finally:
            if self.game_running():
                m["quit_clean"] = self.quit()
            m["ended_s"] = round(time.time() - self.t0, 1) if self.t0 else None
            if self.t0 and os.path.exists(LOG) and os.path.getmtime(LOG) > self.t0:
                shutil.copy2(LOG, os.path.join(self.rundir, "FusionFix.shaders.log"))
            if self.t0 and os.path.exists(DXVK_LOG) and os.path.getmtime(DXVK_LOG) > self.t0:
                shutil.copy2(DXVK_LOG, os.path.join(self.rundir, "GTAIV_d3d9.log"))
            if self.game_running():
                self.say("GTA IV is STILL RUNNING: drop-ins and recordings left as they are")
                rc = 1
            else:
                m["recordings_after"] = self.recordings()
                after = self.plugin_files()
                m["plugins_new"] = sorted(set(after) - set(m.get("plugins_before", {})))
                m["removed_after"] = self.clean_copies("after the run")
                self.restore_snapshot("after the run")
                m["mesa_after_bytes"] = du(MESA_CACHE) if os.path.isdir(MESA_CACHE) else None
            m["exit"] = rc
            self.write_meta()
            self.say("results in %s (exit %d)" % (self.rundir, rc))
        return rc

    def write_meta(self):
        with open(os.path.join(self.rundir, "meta.json"), "w") as f:
            json.dump(self.meta, f, indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name-of", nargs="+", metavar="FILE", help="print each file's drop-in name and exit")
    ap.add_argument("--condition", help="a condition from --conditions")
    ap.add_argument("--run", type=int)
    ap.add_argument("--owner", default=os.environ.get("GTAIV_LOCK_OWNER"),
                    help="who holds /tmp/ff-tools/gtaiv-lock.sh (default $GTAIV_LOCK_OWNER)")
    cold = ap.add_mutually_exclusive_group()
    cold.add_argument("--cold", dest="cold", action="store_true", default=None,
                      help="empty ~/.cache/mesa_shader_cache first (the condition's default)")
    cold.add_argument("--warm", dest="cold", action="store_false", help="keep the Mesa cache")
    ap.add_argument("--expect", action="append", default=[], metavar="KEY=VALUE",
                    help="assert one more [SHADERS] value, or override the condition's")
    ap.add_argument("--dropin", action="append", default=[], metavar="FILE",
                    help="stage one more .bin/.foz (repo-relative or absolute) for this run")
    ap.add_argument("--conditions", default=os.path.join(HERE, "conditions.json"))
    ap.add_argument("--route", default=os.path.join(HERE, "routes", "lc-districts.json"))
    ap.add_argument("--no-refocus", action="store_true", help="report freezes, never focus the window")
    ap.add_argument("--settle", type=int, default=15, help="live seconds in gameplay before the route")
    ap.add_argument("--tail", type=int, default=20,
                    help="seconds after the route before the quit (FusionFix reports every 15 s)")
    ap.add_argument("--pass-timeout", type=int, default=3600)
    ap.add_argument("--ready-timeout", type=int, default=900)
    ap.add_argument("--results", default="/tmp/ff-results")
    ap.add_argument("--snapshot", default="/tmp/ff-tools/snapshot")
    ap.add_argument("--dry-run", action="store_true", help="preflight only; touches nothing")
    ap.add_argument("--force", action="store_true", help="reuse an existing run folder")
    a = ap.parse_args()
    if a.name_of:
        for f in a.name_of:
            print("%s  %s -> %s" % (dropin_name(f), f, DROP_DIRS.get(os.path.splitext(f)[1].lower(), "?")))
        return 0
    if not a.condition or a.run is None:
        ap.error("--condition and --run are required")
    if not a.owner:
        ap.error("--owner (or $GTAIV_LOCK_OWNER) is required: the runner only runs under the game lock")
    with open(a.conditions) as f:
        table = json.load(f)
    conds = table.get("conditions", {})
    if a.condition not in conds:
        ap.error("unknown condition '%s' (have: %s)" % (a.condition, ", ".join(conds)))
    rundir = os.path.join(a.results, "_dry-run" if a.dry_run else a.condition, "run%d" % a.run)
    if os.path.exists(rundir) and not a.force and not a.dry_run:
        ap.error("%s exists (use another --run, or --force)" % rundir)
    os.makedirs(rundir, exist_ok=True)
    return Runner(a, table, conds[a.condition], rundir).run()


if __name__ == "__main__":
    sys.exit(main())

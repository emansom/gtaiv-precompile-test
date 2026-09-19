#!/usr/bin/env python3
"""Summarise gameplay_run.py results as markdown tables.

  gpparse.py [RESULTS_OR_RUN_DIR ...] [--cols a,b,...] [--all-cols] [--json]
  gpparse.py --log FusionFix.shaders.log      one log, no run folder around it

Reads <results>/<condition>/run<N>/ (meta.json, route.json, FusionFix.shaders.log) and
prints one row per run, then per condition the mean and range of every numeric column.
Columns that no run has a value for are left out, so a build without a line simply has no
column for it.

EXTENDING: every number comes from METRICS below: a column name, a regex whose first
group is the value, and how to combine the matching lines:
  last      the last match (the cumulative counters: the value at exit)
  first     the first match
  count     how many lines match
  sum, max  over the matches' values
  delta     a cumulative counter across the route: the first report after the route's
            end (else the last one before it) minus the last one before its start.
            FusionFix reports every 15 s (141a876: only when the count changed), so the
            window can reach up to 15 s past either end.
and the window: "all" (the whole log) or "route" (only lines written while the route
ran: route.json records the log's size at the route's start and end), and optionally a
line that must be in the log for the metric to apply (a count of 0 from a build that
never writes the line is not a result). A new line in a new build is one more entry here.
"""
import argparse
import glob
import json
import os
import re
import statistics
import sys

# The ", >=5 ms (compiled): M" part of CreateTimes::Describe (vkcapture.ixx):
#   N pipelines (L libraries, K linked); >=1 ms: a, >=5 ms (compiled): b (c libraries), >=20 ms: d; worst W ms
GP = r"created by DXVK in gameplay(?: so far)?: "
BEFORE = r"created by DXVK before gameplay: "
# d3c5dc1 counts creations on a loading screen that came back after gameplay had started
# apart from gameplay's own, so a mission load is not read as a stutter.
LATER_LS = r"created by DXVK on later loading screens(?: so far)?: "
FRAMES = r"gameplay frames(?: final)? t=[\d.]+ play=[\d.]+s: "
# A count is only a result where the build writes that kind of line at all: an optional
# fifth element names a line that shows it does (otherwise the column stays empty).
ORDERED = r"\[ShaderPrecompile\] order: 1\. "          # the build with the quiet waits
METERED = r"\[VkCapture\] metrics: gameplay starts"     # the build with frame times

METRICS = [
    # the loading screen
    ("load_pass_s",    r"\[ShaderPrecompile\] precompile complete in ([\d.]+)s", "last", "all"),
    ("load_hold_s",    r"held the loading screen ([\d.]+)s", "last", "all"),
    # "wait after <what>: <quiet | NOT quiet, gave up | stopped by ...> at t= after <s>s (GPU drain ...) ..."
    ("quiet_waits",    r"\[ShaderPrecompile\] wait after ", "count", "all", ORDERED),
    ("quiet_s",        r"\[ShaderPrecompile\] wait after .*? after ([\d.]+)s \(GPU drain", "sum", "all"),
    ("quiet_gave_up",  r"\[ShaderPrecompile\] wait after [^:]*: NOT quiet", "count", "all", ORDERED),
    ("load_released_t", r"order: 3\. loading screen released, t=([\d.]+)", "last", "all"),
    ("vk_replay_s",    r"\[VkCapture\] replay: done(?: t=[\d.]+)? in ([\d.]+)s", "last", "all"),
    ("vk_shared_kb",   r"\[VkCapture\] share: wrote .*? \((\d+) KB\)", "last", "all"),
    ("vk_replayed",    r"\[VkCapture\] replay: done.*?: (\d+) entries created", "last", "all"),
    ("vk_foreign",     r"\[VkCapture\] replay: foreign, .*?: (\d+) entries created", "last", "all"),
    ("vk_foreign_not_relevant", r"\[VkCapture\] replay: foreign, .*?skipped: (\d+) not relevant", "last", "all"),
    ("d3d9_drawn",     r"\[ShaderPrecompile\] replay: drew (\d+) of \d+ pipelines", "last", "all"),
    ("before_pipes",   BEFORE + r"(\d+) pipelines", "last", "all"),
    ("before_compiled", BEFORE + r".*?>=5 ms \(compiled\): (\d+)", "last", "all"),
    # gameplay: DXVK's own pipeline creations (cumulative; the last line is the value at exit)
    ("gp_pipes",       GP + r"(\d+) pipelines", "last", "all"),
    ("gp_compiled",    GP + r".*?>=5 ms \(compiled\): (\d+)", "last", "all"),
    ("gp_over20",      GP + r".*?>=20 ms: (\d+)", "last", "all"),
    ("gp_worst_ms",    GP + r".*?worst ([\d.]+) ms", "last", "all"),
    ("route_gp_pipes", GP + r"(\d+) pipelines", "delta", "route"),
    ("route_gp_compiled", GP + r".*?>=5 ms \(compiled\): (\d+)", "delta", "route"),
    # a loading screen after gameplay started (a mission load): counted, never a stutter
    ("ls_pipes",       LATER_LS + r"(\d+) pipelines", "last", "all"),
    ("ls_compiled",    LATER_LS + r".*?>=5 ms \(compiled\): (\d+)", "last", "all"),
    # one line per creation >= 20 ms: "gameplay: DXVK spent" (141a876), "gameplay compile t=" (later)
    ("route_slow_compiles", r"gameplay(?: compile t=[\d.]+)?: DXVK spent", "count", "route", BEFORE),
    # gameplay frame times (vkcapture, from the build with the metrics)
    ("fps_avg",        FRAMES + r".*?avg ([\d.]+) fps", "last", "all"),
    ("p50_ms",         FRAMES + r".*?p50 ([\d.]+) ms", "last", "all"),
    ("p99_ms",         FRAMES + r".*?p99 ([\d.]+) ms", "last", "all"),
    ("max_ms",         FRAMES + r".*?max ([\d.]+) ms", "last", "all"),
    ("spikes",         FRAMES + r".*?spikes (\d+)", "last", "all"),
    ("over50",         FRAMES + r".*?>50 ms (\d+)", "last", "all"),
    ("route_long_frames", r"gameplay long frame t=", "count", "route", METERED),
    ("route_long_spikes", r"gameplay long frame t=.*spike yes", "count", "route", METERED),
    ("route_worst_frame_ms", r"gameplay long frame t=[\d.]+: ([\d.]+) ms", "max", "route"),
    ("faults",         r"FAULT|faulted", "count", "all"),
]

DEFAULT_COLS = ["condition", "run", "cold", "load_s", "load_pass_s", "load_hold_s", "quiet_s", "quiet_gave_up",
                "vk_replayed",
                "gp_pipes", "gp_compiled", "gp_over20", "gp_worst_ms", "route_gp_pipes", "route_gp_compiled",
                "route_slow_compiles", "ls_compiled",
                "fps_avg", "p99_ms", "max_ms", "spikes", "over50", "route_long_frames", "route_worst_frame_ms",
                "route_ok", "route_live_s", "route_hangs", "route_hang_s", "frozen_s", "unfocused_s", "deviations",
                "faults"]
NUMERIC_SKIP = {"run"}


def num(s):
    try:
        return int(s)
    except ValueError:
        return float(s)


def parse_log(path, window=None):
    """Metrics from one FusionFix.shaders.log. window = (start, end) byte offsets of the route."""
    out = {}
    try:
        data = open(path, "rb").read()
    except OSError:
        return out
    lines, pos = [], 0
    for raw in data.split(b"\n"):
        lines.append((pos, raw.decode("utf-8", "replace")))
        pos += len(raw) + 1
    for name, rx, how, win, *needs in METRICS:
        rxc = re.compile(rx)
        if win == "route" and (window is None or None in window):
            continue
        if needs and not any(re.search(needs[0], l) for _, l in lines):
            continue
        if how == "delta":
            hits = [(p, num(m.group(1))) for p, m in ((p, rxc.search(l)) for p, l in lines) if m]
            before = [v for p, v in hits if p < window[0]]
            after = [v for p, v in hits if p >= window[1]]
            upto = [v for p, v in hits if p < window[1]]
            if after or upto:          # 141a876 reports only when the count changed
                out[name] = (after[0] if after else upto[-1]) - (before[-1] if before else 0)
            continue
        if win == "route":
            sel = [l for p, l in lines if window[0] <= p < window[1]]
        else:
            sel = [l for _, l in lines]
        hits = [m for m in (rxc.search(l) for l in sel) if m]
        if how == "count":
            out[name] = len(hits)
            continue
        vals = [num(m.group(1)) for m in hits if m.groups()]
        if not vals:
            continue
        out[name] = {"last": vals[-1], "first": vals[0], "sum": sum(vals), "max": max(vals)}[how]
    return out


def parse_run(d):
    row = {"dir": d}
    meta = route = {}
    try:
        meta = json.load(open(os.path.join(d, "meta.json")))
    except (OSError, ValueError):
        pass
    try:
        route = json.load(open(os.path.join(d, "route.json")))
    except (OSError, ValueError):
        pass
    row["condition"] = meta.get("condition", os.path.basename(os.path.dirname(d)))
    row["run"] = meta.get("run", os.path.basename(d))
    row["cold"] = ("cold" if meta.get("cold_verified", meta.get("cold")) else "warm") if meta else None
    if meta.get("cold") and meta.get("cold_verified") is False:
        row["cold"] = "COLD?"
    row["asi"] = (meta.get("asi_sha256") or "")[:12] or None
    row["exit"] = meta.get("exit")
    if meta.get("pass_done_s") is not None:
        row["load_s"] = meta["pass_done_s"]
    log = os.path.join(d, "FusionFix.shaders.log")
    if not os.path.exists(log):
        log = os.path.join(d, "FusionFix.shaders.prequit.log")
    row.update(parse_log(log, (route.get("log_at_start"), route.get("log_at_end"))))
    if route:
        row["route_ok"] = "yes" if route.get("clean") else ("done" if route.get("completed") else "NO")
        row["route_live_s"] = route.get("route_live_s")
        row["frozen_s"] = route.get("route_frozen_s")
        row["unfocused_s"] = route.get("route_unfocused_s")
        hangs = [h for h in route.get("hangs", []) if h.get("in_route")]
        row["route_hangs"] = len(hangs)
        row["route_hang_s"] = round(sum(h["seconds"] for h in hangs), 2)
        row["deviations"] = len(route.get("deviations", []))
        row["driven_m"] = route.get("driven_m")
    return row


def find_runs(paths):
    runs = []
    for p in paths:
        if os.path.isfile(os.path.join(p, "meta.json")):
            runs.append(p)
        else:
            runs += sorted(os.path.dirname(m) for m in glob.glob(os.path.join(p, "*", "run*", "meta.json"))
                           if "/_dry-run/" not in m)
    return runs


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".") if abs(v) < 100 else "%.0f" % v
    return str(v)


def table(rows, cols):
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        out.append("| " + " | ".join(fmt(r.get(c)) for c in cols) + " |")
    return "\n".join(out)


def aggregate(rows, cols):
    groups = {}
    for r in rows:
        groups.setdefault(r["condition"], []).append(r)
    out = []
    for cond, rs in groups.items():
        a = {"condition": cond, "run": "n=%d" % len(rs)}
        for c in cols:
            vals = [r[c] for r in rs if isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool)]
            if c in NUMERIC_SKIP or not vals:
                continue
            m = statistics.mean(vals)
            a[c] = fmt(m) if min(vals) == max(vals) else "%s (%s-%s)" % (fmt(m), fmt(min(vals)), fmt(max(vals)))
        out.append(a)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=["/tmp/ff-results"])
    ap.add_argument("--log", help="parse one FusionFix.shaders.log and print its metrics")
    ap.add_argument("--cols", help="comma-separated columns (default: %s)" % ",".join(DEFAULT_COLS))
    ap.add_argument("--all-cols", action="store_true", help="every column any run has")
    ap.add_argument("--json", action="store_true", help="the rows as JSON instead")
    a = ap.parse_args()
    if a.log:
        print(json.dumps(parse_log(a.log), indent=1))
        return 0
    rows = [parse_run(d) for d in find_runs(a.paths)]
    if not rows:
        print("no runs under %s" % ", ".join(a.paths), file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(rows, indent=1))
        return 0
    if a.all_cols:
        cols = []
        for r in rows:
            cols += [k for k in r if k not in cols and k != "dir"]
    else:
        cols = a.cols.split(",") if a.cols else DEFAULT_COLS
    cols = [c for c in cols if c in ("condition", "run") or any(r.get(c) is not None for r in rows)]
    print(table(rows, cols))
    print()
    print(table(aggregate(rows, cols), cols))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# gtaiv-precompile-test -- frame-time spike analyzer (OPTIONAL richer path).
#
# The zero-install happy path is run/Analyze-FrameTimes.ps1 (PowerShell, on every
# stock Windows box). THIS Python version is the optional richer analysis: same
# robust spike-detection algorithm, plus PresentMon CSV parsing and JSON output.
# The two are kept algorithmically identical on purpose.
#
# It ingests a per-frame frame-time log (PresentMon CSV, a MangoHud CSV, or a
# generic CSV) and detects shader-compile-stutter spikes: isolated large
# frame-time outliers that are the signature of a first-use shader/pipeline
# compile blocking the render thread. It reports the frame-time percentile
# distribution and, given two logs, an A/B PASS/FAIL verdict (precompile OFF vs
# ON) for "in-gameplay compile stutter eliminated".
#
# Usage:
#   python analyze_frametimes.py off.csv on.csv            # A/B verdict (exit 0/1)
#   python analyze_frametimes.py capture.csv               # single report
# See CLAUDE.md / README.md. No game interaction; pure log analysis.

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field, asdict

try:
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:
    _HAVE_NUMPY = False


# ----------------------------------------------------------------------------
# Tiny numpy shim so this runs even on a minimal Python without numpy.
# ----------------------------------------------------------------------------
if _HAVE_NUMPY:
    def _median(x): return float(np.median(x))
    def _mean(x): return float(np.mean(x))
    def _percentile(x, q): return float(np.percentile(x, q))
    def _asarray(x): return np.asarray(x, dtype=float)
else:
    def _asarray(x): return list(map(float, x))

    def _median(x):
        s = sorted(x)
        n = len(s)
        if n == 0:
            return 0.0
        m = n // 2
        return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0

    def _mean(x):
        return sum(x) / len(x) if x else 0.0

    def _percentile(x, q):
        s = sorted(x)
        n = len(s)
        if n == 0:
            return 0.0
        if n == 1:
            return s[0]
        pos = (q / 100.0) * (n - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return s[lo]
        return s[lo] + (s[hi] - s[lo]) * (pos - lo)


# ----------------------------------------------------------------------------
# Loading -- auto-detect PresentMon / MangoHud / generic CSV.
# ----------------------------------------------------------------------------

_FRAMETIME_COLS = ("dt_ms", "frametime_ms", "frametime", "ms", "frame_time_ms",
                   "msbetweenpresents", "msbetweendisplaychange")
_TIME_COLS = ("t_wall_ns", "t_ns", "t_ms", "t_us", "elapsed", "time",
              "timestamp", "timeinseconds", "cpustarttime")


@dataclass
class FrameLog:
    dt_ms: list
    t_ms: list
    source: str
    path: str
    dropped: int = 0
    notes: list = field(default_factory=list)

    @property
    def n(self):
        return len(self.dt_ms)


def _read_rows(path):
    with open(path, "r", newline="", errors="replace") as f:
        return [r for r in csv.reader(f) if r]


def _sniff(path):
    with open(path, "r", errors="replace") as f:
        head = "".join(f.readline() for _ in range(4)).lower()
    if "msbetweenpresents" in head or ("presentmode" in head and
                                       ("frametime" in head or "presentruntime" in head)):
        return "presentmon"
    if ("frametime" in head and "fps" in head) or head.startswith("os,"):
        return "mangohud"
    return "generic"


def _load_presentmon(path):
    """PresentMon CSV (1.x classic + 2.x). Frame time = msBetweenPresents (1.x)
    or FrameTime/MsBetweenPresents (2.x); time = TimeInSeconds/CPUStartTime
    (seconds). Drops 'Dropped'==1 (1.x) and non-'Application' FrameType (2.x)."""
    rows = _read_rows(path)
    if not rows:
        raise ValueError("empty PresentMon CSV")
    hdr = [c.strip().lower() for c in rows[0]]

    def col(*names):
        for nm in names:
            if nm in hdr:
                return hdr.index(nm)
        return None

    ft_i = col("msbetweenpresents", "frametime", "msbetweendisplaychange")
    t_i = col("timeinseconds", "cpustarttime")
    drop_i = col("dropped")
    ftype_i = col("frametype")
    if ft_i is None:
        raise ValueError("PresentMon CSV: no frame-time column "
                         "(msBetweenPresents / FrameTime)")
    dt, t_s, dropped = [], [], 0
    for r in rows[1:]:
        try:
            if drop_i is not None and drop_i < len(r):
                dv = r[drop_i].strip().lower()
                if dv in ("1", "true"):
                    dropped += 1
                    continue
            if ftype_i is not None and ftype_i < len(r):
                fv = r[ftype_i].strip().lower()
                if fv and fv not in ("application", ""):   # skip Repeated/Intel etc.
                    dropped += 1
                    continue
            v = float(r[ft_i])
            if v <= 0:
                dropped += 1
                continue
            dt.append(v)
            if t_i is not None and t_i < len(r) and r[t_i].strip():
                t_s.append(float(r[t_i]))
            else:
                t_s.append(None)
        except (ValueError, IndexError):
            dropped += 1
    # Time in seconds -> ms from start; fill gaps by cumulative dt.
    t_ms = _seconds_to_tms(t_s, dt)
    notes = ["PresentMon: frame time = %s" % hdr[ft_i]]
    return FrameLog(dt_ms=dt, t_ms=t_ms, source="presentmon", path=path,
                    dropped=dropped, notes=notes)


def _seconds_to_tms(t_s, dt):
    out = []
    base = None
    acc = 0.0
    for i, s in enumerate(t_s):
        if s is not None:
            if base is None:
                base = s
            acc = (s - base) * 1000.0
            out.append(acc)
        else:
            acc += float(dt[i])
            out.append(acc)
    return out


def _load_mangohud(path):
    with open(path, "r", errors="replace") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    hdr_idx = None
    for i, ln in enumerate(lines[:5]):
        low = ln.lower()
        if "frametime" in low and "fps" in low:
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ValueError("mangohud: no fps,frametime header")
    cols = [c.strip().lower() for c in lines[hdr_idx].split(",")]
    ft_i = cols.index("frametime") if "frametime" in cols else None
    el_i = cols.index("elapsed") if "elapsed" in cols else None
    dt, el_ns, dropped = [], [], 0
    for ln in lines[hdr_idx + 1:]:
        parts = ln.split(",")
        try:
            dt.append(float(parts[ft_i]))
            el_ns.append(float(parts[el_i]) if (el_i is not None and el_i < len(parts)
                                                and parts[el_i].strip()) else None)
        except (ValueError, IndexError, TypeError):
            dropped += 1
    notes = []
    if dt:
        med = _median(dt)
        if med > 1000:
            dt = [v / 1000.0 for v in dt]
            notes.append("mangohud frametime us -> ms")
        elif med < 1.0:
            dt = [v * 1000.0 for v in dt]
            notes.append("mangohud frametime s -> ms")
    if any(e is not None for e in el_ns):
        t_ms, base, acc = [], None, 0.0
        for i, e in enumerate(el_ns):
            if e is not None:
                base = e if base is None else base
                acc = (e - base) / 1e6
            else:
                acc += dt[i]
            t_ms.append(acc)
    else:
        t_ms = _cumsum(dt)
    return FrameLog(dt_ms=dt, t_ms=t_ms, source="mangohud", path=path,
                    dropped=dropped, notes=notes)


def _cumsum(dt):
    out, acc = [], 0.0
    for i, d in enumerate(dt):
        acc += d
        out.append(acc - dt[0] if dt else 0.0)
    return out


def _load_generic(path):
    rows = [r for r in _read_rows(path) if not r[0].lstrip().startswith("#")]
    if not rows:
        raise ValueError("empty CSV")
    header = [c.strip().lower() for c in rows[0]]
    has_header = any(h in _FRAMETIME_COLS or h in _TIME_COLS for h in header)
    if has_header:
        ft_col = next((header.index(c) for c in _FRAMETIME_COLS if c in header), None)
        t_col = next((header.index(c) for c in _TIME_COLS if c in header), None)
        t_name = header[t_col] if t_col is not None else None
        data = rows[1:]
    else:
        if len(rows[0]) >= 3:
            t_col, ft_col, t_name = 1, 2, "t_wall_ns"
        else:
            t_col, ft_col, t_name = None, len(rows[0]) - 1, None
        data = rows
    if ft_col is None:
        raise ValueError("generic CSV: no frame-time column (need one of %s)"
                         % (_FRAMETIME_COLS,))
    dt, tv, dropped = [], [], 0
    for r in data:
        try:
            dt.append(float(r[ft_col]))
            tv.append(float(r[t_col]) if (t_col is not None and t_col < len(r)
                                          and r[t_col].strip()) else None)
        except (ValueError, IndexError):
            dropped += 1
    if tv and any(x is not None for x in tv):
        scale = _time_scale(t_name)
        t0 = next(x for x in tv if x is not None)
        t_ms, last = [], 0.0
        for i, x in enumerate(tv):
            if x is not None:
                last = (x - t0) * scale
            else:
                last += dt[i]
            t_ms.append(last)
    else:
        t_ms = _cumsum(dt)
    return FrameLog(dt_ms=dt, t_ms=t_ms, source="generic", path=path, dropped=dropped)


def _time_scale(name):
    if not name:
        return 1.0
    name = name.lower()
    if name in ("t_wall_ns", "t_ns") or name.endswith("_ns") or name == "elapsed":
        return 1e-6
    if name in ("t_us",) or name.endswith("_us"):
        return 1e-3
    if name in ("timeinseconds", "cpustarttime", "time"):
        return 1e3
    return 1.0


def load(path):
    kind = _sniff(path)
    if kind == "presentmon":
        return _load_presentmon(path)
    if kind == "mangohud":
        try:
            return _load_mangohud(path)
        except Exception:
            pass
    return _load_generic(path)


# ----------------------------------------------------------------------------
# Spike detection (identical algorithm to Analyze-FrameTimes.ps1).
# ----------------------------------------------------------------------------

@dataclass
class Thresholds:
    window: int = 61
    excess_floor_ms: float = 8.0
    rel_factor: float = 1.5
    mad_k: float = 5.0
    isolation: int = 3
    warmup_frames: int = 0


@dataclass
class Report:
    path: str
    source: str
    n_frames: int
    duration_s: float
    dropped: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    p999_ms: float
    max_ms: float
    mean_fps: float
    spike_count: int
    isolated_spike_count: int
    total_excess_ms: float
    max_excess_ms: float
    thresholds: dict
    spikes: list
    notes: list = field(default_factory=list)


def _rolling_median(x, w):
    n = len(x)
    if n == 0:
        return []
    w = max(3, w | 1)
    half = w // 2
    out = [0.0] * n
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = _median(x[lo:hi])
    return out


def _mad(x):
    med = _median(x)
    return _median([abs(v - med) for v in x])


def analyze(log, th):
    dt = list(log.dt_ms)
    t = list(log.t_ms)
    notes = list(log.notes)
    if th.warmup_frames > 0 and len(dt) > th.warmup_frames:
        dt = dt[th.warmup_frames:]
        t = t[th.warmup_frames:]
        notes.append("dropped first %d warm-up frames" % th.warmup_frames)
    n = len(dt)
    if n == 0:
        raise ValueError("no frames after loading/warm-up")

    baseline = _rolling_median(dt, th.window)
    mad_global = _mad(dt) or 0.0
    mad_thresh = th.mad_k * 1.4826 * mad_global

    thr = [max(baseline[i] + th.excess_floor_ms,
               baseline[i] * th.rel_factor,
               baseline[i] + mad_thresh) for i in range(n)]
    idxs = [i for i in range(n) if dt[i] > thr[i]]
    spike_set = set(idxs)

    spikes = []
    for i in idxs:
        isolated = not any((j != i and j in spike_set)
                           for j in range(i - th.isolation, i + th.isolation + 1))
        spikes.append({
            "index": i,
            "t_ms": float(t[i]),
            "dt_ms": float(dt[i]),
            "baseline_ms": float(baseline[i]),
            "excess_ms": float(dt[i] - baseline[i]),
            "isolated": bool(isolated),
        })

    total_excess = sum(s["excess_ms"] for s in spikes)
    max_excess = max((s["excess_ms"] for s in spikes), default=0.0)
    iso_count = sum(1 for s in spikes if s["isolated"])
    duration_s = (t[-1] - t[0]) / 1000.0 if n >= 2 else 0.0
    mean_ms = _mean(dt)

    return Report(
        path=log.path, source=log.source, n_frames=n, duration_s=duration_s,
        dropped=log.dropped, mean_ms=mean_ms, median_ms=_median(dt),
        p95_ms=_percentile(dt, 95), p99_ms=_percentile(dt, 99),
        p999_ms=_percentile(dt, 99.9), max_ms=max(dt),
        mean_fps=(1000.0 / mean_ms) if mean_ms > 0 else 0.0,
        spike_count=len(spikes), isolated_spike_count=iso_count,
        total_excess_ms=total_excess, max_excess_ms=max_excess,
        thresholds=asdict(th), spikes=spikes, notes=notes)


# ----------------------------------------------------------------------------
# Presentation.
# ----------------------------------------------------------------------------

def _fmt_report(rep, show_spikes=True, max_list=25):
    L = ["=" * 68, "Frame-time report: %s" % rep.path,
         "  source=%s  frames=%d  duration=%.1fs  dropped=%d"
         % (rep.source, rep.n_frames, rep.duration_s, rep.dropped)]
    for note in rep.notes:
        L.append("  note: %s" % note)
    L += ["-" * 68,
          "  Frame time (ms):   mean=%.2f  median=%.2f  (mean %.1f fps)"
          % (rep.mean_ms, rep.median_ms, rep.mean_fps),
          "  Percentiles (ms):  p95=%.2f  p99=%.2f  p99.9=%.2f  max=%.2f"
          % (rep.p95_ms, rep.p99_ms, rep.p999_ms, rep.max_ms), "-" * 68]
    th = rep.thresholds
    L.append("  Spike gate: excess>=%.1fms AND (dt>=%.2fx baseline OR >%.1f*MAD),"
             " window=%d" % (th["excess_floor_ms"], th["rel_factor"],
                             th["mad_k"], th["window"]))
    L.append("  SPIKES: total=%d   ISOLATED (compile-like)=%d"
             % (rep.spike_count, rep.isolated_spike_count))
    L.append("  Lost time: total_excess=%.1fms  max_single=%.1fms"
             % (rep.total_excess_ms, rep.max_excess_ms))
    if show_spikes and rep.spikes:
        L.append("-" * 68)
        L.append("  %-7s %-9s %-9s %-9s %-9s %s"
                 % ("frame", "t(s)", "dt(ms)", "base(ms)", "excess", "kind"))
        for s in sorted(rep.spikes, key=lambda s: -s["excess_ms"])[:max_list]:
            L.append("  %-7d %-9.2f %-9.1f %-9.2f %-9.1f %s"
                     % (s["index"], s["t_ms"] / 1000.0, s["dt_ms"],
                        s["baseline_ms"], s["excess_ms"],
                        "ISOLATED" if s["isolated"] else "cluster"))
    L.append("=" * 68)
    return "\n".join(L)


def _verdict(base, cand, max_iso, p999_tol):
    return [
        ("baseline exercised cold compiles (isolated spikes > 0)",
         base.isolated_spike_count > 0, "INCONCLUSIVE"),
        ("candidate isolated compile spikes <= %d" % max_iso,
         cand.isolated_spike_count <= max_iso, "FAIL"),
        ("candidate p99.9 <= baseline p99.9 x%.2f (%.1f <= %.1f)"
         % (1 + p999_tol, cand.p999_ms, base.p999_ms * (1 + p999_tol)),
         cand.p999_ms <= base.p999_ms * (1 + p999_tol), "FAIL"),
        ("candidate total stutter <= baseline (%.0f <= %.0f ms)"
         % (cand.total_excess_ms, base.total_excess_ms),
         cand.total_excess_ms <= base.total_excess_ms, "FAIL"),
    ]


def _fmt_compare(base, cand, checks):
    L = ["#" * 68, "A/B  A=baseline(precompile OFF)  B=candidate(ON)", "#" * 68,
         "  %-20s %14s %14s %12s" % ("metric", "A (OFF)", "B (ON)", "delta"),
         "  " + "-" * 62]
    rows = [("frames", "%d", "n_frames"), ("duration (s)", "%.1f", "duration_s"),
            ("median ms", "%.2f", "median_ms"), ("p99 ms", "%.2f", "p99_ms"),
            ("p99.9 ms", "%.2f", "p999_ms"), ("max ms", "%.2f", "max_ms"),
            ("total spikes", "%d", "spike_count"),
            ("ISOLATED spikes", "%d", "isolated_spike_count"),
            ("total stutter ms", "%.0f", "total_excess_ms"),
            ("max single ms", "%.0f", "max_excess_ms")]
    for label, fmt, attr in rows:
        a, b = getattr(base, attr), getattr(cand, attr)
        try:
            delta = "%+.1f" % (b - a)
        except TypeError:
            delta = "-"
        L.append("  %-20s %14s %14s %12s" % (label, fmt % a, fmt % b, delta))
    L.append("  " + "-" * 62)
    ok = True
    for name, passed, failtag in checks:
        tag = "PASS" if passed else failtag
        if not passed and failtag == "FAIL":
            ok = False
        L.append("  [%-12s] %s" % (tag, name))
    L += ["#" * 68,
          "  VERDICT: %s" % ("PASS -- precompile ON shows zero isolated compile stutter"
                             if ok else "FAIL -- residual compile stutter remains"),
          "#" * 68]
    return "\n".join(L), ok


def build_argparser():
    p = argparse.ArgumentParser(description="Detect shader-compile stutter spikes.")
    p.add_argument("logs", nargs="+", help="one or two CSVs (2 => A/B: OFF then ON)")
    p.add_argument("--window", type=int, default=61)
    p.add_argument("--excess-floor", type=float, default=8.0)
    p.add_argument("--rel-factor", type=float, default=1.5)
    p.add_argument("--mad-k", type=float, default=5.0)
    p.add_argument("--isolation", type=int, default=3)
    p.add_argument("--warmup", type=int, default=0)
    p.add_argument("--max-iso-spikes", type=int, default=0)
    p.add_argument("--p999-tol", type=float, default=0.10)
    p.add_argument("--json", metavar="FILE")
    p.add_argument("--no-spike-list", action="store_true")
    return p


def main(argv=None):
    args = build_argparser().parse_args(argv)
    th = Thresholds(window=args.window, excess_floor_ms=args.excess_floor,
                    rel_factor=args.rel_factor, mad_k=args.mad_k,
                    isolation=args.isolation, warmup_frames=args.warmup)
    reports = [analyze(load(p), th) for p in args.logs]
    for rep in reports:
        print(_fmt_report(rep, show_spikes=not args.no_spike_list))
    exit_code, cmp_payload = 0, None
    if len(reports) == 2:
        checks = _verdict(reports[0], reports[1], args.max_iso_spikes, args.p999_tol)
        text, ok = _fmt_compare(reports[0], reports[1], checks)
        print("\n" + text)
        cmp_payload = {"checks": [{"name": n, "passed": bool(pd)} for n, pd, _ in checks],
                       "verdict": "PASS" if ok else "FAIL"}
        exit_code = 0 if ok else 1
    if args.json:
        payload = {"reports": [asdict(r) for r in reports]}
        if cmp_payload:
            payload["comparison"] = cmp_payload
        with open(args.json, "w") as f:
            json.dump(payload, f, indent=2)
        print("\nwrote %s" % args.json)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

#requires -Version 5.1
<#
.SYNOPSIS
  Detect shader-compile-stutter spikes in a frame-time capture, and A/B compare
  precompile OFF vs ON with a PASS/FAIL verdict. No Python, no modules -- it runs on
  PowerShell 7 (the supported setup) and still works on the 5.1 that ships in the box.

.DESCRIPTION
  Ingests a PresentMon CSV (classic 1.x 'msBetweenPresents' or 2.x 'FrameTime'),
  or a generic CSV. Detects ISOLATED large frame-time outliers -- the signature
  of a first-use shader/pipeline compile stalling the render thread -- using a
  rolling-median + MAD robust threshold, and reports the frame-time percentile
  distribution. This is a direct transliteration of the (unit-tested) Python
  python/analyze_frametimes.py; the algorithm is identical.

.PARAMETER Logs
  One or two CSV paths. One => single report. Two => A/B (first=OFF baseline,
  second=ON candidate) with a PASS/FAIL verdict and exit code (0 PASS, 1 FAIL).

.EXAMPLE
  .\Analyze-FrameTimes.ps1 .\results\raw\off.csv .\results\raw\on.csv -Json .\results\verdict.json
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]] $Logs,
    [int]    $Window        = 61,
    [double] $ExcessFloorMs = 8.0,
    [double] $RelFactor     = 1.5,
    [double] $MadK          = 5.0,
    [int]    $Isolation     = 3,
    [int]    $Warmup        = 0,
    [int]    $MaxIsoSpikes  = 0,
    [double] $P999Tol       = 0.10,
    [string] $Json          = $null,
    [switch] $NoSpikeList
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Inv = [System.Globalization.CultureInfo]::InvariantCulture
# Format with '.' decimals regardless of the tester's locale: this report gets pasted
# into a shared issue, where '94,83' reads as a different number. Parsing already
# forces $Inv explicitly, so this only affects output.
[System.Threading.Thread]::CurrentThread.CurrentCulture = $Inv

# --------------------------------------------------------------------------
# Numeric helpers (locale-safe: PresentMon writes '.' decimals).
# --------------------------------------------------------------------------
function ConvertTo-Double([string] $s) {
    if ([string]::IsNullOrWhiteSpace($s)) { return $null }
    $out = 0.0
    if ([double]::TryParse($s, [Globalization.NumberStyles]::Float, $Inv, [ref] $out)) {
        return $out
    }
    return $null
}

function Get-Median([double[]] $x) {
    $n = $x.Count
    if ($n -eq 0) { return 0.0 }
    $s = ($x | Sort-Object)
    $m = [int]([math]::Floor($n / 2))
    if ($n % 2 -eq 1) { return [double]$s[$m] }
    return ([double]$s[$m - 1] + [double]$s[$m]) / 2.0
}

function Get-Percentile([double[]] $x, [double] $q) {
    $n = $x.Count
    if ($n -eq 0) { return 0.0 }
    if ($n -eq 1) { return [double]$x[0] }
    $s = ($x | Sort-Object)
    $pos = ($q / 100.0) * ($n - 1)
    $lo = [int][math]::Floor($pos)
    $hi = [int][math]::Ceiling($pos)
    if ($lo -eq $hi) { return [double]$s[$lo] }
    return [double]$s[$lo] + ([double]$s[$hi] - [double]$s[$lo]) * ($pos - $lo)
}

function Get-RollingMedian([double[]] $x, [int] $w) {
    $n = $x.Count
    if ($n -eq 0) { return @() }
    if ($w -lt 3) { $w = 3 }
    if ($w % 2 -eq 0) { $w = $w + 1 }
    $half = [int]([math]::Floor($w / 2))
    $out = New-Object 'double[]' $n
    for ($i = 0; $i -lt $n; $i++) {
        $lo = [math]::Max(0, $i - $half)
        $hi = [math]::Min($n - 1, $i + $half)
        $slice = New-Object 'System.Collections.Generic.List[double]'
        for ($j = $lo; $j -le $hi; $j++) { $slice.Add([double]$x[$j]) }
        $out[$i] = Get-Median $slice.ToArray()
    }
    return $out
}

function Get-Mad([double[]] $x) {
    $med = Get-Median $x
    $abs = foreach ($v in $x) { [math]::Abs([double]$v - $med) }
    return Get-Median ([double[]]$abs)
}

# --------------------------------------------------------------------------
# Loading -- PresentMon / generic.
# --------------------------------------------------------------------------
function Get-Prop($row, [string[]] $names) {
    $props = $row.PSObject.Properties.Name
    foreach ($n in $names) {
        foreach ($p in $props) {
            if ($p -ieq $n) { return $p }
        }
    }
    return $null
}

function Import-FrameLog([string] $path) {
    if (-not (Test-Path -LiteralPath $path)) { throw "not found: $path" }
    $head = Get-Content -LiteralPath $path -TotalCount 4 -ErrorAction SilentlyContinue
    $headJoined = ($head -join "`n").ToLowerInvariant()
    $rows = Import-Csv -LiteralPath $path
    if ($rows.Count -eq 0) { throw "empty CSV: $path" }

    $dt = New-Object 'System.Collections.Generic.List[double]'
    $tms = New-Object 'System.Collections.Generic.List[double]'
    $dropped = 0
    $source = 'generic'
    $notes = @()

    $isPM = ($headJoined -match 'msbetweenpresents') -or `
            (($headJoined -match 'presentmode') -and `
             (($headJoined -match 'frametime') -or ($headJoined -match 'presentruntime')))

    if ($isPM) {
        $source = 'presentmon'
        $ftName  = Get-Prop $rows[0] @('msBetweenPresents','FrameTime','msBetweenDisplayChange')
        $tName   = Get-Prop $rows[0] @('TimeInSeconds','CPUStartTime')
        $dropName = Get-Prop $rows[0] @('Dropped')
        $ftypeName = Get-Prop $rows[0] @('FrameType')
        if (-not $ftName) { throw "PresentMon CSV: no frame-time column" }
        $notes += "PresentMon: frame time = $ftName"
        $base = $null; $acc = 0.0
        foreach ($r in $rows) {
            if ($dropName) {
                $dv = ([string]$r.$dropName).Trim().ToLowerInvariant()
                if ($dv -eq '1' -or $dv -eq 'true') { $dropped++; continue }
            }
            if ($ftypeName) {
                $fv = ([string]$r.$ftypeName).Trim().ToLowerInvariant()
                if ($fv -ne '' -and $fv -ne 'application') { $dropped++; continue }
            }
            $v = ConvertTo-Double ([string]$r.$ftName)
            if ($null -eq $v -or $v -le 0) { $dropped++; continue }
            $dt.Add([double]$v)
            if ($tName) {
                $ts = ConvertTo-Double ([string]$r.$tName)
                if ($null -ne $ts) {
                    if ($null -eq $base) { $base = $ts }
                    $acc = ($ts - $base) * 1000.0
                } else { $acc += [double]$v }
            } else { $acc += [double]$v }
            $tms.Add([double]$acc)
        }
    }
    else {
        # generic: look for a frametime column and optional time column.
        $ftName = Get-Prop $rows[0] @('dt_ms','frametime_ms','frametime','ms','frame_time_ms')
        $tName  = Get-Prop $rows[0] @('t_wall_ns','t_ns','t_ms','t_us','elapsed','time','timestamp')
        if (-not $ftName) { throw "generic CSV: no frame-time column (dt_ms/frametime/ms)" }
        $scale = 1.0
        if ($tName) {
            $tl = $tName.ToLowerInvariant()
            if ($tl -match '_ns$' -or $tl -eq 't_wall_ns' -or $tl -eq 'elapsed') { $scale = 1e-6 }
            elseif ($tl -match '_us$') { $scale = 1e-3 }
        }
        $base = $null; $acc = 0.0
        foreach ($r in $rows) {
            $v = ConvertTo-Double ([string]$r.$ftName)
            if ($null -eq $v) { $dropped++; continue }
            $dt.Add([double]$v)
            if ($tName) {
                $ts = ConvertTo-Double ([string]$r.$tName)
                if ($null -ne $ts) {
                    if ($null -eq $base) { $base = $ts }
                    $acc = ($ts - $base) * $scale
                } else { $acc += [double]$v }
            } else { $acc += [double]$v }
            $tms.Add([double]$acc)
        }
    }

    return [pscustomobject]@{
        Dt = $dt.ToArray(); Tms = $tms.ToArray(); Source = $source
        Path = $path; Dropped = $dropped; Notes = $notes
    }
}

# --------------------------------------------------------------------------
# Spike detection (identical to python/analyze_frametimes.py).
# --------------------------------------------------------------------------
function Invoke-Analyze($log) {
    $dt = [double[]]$log.Dt
    $tms = [double[]]$log.Tms
    $notes = @($log.Notes)
    if ($Warmup -gt 0 -and $dt.Count -gt $Warmup) {
        $dt = $dt[$Warmup..($dt.Count - 1)]
        $tms = $tms[$Warmup..($tms.Count - 1)]
        $notes += "dropped first $Warmup warm-up frames"
    }
    $n = $dt.Count
    if ($n -eq 0) { throw "no frames after loading/warm-up" }

    $baseline = Get-RollingMedian $dt $Window
    $madGlobal = Get-Mad $dt
    $madThresh = $MadK * 1.4826 * $madGlobal

    $spikeIdx = New-Object 'System.Collections.Generic.List[int]'
    for ($i = 0; $i -lt $n; $i++) {
        $thr = [math]::Max([math]::Max($baseline[$i] + $ExcessFloorMs, $baseline[$i] * $RelFactor),
                           $baseline[$i] + $madThresh)
        if ($dt[$i] -gt $thr) { $spikeIdx.Add($i) }
    }
    $spikeSet = @{}
    foreach ($i in $spikeIdx) { $spikeSet[$i] = $true }

    $spikes = New-Object 'System.Collections.Generic.List[object]'
    foreach ($i in $spikeIdx) {
        $isolated = $true
        for ($j = $i - $Isolation; $j -le $i + $Isolation; $j++) {
            if ($j -ne $i -and $spikeSet.ContainsKey($j)) { $isolated = $false; break }
        }
        $spikes.Add([pscustomobject]@{
            index = $i; t_ms = [double]$tms[$i]; dt_ms = [double]$dt[$i]
            baseline_ms = [double]$baseline[$i]; excess_ms = [double]($dt[$i] - $baseline[$i])
            isolated = $isolated
        })
    }

    $totalExcess = 0.0; $maxExcess = 0.0; $isoCount = 0
    foreach ($s in $spikes) {
        $totalExcess += $s.excess_ms
        if ($s.excess_ms -gt $maxExcess) { $maxExcess = $s.excess_ms }
        if ($s.isolated) { $isoCount++ }
    }
    $durationS = 0.0
    if ($n -ge 2) { $durationS = ($tms[$n - 1] - $tms[0]) / 1000.0 }
    $meanMs = ($dt | Measure-Object -Average).Average

    return [pscustomobject]@{
        path = $log.Path; source = $log.Source; n_frames = $n; duration_s = $durationS
        notes = $notes
        dropped = $log.Dropped; mean_ms = $meanMs; median_ms = (Get-Median $dt)
        p95_ms = (Get-Percentile $dt 95); p99_ms = (Get-Percentile $dt 99)
        p999_ms = (Get-Percentile $dt 99.9); max_ms = ($dt | Measure-Object -Maximum).Maximum
        mean_fps = $(if ($meanMs -gt 0) { 1000.0 / $meanMs } else { 0.0 })
        spike_count = $spikes.Count; isolated_spike_count = $isoCount
        total_excess_ms = $totalExcess; max_excess_ms = $maxExcess
        spikes = $spikes
        thresholds = [pscustomobject]@{ window = $Window; excess_floor_ms = $ExcessFloorMs
            rel_factor = $RelFactor; mad_k = $MadK; isolation = $Isolation; warmup_frames = $Warmup }
    }
}

# --------------------------------------------------------------------------
# Presentation.
# --------------------------------------------------------------------------
function Format-Report($rep) {
    $L = @()
    $L += ('=' * 68)
    $L += "Frame-time report: $($rep.path)"
    $L += ("  source={0}  frames={1}  duration={2:F1}s  dropped={3}" -f `
            $rep.source, $rep.n_frames, $rep.duration_s, $rep.dropped)
    foreach ($nt in $rep.notes) { $L += "  note: $nt" }
    $L += ('-' * 68)
    $L += ("  Frame time (ms):   mean={0:F2}  median={1:F2}  (mean {2:F1} fps)" -f `
            $rep.mean_ms, $rep.median_ms, $rep.mean_fps)
    $L += ("  Percentiles (ms):  p95={0:F2}  p99={1:F2}  p99.9={2:F2}  max={3:F2}" -f `
            $rep.p95_ms, $rep.p99_ms, $rep.p999_ms, $rep.max_ms)
    $L += ('-' * 68)
    $th = $rep.thresholds
    $L += ("  Spike gate: excess>={0:F1}ms AND (dt>={1:F2}x baseline OR >{2:F1}*MAD), window={3}" -f `
            $th.excess_floor_ms, $th.rel_factor, $th.mad_k, $th.window)
    $L += ("  SPIKES: total={0}   ISOLATED (compile-like)={1}" -f `
            $rep.spike_count, $rep.isolated_spike_count)
    $L += ("  Lost time: total_excess={0:F1}ms  max_single={1:F1}ms" -f `
            $rep.total_excess_ms, $rep.max_excess_ms)
    if (-not $NoSpikeList -and $rep.spikes.Count -gt 0) {
        $L += ('-' * 68)
        $L += ("  {0,-7} {1,-9} {2,-9} {3,-9} {4,-9} {5}" -f 'frame','t(s)','dt(ms)','base(ms)','excess','kind')
        $top = $rep.spikes | Sort-Object -Property excess_ms -Descending | Select-Object -First 25
        foreach ($s in $top) {
            $kind = $(if ($s.isolated) { 'ISOLATED' } else { 'cluster' })
            $L += ("  {0,-7} {1,-9:F2} {2,-9:F1} {3,-9:F2} {4,-9:F1} {5}" -f `
                    $s.index, ($s.t_ms/1000.0), $s.dt_ms, $s.baseline_ms, $s.excess_ms, $kind)
        }
    }
    $L += ('=' * 68)
    return ($L -join "`n")
}

function Get-Verdict($base, $cand) {
    $checks = @()
    $checks += [pscustomobject]@{ name = 'baseline exercised cold compiles (isolated spikes > 0)'
        passed = ($base.isolated_spike_count -gt 0); failtag = 'INCONCLUSIVE' }
    $checks += [pscustomobject]@{ name = ("candidate isolated compile spikes <= {0}" -f $MaxIsoSpikes)
        passed = ($cand.isolated_spike_count -le $MaxIsoSpikes); failtag = 'FAIL' }
    $checks += [pscustomobject]@{ name = ("candidate p99.9 <= baseline p99.9 x{0:F2} ({1:F1} <= {2:F1})" -f `
            (1 + $P999Tol), $cand.p999_ms, ($base.p999_ms * (1 + $P999Tol)))
        passed = ($cand.p999_ms -le $base.p999_ms * (1 + $P999Tol)); failtag = 'FAIL' }
    $checks += [pscustomobject]@{ name = ("candidate total stutter <= baseline ({0:F0} <= {1:F0} ms)" -f `
            $cand.total_excess_ms, $base.total_excess_ms)
        passed = ($cand.total_excess_ms -le $base.total_excess_ms); failtag = 'FAIL' }
    return $checks
}

function Format-Compare($base, $cand, $checks) {
    $L = @(); $L += ('#' * 68)
    $L += 'A/B  A=baseline(precompile OFF)  B=candidate(ON)'
    $L += ('#' * 68)
    $L += ("  {0,-20} {1,14} {2,14} {3,12}" -f 'metric','A (OFF)','B (ON)','delta')
    $L += ('  ' + ('-' * 62))
    $rows = @(
        @('frames','n_frames','F0'), @('duration (s)','duration_s','F1'),
        @('median ms','median_ms','F2'), @('p99 ms','p99_ms','F2'),
        @('p99.9 ms','p999_ms','F2'), @('max ms','max_ms','F2'),
        @('total spikes','spike_count','F0'), @('ISOLATED spikes','isolated_spike_count','F0'),
        @('total stutter ms','total_excess_ms','F0'), @('max single ms','max_excess_ms','F0'))
    foreach ($row in $rows) {
        $a = $base.($row[1]); $b = $cand.($row[1]); $d = $b - $a
        $fmt = '{0:' + $row[2] + '}'
        $L += ("  {0,-20} {1,14} {2,14} {3,12}" -f $row[0], ($fmt -f $a), ($fmt -f $b), ('{0:+0.0;-0.0}' -f $d))
    }
    $L += ('  ' + ('-' * 62))
    $ok = $true
    foreach ($c in $checks) {
        $tag = $(if ($c.passed) { 'PASS' } else { $c.failtag })
        if (-not $c.passed -and $c.failtag -eq 'FAIL') { $ok = $false }
        $L += ("  [{0,-12}] {1}" -f $tag, $c.name)
    }
    $L += ('#' * 68)
    $verdict = $(if ($ok) { 'PASS -- precompile ON shows zero isolated compile stutter' }
                else { 'FAIL -- residual compile stutter remains' })
    $L += "  VERDICT: $verdict"
    $L += ('#' * 68)
    return @{ text = ($L -join "`n"); ok = $ok }
}

# --------------------------------------------------------------------------
# Main.
# --------------------------------------------------------------------------
$reports = @()
foreach ($p in $Logs) {
    $log = Import-FrameLog $p
    $reports += (Invoke-Analyze $log)
}
foreach ($rep in $reports) { Write-Output (Format-Report $rep) }

$exit = 0
$cmp = $null
if ($reports.Count -eq 2) {
    $checks = Get-Verdict $reports[0] $reports[1]
    $res = Format-Compare $reports[0] $reports[1] $checks
    Write-Output "`n$($res.text)"
    $exit = $(if ($res.ok) { 0 } else { 1 })
    $cmp = [pscustomobject]@{ verdict = $(if ($res.ok) {'PASS'} else {'FAIL'}); checks = $checks }
}

if ($Json) {
    $payload = [pscustomobject]@{ reports = @($reports); comparison = $cmp }
    $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Json -Encoding UTF8
    Write-Output "`nwrote $Json"
}

exit $exit

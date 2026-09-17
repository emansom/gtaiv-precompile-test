#requires -Version 5.1
<#
.SYNOPSIS
  Collect GPU (model + driver version), CPU, RAM and OS-build info for a
  shareable test result. Writes JSON and prints a summary.
.EXAMPLE
  .\Get-HardwareInfo.ps1 -Json .\results\raw\hardware.json
#>
[CmdletBinding()]
param([string]$Json)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-DisplayVersion {
    try {
        $k = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
        $p = Get-ItemProperty -Path $k -ErrorAction Stop
        $dv = $p.DisplayVersion
        if (-not $dv) { $dv = $p.ReleaseId }
        return @{ DisplayVersion = $dv; UBR = $p.UBR; ProductName = $p.ProductName }
    } catch { return @{ DisplayVersion = $null; UBR = $null; ProductName = $null } }
}

# GPUs (there may be an iGPU + dGPU; capture all, flag the likely-active one).
$gpus = @()
try {
    foreach ($v in (Get-CimInstance Win32_VideoController -ErrorAction Stop)) {
        $gpus += [pscustomobject]@{
            Name           = $v.Name
            DriverVersion  = $v.DriverVersion
            DriverDate     = if ($v.DriverDate) { $v.DriverDate.ToString('yyyy-MM-dd') } else { $null }
            VideoProcessor = $v.VideoProcessor
            AdapterRAM_MB  = if ($v.AdapterRAM) { [math]::Round($v.AdapterRAM / 1MB) } else { $null }
            Status         = $v.Status
        }
    }
} catch { Write-Warning "GPU query failed: $_" }

# Vendor guess from the first discrete-looking GPU name.
$vendor = 'Unknown'
$primaryGpu = $null
foreach ($g in $gpus) {
    $n = ($g.Name + '').ToLowerInvariant()
    if ($n -match 'nvidia|geforce|rtx|gtx')       { $vendor = 'NVIDIA'; $primaryGpu = $g; break }
    elseif ($n -match 'amd|radeon|rx ')           { $vendor = 'AMD';    $primaryGpu = $g; break }
    elseif ($n -match 'intel|arc|iris|uhd|hd graphics') { $vendor = 'Intel'; $primaryGpu = $g }
}
if (-not $primaryGpu -and $gpus.Count -gt 0) { $primaryGpu = $gpus[0] }

$cpu = $null
try {
    $c = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
    $cpu = [pscustomobject]@{
        Name = $c.Name.Trim(); Cores = $c.NumberOfCores
        Threads = $c.NumberOfLogicalProcessors; MaxClockMHz = $c.MaxClockSpeed
    }
} catch { Write-Warning "CPU query failed: $_" }

$os = $null
try {
    $o = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $dv = Get-DisplayVersion
    $os = [pscustomobject]@{
        Caption = $o.Caption; Version = $o.Version; Build = $o.BuildNumber
        DisplayVersion = $dv.DisplayVersion; UBR = $dv.UBR
    }
} catch { Write-Warning "OS query failed: $_" }

$ramGB = $null
try {
    $ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
} catch {}

$info = [pscustomobject]@{
    collected_utc = (Get-Date).ToUniversalTime().ToString('o')
    vendor       = $vendor
    primary_gpu  = $primaryGpu
    all_gpus     = $gpus
    cpu          = $cpu
    ram_gb       = $ramGB
    os           = $os
}

Write-Host "GPU   : $($primaryGpu.Name)  driver $($primaryGpu.DriverVersion) [$vendor]"
Write-Host "CPU   : $($cpu.Name)  ($($cpu.Cores)C/$($cpu.Threads)T)"
Write-Host "OS    : $($os.Caption) $($os.DisplayVersion) build $($os.Build).$($os.UBR)"
Write-Host "RAM   : $ramGB GB"

if ($Json) {
    $dir = Split-Path -Parent $Json
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $info | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Json -Encoding UTF8
    Write-Host "wrote $Json"
}
# Also emit the object so a caller can consume it directly.
$info

#requires -Version 5.1
# Shared helpers for the gtaiv-precompile-test harness. Dot-source this:
#   . "$PSScriptRoot\Common.ps1"

Set-StrictMode -Version Latest
$InvCulture = [System.Globalization.CultureInfo]::InvariantCulture

# Repo root = parent of the run/ dir this file lives in.
$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:ResultsDir = Join-Path $RepoRoot 'results'
$script:RawDir = Join-Path $ResultsDir 'raw'
$script:ConfigPath = Join-Path $RepoRoot 'config\test.config.psd1'

function Write-Step  { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok    { param([string]$m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err2  { param([string]$m) Write-Host "  [ERR]  $m" -ForegroundColor Red }

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Import-TestConfig {
    param([string]$Path = $script:ConfigPath)
    if (-not (Test-Path -LiteralPath $Path)) {
        $example = Join-Path $RepoRoot 'config\test.config.example.psd1'
        if (Test-Path -LiteralPath $example) {
            Write-Warn2 "config\test.config.psd1 not found -- using defaults from test.config.example.psd1 (copy + edit it to customize)."
            $Path = $example
        } else {
            throw "config not found: $Path (copy config\test.config.example.psd1 to test.config.psd1)"
        }
    }
    # .psd1 is a safe data file; Import-PowerShellDataFile parses it without executing code.
    return Import-PowerShellDataFile -LiteralPath $Path
}

function Resolve-GamePath {
    param($Config)
    if ($Config.GamePath -and (Test-Path -LiteralPath $Config.GamePath)) {
        return (Resolve-Path -LiteralPath $Config.GamePath).Path
    }

    # Ask Steam and the Rockstar Games Launcher where the game is, rather than
    # guessing Program Files. Steam libraries live on whatever drive the user chose,
    # so the old hardcoded candidates missed most installs. See Find-GtaivInstall.ps1.
    try {
        $installs = & "$PSScriptRoot\Find-GtaivInstall.ps1" 6>$null
        if ($installs) {
            # Find-GtaivInstall already prefers Steam, then Rockstar, then uninstall
            # entries, and only returns directories that really contain GTAIV.exe.
            $first = @($installs)[0]
            if ($first -and $first.ExeDir) { return $first.ExeDir }
        }
    } catch {
        Write-Verbose "Find-GtaivInstall.ps1 failed: $($_.Exception.Message)"
    }

    # Last resort: the default install locations, for the case where the registry is
    # unreadable (no elevation, damaged install) but the game is where it usually is.
    $candidates = @(
        "$env:ProgramFiles(x86)\Steam\steamapps\common\Grand Theft Auto IV\GTAIV",
        "$env:ProgramFiles\Rockstar Games\Grand Theft Auto IV\GTAIV",
        "$env:ProgramFiles(x86)\Rockstar Games\Grand Theft Auto IV\GTAIV"
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $c 'GTAIV.exe')) { return $c }
    }
    return $null
}

function New-DirIfMissing { param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null }
}

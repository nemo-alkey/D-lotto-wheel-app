<#
.SYNOPSIS
    Runs the Covella prompt pack against the current repo.
.DESCRIPTION
    Three modes:
      -Runnable    execute prompts that have backing code
      -NeedsScript emit "not yet implemented" stubs (to-do list)
      -Advisory    write advisory prompts into reports/prompts/ as ready-to-paste .md
    With no flags, defaults to -Runnable.
#>
[CmdletBinding()]
param(
    [switch]$Runnable,
    [switch]$NeedsScript,
    [switch]$Advisory,
    [switch]$All,
    [string]$OutDir = "reports/prompts"
)

$ErrorActionPreference = "Continue"

# Resolve repo root from this script's location: scripts/prompts/ -> repo root
$ScriptDir = $PSScriptRoot
$RepoRoot  = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

if ($All) { $Runnable = $NeedsScript = $Advisory = $true }
if (-not ($Runnable -or $NeedsScript -or $Advisory)) { $Runnable = $true }

$catalogPath = Join-Path $ScriptDir "catalog.psd1"
if (-not (Test-Path $catalogPath)) {
    Write-Host "ABORT: catalog not found at $catalogPath" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
$catalog = Import-PowerShellDataFile $catalogPath

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$log = Join-Path $OutDir ("run_{0:yyyy-MM-dd_HHmmss}.log" -f (Get-Date))
"Prompt pack run: $(Get-Date -Format o)" | Out-File $log -Encoding utf8

function Invoke-Entry {
    param($entry)
    $hdr = "[$($entry.Id)] $($entry.Title)  ($($entry.Category))"
    Write-Host "`n=== $hdr ===" -ForegroundColor Cyan
    $hdr | Out-File $log -Append -Encoding utf8

    switch ($entry.Category) {
        "Runnable" {
            if (-not $Runnable) { return }
            $d = $entry.Dispatch
            if ($d.Type -eq "Script") {
                if (-not (Test-Path $d.Path)) {
                    Write-Host "  SKIP: $($d.Path) not found" -ForegroundColor Yellow
                    return
                }
                Write-Host "  dispatch: python $($d.Path)"
                python $d.Path 2>&1 | Tee-Object -FilePath $log -Append
            } elseif ($d.Type -eq "Shell") {
                Write-Host "  dispatch: $($d.Path)"
                Invoke-Expression $d.Path 2>&1 | Tee-Object -FilePath $log -Append
            }
        }
        "NeedsScript" {
            if (-not $NeedsScript) { return }
            $safe = $entry.Title -replace '[^\w]','_'
            $stub = Join-Path $OutDir ("todo_{0:d2}_{1}.txt" -f $entry.Id, $safe)
            @(
                "Not yet implemented: $($entry.Title)",
                "Dispatch target: $($entry.Dispatch.Module)",
                "",
                "Create that module, then re-run with -Runnable."
            ) | Out-File $stub -Encoding utf8
            Write-Host "  todo written: $stub" -ForegroundColor Yellow
        }
        "Advisory" {
            if (-not $Advisory) { return }
            $safe = $entry.Title -replace '[^\w]','_'
            $file = Join-Path $OutDir ("prompt_{0:d2}_{1}.md" -f $entry.Id, $safe)
            "# Prompt $($entry.Id): $($entry.Title)`n`n$($entry.Prompt)" |
                Out-File $file -Encoding utf8
            Write-Host "  prompt written: $file" -ForegroundColor Green
        }
    }
}

foreach ($entry in $catalog.Prompts) {
    Invoke-Entry $entry
}

Write-Host "`nDone. Log: $log" -ForegroundColor Cyan
Write-Host "Prompts in $OutDir"
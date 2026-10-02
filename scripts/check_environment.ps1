[CmdletBinding()]
param(
    [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$failures = [System.Collections.Generic.List[string]]::new()

function Test-CommandVersion([string]$Name, [string]$Arguments = "--version") {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        $failures.Add("Missing command: $Name")
        return
    }
    try {
        $version = (& $command.Source $Arguments 2>&1 | Select-Object -First 1)
        Write-Host ("{0}: {1}" -f $Name, $version)
    } catch {
        $failures.Add("Cannot execute ${Name}: $($_.Exception.Message)")
    }
}

Write-Host "Mneme development environment: $root"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $failures.Add("Project virtual environment is missing: $python")
} else {
    Write-Host ("Python: {0}" -f (& $python --version 2>&1))
    & $python -c "import sys; assert sys.version_info >= (3, 10), sys.version"
    if ($LASTEXITCODE -ne 0) { $failures.Add("Project Python must be 3.10 or newer") }
}

Test-CommandVersion "node"
Test-CommandVersion "npm"
Test-CommandVersion "java"
Test-CommandVersion "mvn"
if (-not $SkipDocker) {
    Test-CommandVersion "docker"
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        try { docker compose version | Select-Object -First 1 } catch { $failures.Add("Docker Compose is unavailable") }
    }
}

foreach ($path in @(".m2", ".npm-cache", ".pip-audit-cache")) {
    $fullPath = Join-Path $root $path
    New-Item -ItemType Directory -Force -Path $fullPath | Out-Null
    $probe = Join-Path $fullPath ".mneme-write-test"
    try {
        [IO.File]::WriteAllText($probe, "ok")
        Remove-Item -LiteralPath $probe -Force
        Write-Host "Writable cache: $fullPath"
    } catch { $failures.Add("Cache directory is not writable: $fullPath") }
}

$dockerConfig = Join-Path $env:USERPROFILE ".docker\config.json"
if (-not $SkipDocker -and (Test-Path $dockerConfig)) {
    try { Get-Content -Raw -LiteralPath $dockerConfig | ConvertFrom-Json | Out-Null; Write-Host "Docker config: readable" }
    catch { $failures.Add("Docker config exists but cannot be read as JSON: $dockerConfig") }
}

if ($failures.Count -gt 0) {
    Write-Error (($failures | ForEach-Object { "- $_" }) -join [Environment]::NewLine)
    exit 1
}
Write-Host "Environment checks passed. Use the project-local Python and package caches for tests."

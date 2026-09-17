param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [switch]$Force,
    [string]$Report = "./backups/last-restore-report.json"
)

if (!$Force) { throw "Restore overwrites current data. Re-run with -Force." }
python "$PSScriptRoot/backup_restore.py" restore $Archive --yes --report $Report
if ($LASTEXITCODE -ne 0) { throw "Mneme restore failed" }

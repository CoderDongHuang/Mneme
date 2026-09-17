param([string]$OutputDir = "./backups")

python "$PSScriptRoot/backup_restore.py" backup --output-dir $OutputDir
if ($LASTEXITCODE -ne 0) { throw "Mneme backup failed" }

param([string]$OutputDir = "./backups")
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
docker compose exec -T mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --events mneme' | Out-File "$OutputDir/mneme-$stamp.sql" -Encoding utf8
tar -czf "$OutputDir/files-$stamp.tar.gz" ./data/files ./data/chroma
if ($env:OBJECT_BACKUP_URI) {
    if (!(Get-Command aws -ErrorAction SilentlyContinue)) { throw "OBJECT_BACKUP_URI is set but AWS CLI is unavailable" }
    aws s3 sync $OutputDir "$($env:OBJECT_BACKUP_URI.TrimEnd('/'))/$stamp/" --only-show-errors
}
Write-Output "Backup created: $stamp"

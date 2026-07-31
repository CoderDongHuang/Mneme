param([Parameter(Mandatory=$true)][string]$SqlFile)
if (!(Test-Path -LiteralPath $SqlFile)) { throw "Backup file not found" }
docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" mneme' < $SqlFile
Write-Output "Database restore completed"

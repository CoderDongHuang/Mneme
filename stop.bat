@echo off
setlocal
cd /d "%~dp0"
docker compose stop mysql redis qdrant
echo Infrastructure stopped. Close the three application terminals to stop local services.
endlocal

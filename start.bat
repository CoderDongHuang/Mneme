@echo off
setlocal
cd /d "%~dp0"

if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do if not "%%A"=="" set "%%A=%%B"
) else (
  echo [Mneme] Missing .env. Copy .env.example to .env first.
  pause
  exit /b 1
)

if not defined JWT_SECRET (
  echo [Mneme] JWT_SECRET is required in .env.
  pause
  exit /b 1
)
if not defined INTERNAL_SERVICE_TOKEN (
  echo [Mneme] INTERNAL_SERVICE_TOKEN is required in .env.
  pause
  exit /b 1
)
if not defined MYSQL_ROOT_PASSWORD if not defined SPRING_DATASOURCE_PASSWORD (
  echo [Mneme] MYSQL_ROOT_PASSWORD or SPRING_DATASOURCE_PASSWORD is required in .env.
  pause
  exit /b 1
)

echo [Mneme] Starting MySQL, Redis and Chroma...
docker compose up -d mysql redis chroma
if errorlevel 1 (
  echo [Mneme] Failed to start infrastructure. Check Docker Desktop.
  pause
  exit /b 1
)

start "Mneme Python Agent" cmd /k "cd /d %~dp0python-agent && python main.py"
start "Mneme Java Gateway" cmd /k "cd /d %~dp0java-gateway && mvn clean spring-boot:run"
start "Mneme React Frontend" cmd /k "cd /d %~dp0frontend && set VITE_GATEWAY_TARGET=http://127.0.0.1:8080&& npm run dev"

echo [Mneme] Three application terminals opened.
echo Frontend: http://localhost:5173
echo Java:     http://localhost:8080/api/v1/health
echo Python:   http://localhost:8001/docs
endlocal

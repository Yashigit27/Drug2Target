@echo off
cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo Docker is not in PATH. Start Docker Desktop, then open a new terminal.
  pause
  exit /b 1
)

if not exist ".env" (
  echo Creating .env from .env.example ...
  copy /Y ".env.example" ".env" >nul
)

echo Building and starting D2T on http://127.0.0.1:8080
echo Keep Docker Desktop running. Press Ctrl+C to stop following logs.
docker compose up --build

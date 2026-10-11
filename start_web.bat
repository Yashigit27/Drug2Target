@echo off
cd /d "%~dp0"
echo Starting D2T web UI at http://127.0.0.1:8080
echo Keep this window open. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m web.server

@echo off
echo ========================================================
echo   ARVIS PILOT LAUNCHER (COMMERCIAL VERTICAL)
echo ========================================================
echo Setting Environment Variables...
set ARVIS_VERTICAL=COMMERCIAL
set LOG_LEVEL=INFO

echo.
echo 🌍 Mode: %ARVIS_VERTICAL%
echo 🚀 Starting API Server...
echo.

uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
pause

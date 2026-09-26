@echo off
echo ========================================================
echo   ARVIS PILOT LAUNCHER (COMMERCIAL - LIVE BUILDING)
echo ========================================================
REM Canonical production entry point: the commercial OpsCopilot pipeline
REM (real BMS ingestion + production hardening). NOT the generic api.main
REM app, which is simulator-wired and mounts demo routes.

set ARVIS_VERTICAL=COMMERCIAL
set ARVIS_ENV=production
if "%ARVIS_MODE%"=="" set ARVIS_MODE=bacnet
set LOG_LEVEL=INFO

echo.
echo Mode: %ARVIS_MODE%   (ARVIS_ENV=production - simulator/demo disabled)
echo Required before start: ARVIS_AUTH_SECRET, ARVIS_ADMIN_PASSWORD, and the
echo BMS connection config (BACnet/Modbus device + point mapping).
echo.
echo Starting commercial live pipeline...
echo.

REM No --reload in production.
python -m agent_commercial.main --port 8000
pause

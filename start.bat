@echo off
REM StrutCalc Knowledge Assistant bootstrap, for machines without `just`.
REM Usage:
REM   start.bat install  - uv sync + npm install (frontend)
REM   start.bat build    - build the frontend into app/dist
REM   start.bat dev       - backend on :8077 with --reload
REM   start.bat prod      - backend on :8077 (no reload)

set COMMAND=%1
if "%COMMAND%"=="" set COMMAND=dev

if "%COMMAND%"=="install" (
    pushd %~dp0
    uv sync --all-groups
    npm --prefix web install
    popd
    goto :eof
)

if "%COMMAND%"=="build" (
    npm --prefix %~dp0web run build
    goto :eof
)

if "%COMMAND%"=="dev" (
    pushd %~dp0
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8077 --reload
    popd
    goto :eof
)

if "%COMMAND%"=="prod" (
    pushd %~dp0
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8077
    popd
    goto :eof
)

echo Unknown command: %COMMAND%
echo Valid: install ^| build ^| dev ^| prod
exit /b 1

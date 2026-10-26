# strut-calc-repo-knowledge — task runner.
# `just` with no argument lists recipes. Everything runs inside the uv env.

# Windows PowerShell as the recipe shell. Without this, just looks for `sh` and
# fails on a machine with no POSIX shell on PATH.
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Default: show the recipe list.
default:
    @just --list

# Create the virtual environment and install all dependency groups.
install:
    uv sync --all-groups

# Lint, type-check and security-scan. The gate before committing.
check: ruff mypy bandit

ruff:
    uv run ruff check src app tests

fmt-check:
    uv run ruff format --check src app tests

fmt:
    uv run ruff format src app tests

mypy:
    uv run mypy

bandit:
    uv run bandit -c pyproject.toml -r src app

test:
    uv run pytest

# Build / incrementally refresh the vector index over the configured repos.
build *ARGS:
    uv run python -m src.build {{ARGS}}

# Rebuild the whole vector index from scratch.
rebuild:
    uv run python -m src.build --force

# Run the MCP server standalone (manual check).
serve:
    uv run python -m src.server

# strands-compose agent REPL against the local index.
agent:
    uv run python agent/main.py

# ── Web app ───────────────────────────────────────────────────────────

# Backend in the foreground (serves the API and, if built, the web UI).
run PORT="8077":
    uv run uvicorn app.main:app --host 0.0.0.0 --port {{PORT}}

# Backend with autoreload, for development.
dev-api PORT="8077":
    uv run uvicorn app.main:app --host 0.0.0.0 --port {{PORT}} --reload

# Frontend dev server (Vite, proxies /api to the backend).
dev-ui:
    npm --prefix web run dev

# Install the frontend dependencies.
web-install:
    npm --prefix web install

# Build the frontend into app/dist so uvicorn can serve it.
web-build:
    npm --prefix web run build

# ── Windows service (NSSM) ────────────────────────────────────────────

# Install + auto-start the service (run as Administrator).
service-install:
    powershell -ExecutionPolicy Bypass -File scripts/install_service.ps1 -AutoStart

# Uninstall the service (run as Administrator).
service-uninstall:
    powershell -ExecutionPolicy Bypass -File scripts/install_service.ps1 -Uninstall

# Start / stop / restart / status.
service-start:
    Start-Service -Name 'StrutCalcKnowledge'; Get-Service -Name 'StrutCalcKnowledge' | Format-Table -AutoSize

service-stop:
    Stop-Service -Name 'StrutCalcKnowledge' -Force; Get-Service -Name 'StrutCalcKnowledge' | Format-Table -AutoSize

service-restart:
    Restart-Service -Name 'StrutCalcKnowledge' -Force; Get-Service -Name 'StrutCalcKnowledge' | Format-Table -AutoSize

service-status:
    Get-Service -Name 'StrutCalcKnowledge' | Format-Table -AutoSize

# Tail the service logs.
service-logs:
    Get-Content logs/service.log -Tail 50 -Wait

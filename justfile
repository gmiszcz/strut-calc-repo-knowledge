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
    uv run ruff check src tests

fmt-check:
    uv run ruff format --check src tests

fmt:
    uv run ruff format src tests

mypy:
    uv run mypy

bandit:
    uv run bandit -c pyproject.toml -r src

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

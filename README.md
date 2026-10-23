# strut-calc-repo-knowledge

Master knowledge engine for the CAE repositories. It runs **local semantic code
search**: it chunks source, embeds each chunk with Bedrock Titan v2, stores the
vectors in a local sqlite-vec file, and serves them two ways — an MCP server for
Kiro to query directly, and a strands-compose agent for use without the repo.

This repo holds the whole engine. The per-app side (the hand-written context map
and the deterministic route/symbol index — "goal 1") lives inside each target
repo under `.repomap/`; this engine only reads the source.

## How it works

```
target repos (StrutCalc, …) ─▶ chunker ─▶ Bedrock Titan v2 ─▶ sqlite-vec (local)
                                                                     │
                                                    ┌────────────────┴───────────────┐
                                              MCP server                   strands-compose agent
                                            (search_code)                    (Bedrock Haiku)
                                                    │                                 │
                                             Kiro (you)                      anyone, no repo needed
```

- **chunk** (`src/chunker.py`): Python on AST boundaries, JS/TS on export
  boundaries, Markdown on headings. Big chunks split into overlapping windows,
  tiny ones merged. Tests, vendored bundles, `static/`, migrations and generated
  dirs are skipped.
- **embed** (`src/embed.py`): Bedrock Titan Text Embeddings v2 (1024-d) via the
  shared SSO profile. Only changed chunks are re-embedded.
- **store** (`src/store.py`): sqlite-vec, one file. A `repo` column tags every
  chunk, so more target repos — and later the goal-3 prose docs — share one DB.
- **build** (`src/build.py`): scan → chunk → embed changed → drop stale, with an
  approximate cost readout.
- **serve** (`src/server.py`): the `search_code` MCP tool.
- **agent** (`agent/`): single Haiku agent whose only tool is `search_code`.

Only chunk text leaves the machine, and only to the corporate Bedrock endpoint,
to compute a vector.

## Setup

```powershell
Copy-Item .env.example .env        # adjust region/model if needed
aws sso login                      # profile `default`, SSO session tenneco-aws
just install                       # uv sync --all-groups
just check                         # ruff + mypy + bandit
just build                         # build the vector index (incremental)
```

## Recipes

| Recipe | What it does |
| --- | --- |
| `just install` | create the venv, install all groups |
| `just check` | ruff + mypy + bandit (the commit gate) |
| `just build` | build / refresh the vector index |
| `just rebuild` | rebuild from scratch |
| `just serve` | run the MCP server standalone |
| `just agent` | agent REPL against the local index |
| `just test` | unit tests |

## Which repos get indexed

`REPOMAP_TARGETS` in `.env` — a JSON array of `{label, root}`. A relative root
resolves against `C:/WebServices`. Default: StrutCalc only. Add the sibling
repos here as they are onboarded.

## Connecting the MCP server to Kiro

Add to your Kiro `mcp.json` (workspace or user):

```json
{
  "mcpServers": {
    "strutcalc-knowledge": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.server"],
      "cwd": "d:/Coding/strut-calc-repo-knowledge"
    }
  }
}
```

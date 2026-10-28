"""MCP server exposing semantic code search over the local vector index.

One tool, ``search_code``: it embeds the query with the same Titan model the
index was built with, runs a KNN search over sqlite-vec, and returns the closest
chunks with their location (repo, path, line range, symbol).

Run as ``python -m src.server`` for a plain FastMCP server over stdio, which is
how Kiro launches and talks to it. The strands-compose agent connects to this
same command as an MCP *client* (stdio), so there is one server implementation.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.config import Settings, get_settings
from src.embed import BedrockEmbedder
from src.store import SearchHit, VectorStore

logger = logging.getLogger(__name__)

# Lines of context added on each side of a requested range in read_file_range,
# so a chunk's range opens into its surrounding function without a second call.
_READ_MARGIN = 10

# Hard cap on how many lines one read_file_range call may return, so a bad
# range can never pull a whole large file into the model context.
_MAX_READ_LINES = 400


def _format_hit(hit: SearchHit) -> dict[str, object]:
    """Shape one search hit into the tool's return record.

    Args:
        hit: A store search hit.

    Returns:
        A JSON-serialisable record with location, score and text.
    """
    return {
        "repo": hit.repo,
        "path": hit.path,
        "symbol": hit.symbol,
        "lines": f"{hit.start_line}-{hit.end_line}",
        "lang": hit.lang,
        "kind": hit.kind,
        "score": round(1.0 / (1.0 + hit.distance), 4),
        "text": hit.text,
    }


def _accessible_roots(settings: Settings) -> dict[str, Path]:
    """Return the repo labels whose root actually exists on this machine.

    The engine is configured with a fixed set of target repos, but a given
    machine may not have all of them checked out. Only repos whose root
    directory exists are considered accessible for reading.

    Args:
        settings: Engine settings.

    Returns:
        Mapping of repo label to its resolved absolute root, for roots that
        exist as directories.
    """
    accessible: dict[str, Path] = {}
    for target in settings.targets:
        root = target.root.resolve()
        if root.is_dir():
            accessible[target.label] = root
    return accessible


def _resolve_in_repo(root: Path, path: str) -> Path | None:
    """Resolve a repo-relative path and confirm it stays inside the repo.

    Rejects absolute paths and any path that escapes the repo root via ``..``,
    so the tool can never read outside an accessible repo.

    Args:
        root: Resolved absolute repo root.
        path: Repo-relative path as given by the caller.

    Returns:
        The resolved absolute file path when it is a readable file inside the
        repo, or ``None`` when the path is invalid, escapes the root, or is not
        an existing file.
    """
    candidate = Path(path)
    if candidate.is_absolute():
        return None
    resolved = (root / candidate).resolve()
    if root not in resolved.parents and resolved != root:
        return None
    if not resolved.is_file():
        return None
    return resolved


def _register_read_tools(mcp: FastMCP, settings: Settings) -> None:
    """Register ``list_repos`` and ``read_file_range`` on a FastMCP instance.

    These let an agent check which repos it can actually read and then pull the
    full surrounding source for a search hit, instead of reasoning from the
    chunk snippet alone. Both refuse any repo that is not an accessible target.

    Args:
        mcp: The FastMCP instance to register the tools on.
        settings: Engine settings.
    """

    @mcp.tool()
    def list_repos() -> list[dict[str, str]]:
        """List the repos this server can read on the current machine.

        Call this before ``read_file_range`` to learn which repo labels are
        accessible. A repo is accessible only when its root directory exists
        here, so this reflects real read access, not just configuration.

        Returns:
            One record per accessible repo with ``repo`` (label) and ``root``
            (absolute path). Empty when no target repo is checked out.
        """
        return [
            {"repo": label, "root": str(root)}
            for label, root in _accessible_roots(settings).items()
        ]

    @mcp.tool()
    def read_file_range(
        repo: str, path: str, start_line: int = 1, end_line: int = 0
    ) -> dict[str, object]:
        """Read a line range from a file in an accessible repo.

        Use this to read the full function or section around a search hit: pass
        the hit's ``repo`` and ``path`` and the line range. The server widens
        the range slightly for context and caps the total lines returned.

        Access is checked first. When ``repo`` is not an accessible target (not
        configured, or its root is not checked out on this machine), nothing is
        read and ``ok`` is ``false`` with a reason. Only read after confirming
        access, either here or via ``list_repos``.

        Args:
            repo: Repo label, as returned by ``search_code`` or ``list_repos``.
            path: Repo-relative file path, as returned by ``search_code``.
            start_line: 1-based first line to read (clamped to the file).
            end_line: 1-based last line to read, or 0 for the end of the file.

        Returns:
            A record with ``ok``. On success: ``repo``, ``path``,
            ``start_line``, ``end_line`` (the widened, clamped range actually
            returned) and ``text``. On failure: ``ok`` false and ``reason``.
        """
        roots = _accessible_roots(settings)
        root = roots.get(repo)
        if root is None:
            known = ", ".join(sorted(roots)) or "none"
            return {
                "ok": False,
                "reason": (
                    f"no read access to repo '{repo}'. accessible repos: {known}"
                ),
            }
        resolved = _resolve_in_repo(root, path)
        if resolved is None:
            return {
                "ok": False,
                "reason": (
                    f"path '{path}' is not a readable file inside repo '{repo}'"
                ),
            }

        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        requested_end = end_line if end_line > 0 else total
        begin = max(1, start_line - _READ_MARGIN)
        finish = min(total, requested_end + _READ_MARGIN)
        if finish < begin:
            finish = begin
        if finish - begin + 1 > _MAX_READ_LINES:
            finish = begin + _MAX_READ_LINES - 1
        snippet = "\n".join(lines[begin - 1 : finish])
        return {
            "ok": True,
            "repo": repo,
            "path": path,
            "start_line": begin,
            "end_line": finish,
            "text": snippet,
        }


def _register_search_tool(mcp: FastMCP, settings: Settings) -> None:
    """Register ``search_code`` on a FastMCP instance.

    The embedder and store are created once and closed over by the tool, so each
    call reuses the Bedrock client and the open database connection. Shared by
    the standalone server and the strands-compose server so both expose exactly
    the same tool.

    Args:
        mcp: The FastMCP instance to register the tool on.
        settings: Engine settings.
    """
    embedder = BedrockEmbedder(
        profile=settings.aws_profile,
        region=settings.aws_region,
        model_id=settings.embed_model_id,
        embed_dim=settings.embed_dim,
    )
    store = VectorStore(settings.resolved_db_path, settings.embed_dim)

    @mcp.tool()
    def search_code(query: str, k: int = 0, repo: str = "") -> list[dict[str, object]]:
        """Search the indexed code and docs by meaning.

        Use this for "how does X work", "where is the logic for Y", "why do we
        use this option" — questions whose wording does not match the identifier
        in the code, where grep fails. For a known symbol name, grep is cheaper.

        Args:
            query: A natural-language description of what to find.
            k: Number of results (0 uses the configured default).
            repo: Restrict to one repo label, or empty for all.

        Returns:
            Closest chunks, each with repo, path, symbol, line range and text.
        """
        top_k = k if k > 0 else settings.search_k
        repo_filter = repo or None
        vector = embedder.embed(query)
        hits = store.search(vector, top_k, repo=repo_filter)
        return [_format_hit(hit) for hit in hits]


def build_mcp(settings: Settings) -> FastMCP:
    """Build the FastMCP app with ``search_code`` wired in.

    Args:
        settings: Engine settings.

    Returns:
        A configured FastMCP instance ready to run.
    """
    mcp = FastMCP("strutcalc-knowledge", host=settings.mcp_host, port=settings.mcp_port)
    _register_search_tool(mcp, settings)
    _register_read_tools(mcp, settings)
    return mcp


def main() -> None:
    """Run the standalone MCP server over stdio.

    Stdio is how Kiro launches an MCP server: it spawns this process and speaks
    MCP over stdin/stdout. Logging goes to stderr so it never corrupts the stdio
    protocol stream on stdout.
    """
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    settings = get_settings()
    mcp = build_mcp(settings)
    logger.info(
        "db=<%s> | starting search MCP server over stdio", settings.resolved_db_path
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

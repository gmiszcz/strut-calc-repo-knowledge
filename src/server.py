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

from mcp.server.fastmcp import FastMCP

from src.config import Settings, get_settings
from src.embed import BedrockEmbedder
from src.store import SearchHit, VectorStore

logger = logging.getLogger(__name__)


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

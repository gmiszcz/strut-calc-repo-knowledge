"""Build (or incrementally refresh) the vector index over the target repos.

For each configured repo it chunks every source file, then embeds only the
chunks whose text changed since the last run and drops chunks whose source
disappeared. The store already holds a content hash per chunk, so a no-op run
embeds nothing. First run embeds everything.

Run as a module: ``python -m src.build`` (incremental) or ``--force`` (rebuild).
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.chunker import Chunk, chunk_file, iter_source_files
from src.config import Settings, get_settings
from src.embed import BedrockEmbedder, EmbeddingError
from src.store import VectorStore

logger = logging.getLogger(__name__)

# Rough token estimate per character, to report an approximate embedding cost.
CHARS_PER_TOKEN = 4.0
# Titan Text Embeddings v2 on-demand price per 1000 input tokens (USD). Verify
# against the AWS console for the active region and contract.
USD_PER_1K_TOKENS = 0.00002


def _collect_chunks(settings: Settings) -> dict[str, list[Chunk]]:
    """Chunk every source file of every configured repo.

    Args:
        settings: Engine settings holding the repo targets.

    Returns:
        Mapping of repo label to its chunks.
    """
    by_repo: dict[str, list[Chunk]] = {}
    for target in settings.targets:
        if not target.root.exists():
            logger.warning("repo=<%s>, root=<%s> | missing, skipping", target.label, target.root)
            by_repo[target.label] = []
            continue
        chunks: list[Chunk] = []
        for path in iter_source_files(target.root):
            chunks.extend(chunk_file(target.label, target.root, path))
        by_repo[target.label] = chunks
        logger.info("repo=<%s> | %s chunks from source", target.label, len(chunks))
    return by_repo


def _sync_repo(
    repo: str,
    chunks: list[Chunk],
    store: VectorStore,
    embedder: BedrockEmbedder,
    force: bool,
) -> tuple[int, int, int]:
    """Bring the store in line with the current chunks for one repo.

    Args:
        repo: Repository label.
        chunks: The repo's current chunks.
        store: The vector store.
        embedder: The Bedrock embedder.
        force: Re-embed every chunk regardless of its stored hash.

    Returns:
        ``(embedded, skipped, deleted)`` counts.
    """
    existing = {} if force else store.existing_hashes(repo)
    current_ids = {chunk.chunk_id for chunk in chunks}

    stale = store.all_chunk_ids(repo) - current_ids
    store.delete_chunks(stale)

    embedded = 0
    skipped = 0
    for chunk in chunks:
        if existing.get(chunk.chunk_id) == chunk.content_hash:
            skipped += 1
            continue
        try:
            vector = embedder.embed(chunk.text)
        except EmbeddingError:
            logger.exception(
                "repo=<%s>, path=<%s>, symbol=<%s> | embedding failed",
                repo,
                chunk.path,
                chunk.symbol,
            )
            raise
        store.upsert(chunk, vector)
        embedded += 1
        if embedded % 50 == 0:
            store.commit()
            logger.info("repo=<%s> | embedded %s so far", repo, embedded)

    store.commit()
    return embedded, skipped, len(stale)


def run(force: bool) -> int:
    """Build or refresh the index for every configured repo.

    Args:
        force: Rebuild all vectors regardless of stored hashes.

    Returns:
        Process exit code (0 on success).
    """
    settings = get_settings()
    embedder = BedrockEmbedder(
        profile=settings.aws_profile,
        region=settings.aws_region,
        model_id=settings.embed_model_id,
        embed_dim=settings.embed_dim,
    )

    by_repo = _collect_chunks(settings)

    total_embedded = 0
    total_chars = 0
    with VectorStore(settings.resolved_db_path, settings.embed_dim) as store:
        for repo, chunks in by_repo.items():
            embedded, skipped, deleted = _sync_repo(repo, chunks, store, embedder, force)
            total_embedded += embedded
            total_chars += sum(len(c.text) for c in chunks if c.content_hash)
            logger.info(
                "repo=<%s> | embedded=%s skipped=%s deleted=%s total_stored=%s",
                repo,
                embedded,
                skipped,
                deleted,
                store.count(repo),
            )

    approx_tokens = total_chars / CHARS_PER_TOKEN
    approx_cost = approx_tokens / 1000 * USD_PER_1K_TOKENS
    print(
        f"Done. Embedded {total_embedded} chunks "
        f"(~{approx_tokens:,.0f} tokens, ~${approx_cost:.4f} this run)."
    )
    return 0


def main() -> int:
    """CLI entry point.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
    parser = argparse.ArgumentParser(description="Build the knowledge vector index.")
    parser.add_argument("--force", action="store_true", help="re-embed everything")
    args = parser.parse_args()
    return run(force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())

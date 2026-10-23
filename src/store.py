"""Vector store over sqlite-vec.

Two tables kept in step: ``chunks`` holds the metadata and text, ``vec_chunks``
(a vec0 virtual table) holds the embedding. Both are keyed by the same integer
rowid, so a vector search joins straight back to its chunk. A separate
``chunks.content_hash`` column drives incremental rebuilds — a chunk whose text
is unchanged keeps its vector and is never re-embedded.
"""

from __future__ import annotations

import logging
import sqlite3
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from src.chunker import Chunk

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchHit:
    """One result row from a vector search.

    Attributes:
        repo: Repository label.
        path: Repo-relative path of the source file.
        lang: ``py``, ``js`` or ``md``.
        kind: ``code`` or ``doc``.
        symbol: Symbol or section name.
        start_line: 1-based first line.
        end_line: 1-based last line.
        text: The chunk text.
        distance: Vector distance (smaller is closer).
    """

    repo: str
    path: str
    lang: str
    kind: str
    symbol: str
    start_line: int
    end_line: int
    text: str
    distance: float


def _pack(vector: Sequence[float]) -> bytes:
    """Pack a float vector into the little-endian blob sqlite-vec expects.

    Args:
        vector: Embedding values.

    Returns:
        Raw bytes for the vec0 column.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


class VectorStore:
    """A sqlite-vec backed store of code/doc chunks and their embeddings."""

    def __init__(self, db_path: Path, embed_dim: int) -> None:
        """Open (and if needed create) the store.

        Args:
            db_path: Path to the sqlite database file.
            embed_dim: Embedding dimensionality for the vec0 table.
        """
        self._embed_dim = embed_dim
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._create_schema()

    def _create_schema(self) -> None:
        """Create the chunk and vector tables when absent."""
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                rowid        INTEGER PRIMARY KEY,
                chunk_id     TEXT UNIQUE NOT NULL,
                repo         TEXT NOT NULL,
                path         TEXT NOT NULL,
                lang         TEXT NOT NULL,
                kind         TEXT NOT NULL,
                symbol       TEXT NOT NULL,
                start_line   INTEGER NOT NULL,
                end_line     INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                text         TEXT NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_repo ON chunks(repo)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_chunk_id ON chunks(chunk_id)"
        )
        self._conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                embedding float[{self._embed_dim}]
            )
            """
        )
        self._conn.commit()

    def existing_hashes(self, repo: str) -> dict[str, str]:
        """Return the stored ``chunk_id -> content_hash`` map for one repo.

        Used by the build step to decide which chunks are unchanged and can keep
        their existing vector.

        Args:
            repo: Repository label.

        Returns:
            Mapping of chunk id to stored content hash.
        """
        rows = self._conn.execute(
            "SELECT chunk_id, content_hash FROM chunks WHERE repo = ?", (repo,)
        ).fetchall()
        return {chunk_id: content_hash for chunk_id, content_hash in rows}

    def all_chunk_ids(self, repo: str) -> set[str]:
        """Return every stored chunk id for one repo.

        Args:
            repo: Repository label.

        Returns:
            The set of chunk ids currently stored for the repo.
        """
        rows = self._conn.execute(
            "SELECT chunk_id FROM chunks WHERE repo = ?", (repo,)
        ).fetchall()
        return {row[0] for row in rows}

    def upsert(self, chunk: Chunk, embedding: Sequence[float]) -> None:
        """Insert or replace one chunk and its embedding.

        The two tables are kept in step through a shared rowid: the chunk row is
        written first, then the vector row is replaced at the same rowid.

        Args:
            chunk: The chunk metadata and text.
            embedding: The chunk's embedding vector.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO chunks
                (chunk_id, repo, path, lang, kind, symbol, start_line, end_line,
                 content_hash, text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                repo=excluded.repo, path=excluded.path, lang=excluded.lang,
                kind=excluded.kind, symbol=excluded.symbol,
                start_line=excluded.start_line, end_line=excluded.end_line,
                content_hash=excluded.content_hash, text=excluded.text
            """,
            (
                chunk.chunk_id,
                chunk.repo,
                chunk.path,
                chunk.lang,
                chunk.kind,
                chunk.symbol,
                chunk.start_line,
                chunk.end_line,
                chunk.content_hash,
                chunk.text,
            ),
        )
        rowid = cursor.lastrowid
        if rowid is None:
            row = self._conn.execute(
                "SELECT rowid FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)
            ).fetchone()
            rowid = int(row[0])
        self._conn.execute(
            "INSERT OR REPLACE INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
            (rowid, _pack(embedding)),
        )

    def delete_chunks(self, chunk_ids: set[str]) -> None:
        """Remove chunks (and their vectors) that no longer exist in source.

        Args:
            chunk_ids: Ids to delete.
        """
        for chunk_id in chunk_ids:
            row = self._conn.execute(
                "SELECT rowid FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
            if row is None:
                continue
            rowid = int(row[0])
            self._conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (rowid,))
            self._conn.execute("DELETE FROM chunks WHERE rowid = ?", (rowid,))

    def search(
        self, embedding: Sequence[float], k: int, repo: str | None = None
    ) -> list[SearchHit]:
        """Return the ``k`` chunks closest to a query embedding.

        Args:
            embedding: The query's embedding vector.
            k: Number of results to return.
            repo: Optional repo label to restrict the search to.

        Returns:
            Hits ordered from closest to farthest.
        """
        # vec0 KNN runs first, then the join filters by repo. Over-fetch when a
        # repo filter is set so the post-filter still has k candidates.
        fetch = k if repo is None else k * 5
        rows = self._conn.execute(
            """
            SELECT c.repo, c.path, c.lang, c.kind, c.symbol, c.start_line,
                   c.end_line, c.text, v.distance
            FROM vec_chunks v
            JOIN chunks c ON c.rowid = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (_pack(embedding), fetch),
        ).fetchall()
        hits = [
            SearchHit(
                repo=row[0],
                path=row[1],
                lang=row[2],
                kind=row[3],
                symbol=row[4],
                start_line=row[5],
                end_line=row[6],
                text=row[7],
                distance=row[8],
            )
            for row in rows
        ]
        if repo is not None:
            hits = [hit for hit in hits if hit.repo == repo]
        return hits[:k]

    def count(self, repo: str | None = None) -> int:
        """Return the number of stored chunks.

        Args:
            repo: Optional repo label to count within.

        Returns:
            Stored chunk count.
        """
        if repo is None:
            row = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE repo = ?", (repo,)
            ).fetchone()
        return int(row[0])

    def commit(self) -> None:
        """Flush pending writes to disk."""
        self._conn.commit()

    def close(self) -> None:
        """Commit and close the database connection."""
        self._conn.commit()
        self._conn.close()

    def __enter__(self) -> VectorStore:
        """Enter a context manager.

        Returns:
            This store.
        """
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the store on context exit."""
        self.close()

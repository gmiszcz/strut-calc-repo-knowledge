"""Tests for the sqlite-vec vector store."""

from __future__ import annotations

from pathlib import Path

from src.chunker import Chunk
from src.store import VectorStore

DIM = 8


def _chunk(symbol: str, start: int, text: str) -> Chunk:
    return Chunk(
        repo="demo",
        path="mod.py",
        lang="py",
        kind="code",
        symbol=symbol,
        start_line=start,
        end_line=start + 2,
        text=text,
    )


def _unit(index: int) -> list[float]:
    """A simple one-hot-ish vector so nearest-neighbour is predictable."""
    vector = [0.0] * DIM
    vector[index % DIM] = 1.0
    return vector


def test_upsert_and_count(tmp_path: Path) -> None:
    with VectorStore(tmp_path / "t.db", DIM) as store:
        store.upsert(_chunk("a", 1, "alpha"), _unit(0))
        store.upsert(_chunk("b", 4, "beta"), _unit(1))
        store.commit()
        assert store.count("demo") == 2


def test_search_returns_closest(tmp_path: Path) -> None:
    with VectorStore(tmp_path / "t.db", DIM) as store:
        store.upsert(_chunk("a", 1, "alpha"), _unit(0))
        store.upsert(_chunk("b", 4, "beta"), _unit(1))
        store.commit()
        hits = store.search(_unit(0), k=1)
        assert len(hits) == 1
        assert hits[0].symbol == "a"


def test_unchanged_hash_lets_build_skip(tmp_path: Path) -> None:
    chunk = _chunk("a", 1, "alpha")
    with VectorStore(tmp_path / "t.db", DIM) as store:
        store.upsert(chunk, _unit(0))
        store.commit()
        existing = store.existing_hashes("demo")
        assert existing[chunk.chunk_id] == chunk.content_hash


def test_delete_removes_chunk_and_vector(tmp_path: Path) -> None:
    chunk = _chunk("a", 1, "alpha")
    with VectorStore(tmp_path / "t.db", DIM) as store:
        store.upsert(chunk, _unit(0))
        store.commit()
        store.delete_chunks({chunk.chunk_id})
        store.commit()
        assert store.count("demo") == 0
        assert store.search(_unit(0), k=1) == []

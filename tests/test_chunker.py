"""Tests for the source chunker."""

from __future__ import annotations

from pathlib import Path

from src.chunker import (
    chunk_js,
    chunk_markdown,
    chunk_python,
    is_scannable,
)


def test_python_splits_on_top_level_symbols() -> None:
    source = (
        "import os\n"
        "\n"
        "\n"
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "\n"
        "class Beta:\n"
        "    def method(self):\n"
        "        return 2\n"
    )
    chunks = chunk_python("demo", "mod.py", source)
    symbols = {c.symbol for c in chunks}
    # Leading import block plus the two symbols.
    assert "alpha" in symbols
    assert "Beta" in symbols
    assert all(c.lang == "py" and c.kind == "code" for c in chunks)


def test_python_syntax_error_yields_one_chunk() -> None:
    chunks = chunk_python("demo", "bad.py", "def oops(:\n")
    assert len(chunks) == 1
    assert chunks[0].start_line == 1


def test_js_splits_on_exports() -> None:
    source = (
        "import x from 'y';\n"
        "\n"
        "export function foo() {\n"
        "  return 1;\n"
        "}\n"
        "\n"
        "export const bar = () => {\n"
        "  return 2;\n"
        "};\n"
    )
    chunks = chunk_js("demo", "mod.js", source)
    symbols = {c.symbol for c in chunks}
    assert "foo" in symbols
    assert "bar" in symbols


def test_markdown_splits_on_headings() -> None:
    source = "# Title\n\nintro\n\n## Section A\n\nbody a\n\n## Section B\n\nbody b\n"
    chunks = chunk_markdown("demo", "doc.md", source)
    symbols = {c.symbol for c in chunks}
    assert "Section A" in symbols
    assert "Section B" in symbols
    assert all(c.kind == "doc" for c in chunks)


def test_chunk_ids_are_unique_within_file() -> None:
    source = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    chunks = chunk_python("demo", "mod.py", source)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_is_scannable_filters_tests_and_vendor() -> None:
    assert is_scannable(Path("src/app/models.py"))
    assert not is_scannable(Path("src/app/test_models.py"))
    assert not is_scannable(Path("ui/src/vendor-react.js"))
    assert not is_scannable(Path("node_modules/pkg/index.js"))
    assert not is_scannable(Path("ui/src/thing.test.jsx"))

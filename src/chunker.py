"""Cut source files into logical chunks for embedding.

A chunk is a unit of meaning, not a fixed window: a Python function/method/class
(via ``ast``), a JS/TS export or top-level function (via heuristics), or a
Markdown section (by heading). Oversized chunks are split into overlapping
windows so one embedding never has to represent 400 lines; undersized sibling
chunks are merged so a two-line getter does not get its own vector.

The chunker is pure: it takes paths and returns :class:`Chunk` objects. It reads
files but never embeds or stores — that is the embedder's and the store's job.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories never scanned. Matched against any path part.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".kiro",
        ".repomap",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "migrations",
        "static",
        "dist",
        "build",
        ".agents",
        ".sessions",
        "certification-data",
        "coverage",
        ".vite",
        "dev-dist",
        # Generated eval run artifacts (cae-ai-agents/agents/strut-calc/eval/results).
        "results",
        # strut-calc-v2 keeps three copies of the engine: the canonical `pre/`,
        # a runtime `workdir/` copy, and an older `dev/` variant. Index `pre/`
        # only; the other two are byte-identical duplicates that triple every
        # hit. (Verified these dir names hold no unique source in the other
        # repos.)
        "workdir",
        "dev",
    }
)

PY_SUFFIX = ".py"
JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx"})
MD_SUFFIXES = frozenset({".md"})
TEXT_SUFFIXES = PY_SUFFIX_SET = frozenset({PY_SUFFIX}) | JS_SUFFIXES | MD_SUFFIXES

# A chunk larger than this many lines is split into overlapping windows.
MAX_CHUNK_LINES = 120
# Window size and overlap used when splitting an oversized chunk.
WINDOW_LINES = 90
WINDOW_OVERLAP = 15
# Hard character ceiling per chunk. Titan v2 rejects input over 50000 chars, so
# a chunk is split on character count as a final safeguard regardless of line
# count — a file with very long lines can blow the limit well under 120 lines.
MAX_CHUNK_CHARS = 20000
# Python symbols shorter than this are merged with the next sibling.
MIN_PY_SYMBOL_LINES = 3

# JS/TS: lines that begin a top-level definition worth being its own chunk.
_JS_DEF = re.compile(
    r"""^\s*(?:export\s+)?(?:default\s+)?
        (?:async\s+)?
        (?:function\b|class\b|const\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?\(|
           const\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?function\b|
           const\s+[A-Za-z_$][\w$]*\s*=\s*\()""",
    re.VERBOSE,
)
# Name captured from a JS definition line, best-effort.
_JS_NAME = re.compile(r"(?:function\*?|class|const)\s+([A-Za-z_$][\w$]*)")


@dataclass(frozen=True)
class Chunk:
    """One embeddable unit of source.

    Attributes:
        repo: Repository label the chunk belongs to.
        path: Repo-relative POSIX path of the source file.
        lang: ``py``, ``js`` or ``md``.
        kind: ``code`` or ``doc``.
        symbol: Symbol or section name, or ``""`` when none applies.
        start_line: 1-based first line of the chunk, inclusive.
        end_line: 1-based last line of the chunk, inclusive.
        text: The chunk's source text.
    """

    repo: str
    path: str
    lang: str
    kind: str
    symbol: str
    start_line: int
    end_line: int
    text: str
    part: int = 0

    @property
    def chunk_id(self) -> str:
        """Return a stable id for the chunk.

        Derived from repo, path, line span and part index, so it survives edits
        elsewhere in the file and lets the store upsert in place. ``part``
        distinguishes character-split pieces that share a line span.

        Returns:
            A stable hex id.
        """
        key = f"{self.repo}:{self.path}:{self.start_line}-{self.end_line}:{self.part}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    @property
    def content_hash(self) -> str:
        """Return a hash of the chunk text for change detection.

        Returns:
            Hex digest of the chunk text.
        """
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


def is_skipped(path: Path) -> bool:
    """Whether a path lies under a never-scanned directory.

    Args:
        path: Candidate file path.

    Returns:
        True when any path component is in :data:`SKIP_DIRS`.
    """
    return any(part in SKIP_DIRS for part in path.parts)


def is_scannable(path: Path) -> bool:
    """Whether a file should be chunked at all.

    Skips vendored/generated directories, test files and minified vendor
    bundles. Keeps Python, JS/TS and Markdown source.

    Args:
        path: Candidate file path.

    Returns:
        True when the file is a source file worth embedding.
    """
    if path.suffix not in TEXT_SUFFIXES:
        return False
    if is_skipped(path):
        return False
    name = path.name
    if name.startswith("test_") or ".test." in name:
        return False
    if name.startswith("vendor-") or name.endswith(".min.js"):
        return False
    return True


def _split_window(lines: list[str], start_line: int) -> list[tuple[int, int, str]]:
    """Split a long run of lines into overlapping windows.

    Args:
        lines: The lines to split (the oversized chunk's body).
        start_line: 1-based line number of ``lines[0]`` in the file.

    Returns:
        A list of ``(start_line, end_line, text)`` windows.
    """
    windows: list[tuple[int, int, str]] = []
    step = WINDOW_LINES - WINDOW_OVERLAP
    index = 0
    while index < len(lines):
        window = lines[index : index + WINDOW_LINES]
        win_start = start_line + index
        win_end = win_start + len(window) - 1
        windows.append((win_start, win_end, "".join(window)))
        if index + WINDOW_LINES >= len(lines):
            break
        index += step
    return windows


def _emit(
    repo: str,
    path: str,
    lang: str,
    kind: str,
    symbol: str,
    start_line: int,
    end_line: int,
    lines: list[str],
) -> list[Chunk]:
    """Build one or more chunks from a line span, splitting if oversized.

    Args:
        repo: Repository label.
        path: Repo-relative POSIX path.
        lang: Language tag.
        kind: ``code`` or ``doc``.
        symbol: Symbol or section name.
        start_line: 1-based first line of the span.
        end_line: 1-based last line of the span.
        lines: The span's lines, newline-terminated.

    Returns:
        One chunk, or several windows when the span exceeds the size limit.
    """
    span = end_line - start_line + 1
    text = "".join(lines)
    if span <= MAX_CHUNK_LINES and len(text) <= MAX_CHUNK_CHARS:
        return [Chunk(repo, path, lang, kind, symbol, start_line, end_line, text)]

    chunks: list[Chunk] = []
    for win_start, win_end, window_text in _split_window(lines, start_line):
        chunks.extend(
            _split_on_chars(repo, path, lang, kind, symbol, win_start, win_end, window_text)
        )
    return chunks


def _split_on_chars(
    repo: str,
    path: str,
    lang: str,
    kind: str,
    symbol: str,
    start_line: int,
    end_line: int,
    text: str,
) -> list[Chunk]:
    """Split a window further if its text exceeds the character ceiling.

    A window bounded by line count can still be too large when lines are very
    long (minified or data-like files). This cuts such a window into
    character-bounded pieces that share the window's line span, so the embedder
    never sees input over the model limit.

    Args:
        repo: Repository label.
        path: Repo-relative POSIX path.
        lang: Language tag.
        kind: ``code`` or ``doc``.
        symbol: Symbol or section name.
        start_line: 1-based first line of the window.
        end_line: 1-based last line of the window.
        text: The window's text.

    Returns:
        One chunk when within the ceiling, otherwise several char-bounded chunks.
    """
    if len(text) <= MAX_CHUNK_CHARS:
        return [Chunk(repo, path, lang, kind, symbol, start_line, end_line, text)]
    pieces: list[Chunk] = []
    for part, offset in enumerate(range(0, len(text), MAX_CHUNK_CHARS)):
        pieces.append(
            Chunk(
                repo,
                path,
                lang,
                kind,
                symbol,
                start_line,
                end_line,
                text[offset : offset + MAX_CHUNK_CHARS],
                part=part,
            )
        )
    return pieces


def chunk_python(repo: str, rel_path: str, source: str) -> list[Chunk]:
    """Chunk a Python module on top-level symbol boundaries.

    Top-level functions and classes each become a chunk. A class body is kept
    whole (methods ride along with their class) so the chunk reads as a unit.
    Adjacent tiny symbols are merged. Code before the first symbol (imports,
    module constants) is emitted as a leading chunk when non-trivial.

    Args:
        repo: Repository label.
        rel_path: Repo-relative POSIX path.
        source: Full module text.

    Returns:
        The module's chunks. On a syntax error, one chunk for the whole file.
    """
    lines = source.splitlines(keepends=True)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        logger.warning("path=<%s> | python syntax error, emitting whole file", rel_path)
        return _emit(repo, rel_path, "py", "code", "", 1, len(lines), lines)

    spans: list[tuple[str, int, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            spans.append((node.name, node.lineno, end))

    if not spans:
        return _emit(repo, rel_path, "py", "code", "", 1, len(lines), lines)

    chunks: list[Chunk] = []

    # Leading block before the first symbol (imports, constants, docstring).
    first_start = spans[0][1]
    if first_start > 1:
        head = lines[: first_start - 1]
        if any(line.strip() for line in head):
            chunks.extend(
                _emit(repo, rel_path, "py", "code", "module", 1, first_start - 1, head)
            )

    merged = _merge_small(spans)
    for symbol, start, end in merged:
        body = lines[start - 1 : end]
        chunks.extend(_emit(repo, rel_path, "py", "code", symbol, start, end, body))
    return chunks


def _merge_small(spans: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Coalesce runs of tiny adjacent Python symbols into one chunk.

    Only merges when both the previous span and the current one are small (e.g.
    a cluster of one-line getters). A small symbol next to a normal-sized one is
    left alone, so an ordinary short function keeps its own chunk and name.

    Args:
        spans: ``(name, start_line, end_line)`` per top-level symbol, in order.

    Returns:
        The spans with tiny neighbours coalesced. A merged span keeps the first
        symbol's name with a ``+`` suffix to signal it carries more than one.
    """

    def is_small(start: int, end: int) -> bool:
        return (end - start + 1) < MIN_PY_SYMBOL_LINES

    merged: list[tuple[str, int, int]] = []
    for name, start, end in spans:
        if merged:
            prev_name, prev_start, prev_end = merged[-1]
            if is_small(prev_start, prev_end) and is_small(start, end):
                label = prev_name if prev_name.endswith("+") else f"{prev_name}+"
                merged[-1] = (label, prev_start, end)
                continue
        merged.append((name, start, end))
    return merged


def chunk_js(repo: str, rel_path: str, source: str) -> list[Chunk]:
    """Chunk a JS/TS file on top-level definition boundaries.

    Heuristic, not a full parse: a chunk starts at a top-level ``export`` /
    ``function`` / ``class`` / ``const X = (…=>|function)`` line and runs until
    the next one. Good enough for a who-defines-what map, which is what the
    search needs, without a JS AST dependency.

    Args:
        repo: Repository label.
        rel_path: Repo-relative POSIX path.
        source: Full file text.

    Returns:
        The file's chunks.
    """
    lines = source.splitlines(keepends=True)
    if not lines:
        return []

    boundaries: list[int] = []
    for index, line in enumerate(lines):
        # Only treat as a boundary when at low indentation, i.e. a top-level def.
        indent = len(line) - len(line.lstrip())
        if indent <= 2 and _JS_DEF.match(line):
            boundaries.append(index)

    if not boundaries:
        return _emit(repo, rel_path, "js", "code", "", 1, len(lines), lines)

    chunks: list[Chunk] = []

    if boundaries[0] > 0:
        head = lines[: boundaries[0]]
        if any(line.strip() for line in head):
            chunks.extend(
                _emit(repo, rel_path, "js", "code", "imports", 1, boundaries[0], head)
            )

    for position, start_index in enumerate(boundaries):
        end_index = boundaries[position + 1] if position + 1 < len(boundaries) else len(lines)
        body = lines[start_index:end_index]
        name_match = _JS_NAME.search(lines[start_index])
        symbol = name_match.group(1) if name_match else ""
        chunks.extend(
            _emit(repo, rel_path, "js", "code", symbol, start_index + 1, end_index, body)
        )
    return chunks


def chunk_markdown(repo: str, rel_path: str, source: str) -> list[Chunk]:
    """Chunk a Markdown file by heading.

    Each ``#``/``##``/``###`` heading starts a new section chunk. Content before
    the first heading becomes a leading chunk.

    Args:
        repo: Repository label.
        rel_path: Repo-relative POSIX path.
        source: Full file text.

    Returns:
        The file's section chunks.
    """
    lines = source.splitlines(keepends=True)
    if not lines:
        return []

    heading = re.compile(r"^#{1,3}\s+(.*)$")
    boundaries: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = heading.match(line)
        if match:
            boundaries.append((index, match.group(1).strip()))

    if not boundaries:
        return _emit(repo, rel_path, "md", "doc", "", 1, len(lines), lines)

    chunks: list[Chunk] = []

    if boundaries[0][0] > 0:
        head = lines[: boundaries[0][0]]
        if any(line.strip() for line in head):
            chunks.extend(
                _emit(repo, rel_path, "md", "doc", "intro", 1, boundaries[0][0], head)
            )

    for position, (start_index, title) in enumerate(boundaries):
        end_index = (
            boundaries[position + 1][0] if position + 1 < len(boundaries) else len(lines)
        )
        body = lines[start_index:end_index]
        chunks.extend(
            _emit(repo, rel_path, "md", "doc", title, start_index + 1, end_index, body)
        )
    return chunks


def chunk_file(repo: str, repo_root: Path, path: Path) -> list[Chunk]:
    """Chunk one source file, dispatching on its suffix.

    Args:
        repo: Repository label.
        repo_root: Absolute root of the repo, for computing the relative path.
        path: Absolute path to the file.

    Returns:
        The file's chunks, or an empty list when it is unreadable or empty.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning("path=<%s> | unreadable, skipping", path)
        return []
    if not source.strip():
        return []

    rel_path = path.relative_to(repo_root).as_posix()
    if path.suffix == PY_SUFFIX:
        return chunk_python(repo, rel_path, source)
    if path.suffix in JS_SUFFIXES:
        return chunk_js(repo, rel_path, source)
    if path.suffix in MD_SUFFIXES:
        return chunk_markdown(repo, rel_path, source)
    return []


def iter_source_files(repo_root: Path) -> list[Path]:
    """List the scannable source files under a repo root.

    Args:
        repo_root: Absolute repo root.

    Returns:
        Sorted absolute paths of files worth chunking.
    """
    found = [p for p in repo_root.rglob("*") if p.is_file() and is_scannable(p)]
    found.sort()
    return found

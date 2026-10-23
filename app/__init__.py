"""FastAPI web app for the knowledge assistant.

A small search UI over the two strands-compose agents: `searcher` (semantic
code search, streams its reasoning) and `redactor` (polishes the answer into
Markdown). The backend invokes both and streams every stage over SSE.
"""

from __future__ import annotations

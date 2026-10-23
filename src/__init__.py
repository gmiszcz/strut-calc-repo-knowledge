"""Master knowledge engine: local semantic code search over the CAE repos.

Pipeline: chunk source (AST for Python, heuristics for JS, headings for
Markdown) -> embed each chunk with Bedrock Titan v2 -> store vectors in
sqlite-vec -> query by meaning through an MCP server and a strands-compose agent.

This engine lives in the master repo and scans one or more target repositories.
StrutCalc is the first target; the schema carries a ``repo`` label so more
targets drop into the same store without a rebuild.
"""

from __future__ import annotations

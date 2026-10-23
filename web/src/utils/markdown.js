// Markdown -> HTML with KaTeX math, configured once and reused.

import { marked } from "marked";
import markedKatex from "marked-katex-extension";

marked.use(
  markedKatex({ throwOnError: false, nonStandard: true }),
  { gfm: true, breaks: true },
);

/**
 * Render a Markdown string to an HTML string.
 * Returns an empty string for empty input.
 */
export function renderMarkdown(md) {
  if (!md) return "";
  return marked.parse(md);
}

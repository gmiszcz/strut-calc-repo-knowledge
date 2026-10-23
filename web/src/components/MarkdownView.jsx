import { renderMarkdown } from "@utils/markdown";

/** Render a Markdown string as formatted HTML. */
export default function MarkdownView({ md, className = "" }) {
  return (
    <div
      className={`md-body ${className}`}
      // Content comes from our own agents over our own backend.
      dangerouslySetInnerHTML={{ __html: renderMarkdown(md) }}
    />
  );
}

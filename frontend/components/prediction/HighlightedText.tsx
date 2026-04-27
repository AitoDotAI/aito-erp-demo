"use client";

import { ReactNode } from "react";

/** Render a highlight string from Aito where matched tokens are wrapped
 * in « / » sentinel tags (positive lifts) or <font color="red">…</font>
 * (negative-lift "anti-tokens" Aito injects on its own). Renders both as
 * <mark> elements with appropriate styling — no dangerouslySetInnerHTML. */
export function HighlightedText({ text }: { text: string }) {
  if (!text) return null;

  // Strip stray HTML font tags Aito injects for negative-lift tokens, but
  // remember which substrings they wrapped so we can render them dimmed.
  const NEG_OPEN = "";
  const NEG_CLOSE = "";
  const normalized = text
    .replace(/<font[^>]*>/gi, NEG_OPEN)
    .replace(/<\/font>/gi, NEG_CLOSE);

  // Split on either positive (« ») or negative ( ) wrappers.
  const parts: Array<{ text: string; kind: "plain" | "match" | "anti" }> = [];
  let i = 0;
  while (i < normalized.length) {
    const posStart = normalized.indexOf("«", i);
    const negStart = normalized.indexOf(NEG_OPEN, i);
    let nextStart = -1;
    let kind: "match" | "anti" = "match";
    let openLen = 1;
    let close = "»";

    if (posStart !== -1 && (negStart === -1 || posStart < negStart)) {
      nextStart = posStart;
      kind = "match";
      close = "»";
    } else if (negStart !== -1) {
      nextStart = negStart;
      kind = "anti";
      close = NEG_CLOSE;
    }

    if (nextStart === -1) {
      parts.push({ text: normalized.slice(i), kind: "plain" });
      break;
    }
    if (nextStart > i) {
      parts.push({ text: normalized.slice(i, nextStart), kind: "plain" });
    }
    const closeIdx = normalized.indexOf(close, nextStart + openLen);
    if (closeIdx === -1) {
      parts.push({ text: normalized.slice(nextStart + openLen), kind });
      break;
    }
    parts.push({ text: normalized.slice(nextStart + openLen, closeIdx), kind });
    i = closeIdx + 1;
  }

  const out: ReactNode[] = [];
  parts.forEach((p, idx) => {
    if (!p.text) return;
    if (p.kind === "plain") out.push(<span key={idx}>{p.text}</span>);
    else if (p.kind === "match") out.push(<mark key={idx} className="why-highlight">{p.text}</mark>);
    else out.push(<mark key={idx} className="why-anti-highlight">{p.text}</mark>);
  });
  return <>{out}</>;
}

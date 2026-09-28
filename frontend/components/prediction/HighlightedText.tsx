"use client";

import { ReactNode } from "react";

/** Render a highlight string from Aito where matched tokens are wrapped
 * in « / » sentinel tags (positive lifts) or <font color="red">…</font>
 * (negative-lift "anti-tokens" Aito injects on its own). Renders both as
 * <mark> elements with appropriate styling — no dangerouslySetInnerHTML. */
// Aito's highlight text is HTML-escaped ("Security upgrade &mdash; door
// locks"), and this component renders it as TEXT — deliberately, so a
// description can never inject markup. Entities are therefore decoded to
// the characters they stand for, and nothing is ever parsed as HTML.
const NAMED_ENTITIES: Record<string, string> = {
  amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: "\u00A0",
  mdash: "\u2014", ndash: "\u2013", hellip: "\u2026", euro: "\u20AC",
  auml: "\u00E4", ouml: "\u00F6", aring: "\u00E5", Auml: "\u00C4", Ouml: "\u00D6", Aring: "\u00C5",
};

export function decodeEntities(s: string): string {
  return s.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-zA-Z]+);/g, (whole, body: string) => {
    if (body[0] === "#") {
      const code = body[1] === "x" || body[1] === "X" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : whole;
    }
    // An entity outside the table is shown as written rather than guessed.
    return NAMED_ENTITIES[body] ?? whole;
  });
}

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
    const shown = decodeEntities(p.text);
    if (p.kind === "plain") out.push(<span key={idx}>{shown}</span>);
    else if (p.kind === "match") out.push(<mark key={idx} className="why-highlight">{shown}</mark>);
    else out.push(<mark key={idx} className="why-anti-highlight">{shown}</mark>);
  });
  return <>{out}</>;
}

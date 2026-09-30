/**
 * The query a side panel shows is one the backend actually sent.
 *
 * Panels used to carry hand-written query HTML, and they drifted:
 * tables that do not exist, clauses the client always adds left out,
 * samples unrelated to the screen. The backend now records every body
 * it sends while producing a response and returns them under
 * `_queries` (src/query_log.py). A page picks the one behind what is
 * on screen with `findQuery`; the panel renders it with `queryHtml`.
 * No page writes query text — tests/test_query_panes_recorded.py
 * fails if one does.
 */

export interface RecordedQuery {
  endpoint: string;
  body: Record<string, unknown>;
}

/** Any response the backend stamped with the queries behind it. */
export interface WithQueries {
  _queries?: RecordedQuery[];
}

export interface QueryMatch {
  endpoint?: string;
  /** The `from` table. A nested `from` (a scoped population) never matches a name. */
  from?: string;
  /** The field asked about: `predict`, `estimate`, `relate` or `recommend`. */
  target?: string;
  /** Clauses the query's `where` must contain, compared by value. */
  where?: Record<string, unknown>;
}

const TARGET_KEYS = ["predict", "estimate", "relate", "recommend"] as const;

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function targetOf(body: Record<string, unknown>): unknown {
  for (const k of TARGET_KEYS) if (body[k] !== undefined) return body[k];
  return undefined;
}

function targetMatches(target: unknown, want: string): boolean {
  // v2 sends `relate` as a list; a name matches if it is in it.
  return Array.isArray(target) ? target.includes(want) : target === want;
}

/** The first recorded query that fits, or null — a panel with no
 *  matching record shows no query rather than a sample. */
export function findQuery(
  queries: RecordedQuery[] | undefined | null,
  match: QueryMatch,
): RecordedQuery | null {
  for (const q of queries ?? []) {
    if (match.endpoint && q.endpoint !== match.endpoint) continue;
    if (match.from && q.body.from !== match.from) continue;
    if (match.target && !targetMatches(targetOf(q.body), match.target)) continue;
    if (match.where) {
      const where = (q.body.where ?? {}) as Record<string, unknown>;
      if (!Object.entries(match.where).every(([k, v]) => sameValue(where[k], v))) continue;
    }
    return q;
  }
  return null;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const INDENT = "&nbsp;&nbsp;";

function renderValue(value: unknown, depth: number, highlight: boolean): string {
  const pad = INDENT.repeat(depth + 1);
  const close = INDENT.repeat(depth);
  if (value === null) return `<span class="q-n">null</span>`;
  if (typeof value === "string") {
    const cls = highlight ? "q-p" : "q-v";
    return `<span class="${cls}">${escapeHtml(JSON.stringify(value))}</span>`;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return `<span class="q-n">${String(value)}</span>`;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    // Short lists of scalars stay on one line, as a person would write them.
    if (value.every((v) => typeof v !== "object" || v === null) && JSON.stringify(value).length <= 48) {
      return "[" + value.map((v) => renderValue(v, depth, highlight)).join(", ") + "]";
    }
    return "[<br/>" + value.map((v) => pad + renderValue(v, depth + 1, highlight)).join(",<br/>")
      + "<br/>" + close + "]";
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "{}";
    return "{<br/>" + entries.map(([k, v]) => {
      const keyCls = k.startsWith("$") ? "q-op" : "q-k";
      const isTarget = depth === 0 && (TARGET_KEYS as readonly string[]).includes(k);
      return `${pad}<span class="${keyCls}">${escapeHtml(JSON.stringify(k))}</span>: `
        + renderValue(v, depth + 1, highlight || isTarget);
    }).join(",<br/>") + "<br/>" + close + "}";
  }
  throw new Error(`queryHtml: unexpected ${typeof value} in a recorded query body`);
}

/** The recorded body as the panel's highlighted HTML, escaped once. */
export function queryHtml(q: RecordedQuery, version: string): string {
  return `<span class="q-k">POST</span> /api/${escapeHtml(version)}/${escapeHtml(q.endpoint)}<br/>`
    + renderValue(q.body, 0, false);
}

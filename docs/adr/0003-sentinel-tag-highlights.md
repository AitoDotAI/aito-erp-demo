# ADR 0003: Sentinel-tag highlights instead of `dangerouslySetInnerHTML`

**Status:** Accepted
**Date:** 2026-04
**Deciders:** Demo team

## Context

Aito's `_predict` returns token-level matches in the `$why.factors[].highlight`
array. Each entry has a `field` and a `highlight` string — for example:

```
"Issue <b>RM</b> to <b>production</b>"
```

The default tag is `<b>...</b>`. Rendering this in React is a problem:
either use `dangerouslySetInnerHTML` (XSS surface) or parse the HTML.

## Decision

We pass non-HTML sentinel characters as the tag delimiters in every
`_predict` call:

```python
"select": [
    "$p",
    "feature",
    {
        "$why": {
            "highlight": {
                "posPreTag": "«",
                "posPostTag": "»",
            }
        }
    },
]
```

The frontend's `HighlightedText` component splits the string on
`/«([^»]*)»/`, mapping odd-indexed parts to `<mark>` elements and
even-indexed parts to `<span>`. No HTML parsing, no
`dangerouslySetInnerHTML`, no DOMPurify dependency.

## Consequences

**Good:**
- XSS surface eliminated — Aito is treated as a string oracle, not an
  HTML emitter
- No new runtime dependency
- The same component handles a quirk: Aito occasionally injects
  `<font color="red">…</font>` for negative-lift "anti-tokens". We
  detect those, normalize them to a parallel sentinel pair, and render
  them as struck-through red `<mark>`s
- Sentinel characters are visually distinctive enough that you'd
  notice if they leaked into a non-highlight context

**Bad:**
- The sentinel chars (`«` `»`) are valid Unicode that real product
  names could contain (rare but not impossible). If a product called
  "Café «Latte»" appears, the splitter will misinterpret it. Tradeoff:
  unlikely on a Finnish procurement dataset; would need escaping for
  multilingual catalogs
- The first version used `<b>` and ended up with sanitization concerns
  that pushed us toward this approach. A future implementation could
  use the React-native `dangerouslySetInnerHTML` + DOMPurify path if
  the data grew to include those characters legitimately

## Alternatives considered

- **`dangerouslySetInnerHTML` + DOMPurify**: rejected — the dependency
  cost wasn't worth it for a demo with controlled data
- **Custom Aito-side tag selection**: chose `«` / `»` after verifying
  Aito accepts arbitrary string delimiters in
  `posPreTag` / `posPostTag` (it does)
- **Server-side highlight rendering**: rejected — couples backend to
  frontend rendering decisions

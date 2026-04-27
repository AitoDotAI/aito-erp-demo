# ADR 0004: Three-state SmartField (one field per concept)

**Status:** Accepted
**Date:** 2026-04
**Deciders:** Demo team

## Context

The first iteration of Smart Entry had separate "raw input" fields and
"predicted output" fields. The user typed in the top section, watched
predictions render in the bottom section, and submitted. This is the
**duplicated-field anti-pattern** described in the
[smart forms guide](https://aito.ai/docs/guides/smart-forms): two
fields, one concept.

The problems showed up immediately during live demos:

- "Where do I edit cost center? It says Production but I want
  Facilities" — the predicted value was read-only; users had to
  understand they couldn't override there
- "I see 4810 in the predicted column. Did the system put it there or
  did I?" — no visual distinction between guessed and confirmed values
- "Submit" took only the typed values and discarded the predictions —
  surprising and wrong

## Decision

We collapsed each predictable field to a **single DOM input** with
three visual states keyed off a `source` enum:

| Source | Visual | Behaviour |
|--------|--------|-----------|
| `empty` | normal input, ghost placeholder | type to fill |
| `predicted` | gold background, italic, fade-in animation, 🤖 badge below | Tab/blur promotes to `user`; Esc clears; typing replaces |
| `user` | normal input | normal editing |

The component is `SmartField`. It exposes a single `onChange` that
always reports `source: "user"` — accepting a prediction is just
"typing zero characters." The owning page tracks per-field source in a
`Record<FieldName, FieldState>` and never mutates a `user`-sourced
field even when fresh predictions arrive.

## Consequences

**Good:**
- The form fits on one screen
- "Where do I edit?" becomes obvious — the predicted value is the field
- The visual distinction between predicted and user-confirmed values
  survives screenshots and remote demos
- Submit captures whatever the field shows; no separate state to
  reconcile

**Bad:**
- The component is more complex than a plain `<input>` — about 130
  lines of source
- Tab-to-accept is a hidden affordance for users who haven't seen the
  pattern; we mitigate with the three-state badge below the input but
  it requires a quick coaching moment in live demos
- Esc-to-clear conflicts with browser autofill on some setups
  (rare but observed)

## Alternatives considered

- **Separate input + display field**: this is what we replaced
  (the anti-pattern)
- **Modal "Did you mean…?" confirmation**: rejected — friction for
  the common case
- **Read-only predictions with a "Use these" button**: rejected —
  works for batch but feels paternalistic in a single-record form

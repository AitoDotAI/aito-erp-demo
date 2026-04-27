"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { Alternative, WhyExplanation } from "@/lib/types";
import WhyPopover from "./WhyPopover";

/** A field whose current value comes from one of three sources:
 *   - "empty"     — no value, ghost suggestion shown as placeholder
 *   - "predicted" — value from Aito; styled gold-italic; clears on Esc
 *   - "user"      — value typed by the user; normal styling
 *
 * Behaviour:
 *   - Tab / blur on a predicted field → promotes to "user" (silent accept).
 *   - Esc on a predicted field → clears.
 *   - Typing into a predicted field → replaces it; source becomes "user".
 *   - The "?" / "!" button always shows the explanation.
 *   - Focus opens a dropdown listing every alternative ordered by
 *     probability. As the user types, the list is filtered to entries
 *     whose value starts with the typed prefix (case-insensitive); the
 *     remaining entries keep their probability order.
 */
export type FieldSource = "empty" | "predicted" | "user" | "derived";

export interface SmartFieldProps {
  label: string;
  fieldName: string;
  value: string;
  source: FieldSource;
  confidence?: number;
  why?: WhyExplanation;
  alternatives?: Alternative[];
  /** When the user types, accepts a prediction (Tab/blur), or picks
   * an alternative — the source flips to "user". */
  onChange: (value: string, source: "user") => void;
  /** Reject the prediction (clears to empty). */
  onReject?: () => void;
  /** Called when the popover opens with the set of $context. fields that
   * influenced the prediction. Empty set on close. */
  onContextFieldsChange?: (fields: Set<string>) => void;
  /** When an upstream popover marks this field as a contributor, the
   * outer page sets this to true and we draw an outline. */
  highlighted?: boolean;
  readOnly?: boolean;
  placeholder?: string;
}

function fmtP(p: number): string {
  if (p >= 0.1) return `${Math.round(p * 100)}%`;
  if (p >= 0.001) return `${(p * 100).toFixed(1)}%`;
  return `${(p * 100).toFixed(2)}%`;
}

function confColor(p: number): string {
  if (p >= 0.85) return "var(--green)";
  if (p >= 0.5) return "var(--gold)";
  return "var(--red)";
}

export default function SmartField({
  label,
  fieldName,
  value,
  source,
  confidence = 0,
  why,
  alternatives,
  onChange,
  onReject,
  onContextFieldsChange,
  highlighted = false,
  readOnly = false,
  placeholder,
}: SmartFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [focused, setFocused] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);

  const isPredicted = source === "predicted" && !!value;
  const isEmpty = !value;

  // Filter while preserving the order alternatives came in (by probability).
  // When the value is a still-pending prediction we don't filter — the
  // user hasn't typed anything yet, so show the full list.
  const filtered = useMemo(() => {
    const list = alternatives ?? [];
    if (!list.length) return list;
    const prefix = source === "user" ? value.trim().toLowerCase() : "";
    if (!prefix) return list;
    return list.filter((a) => a.value.toLowerCase().startsWith(prefix));
  }, [alternatives, value, source]);

  // Keep active index in range when the filtered list changes.
  useEffect(() => {
    if (activeIdx >= filtered.length) setActiveIdx(0);
  }, [filtered.length, activeIdx]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handle = (e: MouseEvent) => {
      if (wrapRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  const hasDropdown = (alternatives?.length ?? 0) > 0;

  const selectAlt = (alt: Alternative) => {
    onChange(alt.value, "user");
    setOpen(false);
    setActiveIdx(0);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      if (open) {
        e.preventDefault();
        setOpen(false);
        return;
      }
      if (isPredicted) {
        e.preventDefault();
        onReject?.();
      }
      return;
    }
    if (!hasDropdown) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) setOpen(true);
      else setActiveIdx((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && open && filtered[activeIdx]) {
      e.preventDefault();
      selectAlt(filtered[activeIdx]);
    }
  };

  const handleFocus = () => {
    setFocused(true);
    if (hasDropdown) setOpen(true);
  };

  const handleBlur = (e: React.FocusEvent<HTMLInputElement>) => {
    // Don't close when focus moves into the dropdown itself.
    const next = e.relatedTarget as Node | null;
    if (next && wrapRef.current?.contains(next)) return;
    setFocused(false);
    setOpen(false);
    // Tab / click-away on a predicted field promotes to user-entered.
    if (isPredicted) onChange(value, "user");
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value, "user");
    if (hasDropdown) setOpen(true);
    setActiveIdx(0);
  };

  const handleAcceptAlternative = (alt: Alternative) => {
    onChange(alt.value, "user");
  };

  const sourceClass =
    source === "user" ? "sf-user" :
    source === "predicted" ? "sf-predicted" :
    source === "derived" ? "sf-derived" :
    "sf-empty";

  return (
    <div
      ref={wrapRef}
      className={`smart-field${highlighted ? " sf-highlighted" : ""}`}
      data-field={fieldName}
    >
      <div className="smart-field-label-row">
        <label className="form-label">{label}</label>
        {!isEmpty && why && (
          <WhyPopover
            value={value}
            confidence={confidence}
            why={why}
            alternatives={alternatives}
            onSelectAlternative={handleAcceptAlternative}
            onContextFieldsChange={onContextFieldsChange}
          />
        )}
      </div>
      <div className="sf-combobox">
        <input
          ref={inputRef}
          type="text"
          className={`form-input ${sourceClass}`}
          value={value}
          readOnly={readOnly}
          placeholder={placeholder}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={handleFocus}
          onBlur={handleBlur}
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          aria-controls={`${fieldName}-listbox`}
        />
        {hasDropdown && !readOnly && (
          <button
            type="button"
            className="sf-caret"
            tabIndex={-1}
            aria-label={open ? "Hide predictions" : "Show all predictions"}
            onMouseDown={(e) => {
              e.preventDefault(); // keep focus on input
              setOpen((v) => !v);
              inputRef.current?.focus();
            }}
          >
            ▾
          </button>
        )}
        {open && hasDropdown && (
          <ul
            id={`${fieldName}-listbox`}
            className="sf-dropdown"
            role="listbox"
            onMouseDown={(e) => e.preventDefault()}
          >
            {filtered.length === 0 ? (
              <li className="sf-dropdown-empty">No matches for "{value}"</li>
            ) : (
              filtered.map((alt, i) => {
                const pct = Math.max(0, Math.min(1, alt.confidence));
                return (
                  <li
                    key={`${alt.value}-${i}`}
                    role="option"
                    aria-selected={i === activeIdx}
                    className={`sf-dropdown-item${i === activeIdx ? " active" : ""}${alt.value === value ? " current" : ""}`}
                    onMouseEnter={() => setActiveIdx(i)}
                    onClick={() => selectAlt(alt)}
                  >
                    <span className="sf-dropdown-value">{alt.value || "—"}</span>
                    <span className="sf-dropdown-bar conf-track">
                      <span
                        className="conf-fill"
                        style={{ width: `${Math.round(pct * 100)}%`, background: confColor(pct) }}
                      />
                    </span>
                    <span className="sf-dropdown-pct mono">{fmtP(pct)}</span>
                  </li>
                );
              })
            )}
          </ul>
        )}
      </div>
      <div className="smart-field-meta">
        {isPredicted && (
          <>
            <span className="sf-badge-predicted">🤖 predicted</span>
            <span className="sf-conf">{Math.round(confidence * 100)}%</span>
            {onReject && (
              <button
                type="button"
                className="sf-reject"
                onClick={onReject}
                title="Reject prediction (Esc)"
              >Clear</button>
            )}
          </>
        )}
        {source === "user" && value && (
          <span className="sf-badge-user">✓ entered</span>
        )}
        {source === "derived" && (
          <span className="sf-badge-derived">→ derived</span>
        )}
        {source === "empty" && focused && alternatives && alternatives.length > 0 && (
          <span style={{ fontSize: 10, color: "var(--mid)" }}>
            {alternatives.length} suggestion{alternatives.length > 1 ? "s" : ""} — type to filter
          </span>
        )}
      </div>
    </div>
  );
}

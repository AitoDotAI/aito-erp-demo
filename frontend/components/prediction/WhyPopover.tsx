"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Alternative, WhyExplanation } from "@/lib/types";
import PredictionExplanation from "./PredictionExplanation";

/** Pattern C: a "?" button anchored to a row that opens a popover with
 * the full PredictionExplanation. Visual prominence of the button scales
 * inversely with confidence — faint at high, alert at low.
 *
 * Confidence tiers (from the explanations guide):
 *   high   ≥ 0.85  → small dim affordance
 *   medium 0.5–0.85 → standard "?" badge
 *   low    < 0.5   → red "!" alert
 */
export interface WhyPopoverProps {
  value: string;
  confidence: number;
  why?: WhyExplanation;
  alternatives?: Alternative[];
  onSelectAlternative?: (alt: Alternative) => void;
  /** Called with the set of input field names that contributed (from
   * $context. prefixes) when popover opens. Empty set on close. */
  onContextFieldsChange?: (fields: Set<string>) => void;
}

export default function WhyPopover({
  value,
  confidence,
  why,
  alternatives,
  onSelectAlternative,
  onContextFieldsChange,
}: WhyPopoverProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  const tier = confidence >= 0.85 ? "high" : confidence >= 0.5 ? "medium" : "low";
  const isLow = tier === "low";

  // Close on click outside / scroll / escape
  useEffect(() => {
    if (!open) return;
    function handleDocMouseDown(e: MouseEvent) {
      if (popRef.current?.contains(e.target as Node)) return;
      if (btnRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function handleScroll() {
      if (btnRef.current) {
        const r = btnRef.current.getBoundingClientRect();
        setPos({ top: r.bottom + 6, left: Math.max(8, r.right - 380) });
      }
    }
    document.addEventListener("mousedown", handleDocMouseDown);
    document.addEventListener("keydown", handleKey);
    window.addEventListener("scroll", handleScroll, true);
    return () => {
      document.removeEventListener("mousedown", handleDocMouseDown);
      document.removeEventListener("keydown", handleKey);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [open]);

  // Notify parent about cross-highlight fields ONLY when the popover
  // toggles open/closed. Earlier this effect listed `why` and
  // `onContextFieldsChange` in its dep array — both are fresh
  // references on every parent render, so the effect re-fired on
  // every render, called the parent's setter with a new `Set()`,
  // re-rendered the parent, made the callback a fresh ref again, and
  // looped. Capture the latest values via refs and depend only on
  // `open`.
  const onContextChangeRef = useRef(onContextFieldsChange);
  const whyRef = useRef(why);
  useEffect(() => {
    onContextChangeRef.current = onContextFieldsChange;
    whyRef.current = why;
  });
  useEffect(() => {
    const handler = onContextChangeRef.current;
    if (!handler) return;
    if (open) {
      const fields = whyRef.current?.context_fields ?? [];
      handler(fields.length ? new Set(fields) : new Set());
    } else {
      handler(new Set());
    }
  }, [open]);

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 6, left: Math.max(8, r.right - 380) });
    }
    setOpen((v) => !v);
  };

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        className={`why-trigger why-trigger-${tier}${open ? " open" : ""}`}
        onClick={toggle}
        title={isLow ? "Low confidence — investigate" : "Why this prediction?"}
        aria-label="Show prediction explanation"
      >
        {isLow ? "!" : "?"}
      </button>
      {open && pos && typeof document !== "undefined" && createPortal(
        <div
          ref={popRef}
          className="why-popover"
          style={{ top: pos.top, left: pos.left }}
          onClick={(e) => e.stopPropagation()}
          role="dialog"
        >
          <PredictionExplanation
            value={value}
            confidence={confidence}
            why={why}
            alternatives={alternatives}
            onSelectAlternative={(alt) => {
              onSelectAlternative?.(alt);
              setOpen(false);
            }}
          />
        </div>,
        document.body,
      )}
    </>
  );
}

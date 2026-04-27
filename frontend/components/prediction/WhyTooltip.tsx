"use client";

import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import type { WhyFactor } from "@/lib/types";

interface WhyTooltipProps {
  factors: WhyFactor[];
}

export default function WhyTooltip({ factors }: WhyTooltipProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const btnRef = useRef<HTMLButtonElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function handleClickOutside(e: MouseEvent) {
      if (
        btnRef.current &&
        !btnRef.current.contains(e.target as Node) &&
        tooltipRef.current &&
        !tooltipRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  function handleToggle() {
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect();
      setPos({
        top: rect.bottom + 6,
        left: Math.max(8, rect.left - 120),
      });
    }
    setOpen(!open);
  }

  if (!factors || factors.length === 0) return null;

  return (
    <>
      <button
        ref={btnRef}
        onClick={handleToggle}
        style={{
          width: 18,
          height: 18,
          borderRadius: "50%",
          border: "1px solid var(--border)",
          background: open ? "var(--gold-light)" : "var(--card)",
          color: open ? "var(--gold-dark)" : "var(--mid)",
          fontSize: 10,
          fontWeight: 700,
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "'DM Mono', monospace",
          lineHeight: 1,
          flexShrink: 0,
        }}
        title="Show prediction reasoning"
      >
        ?
      </button>

      {open &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            ref={tooltipRef}
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              zIndex: 9999,
              background: "var(--aito-bg)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 6,
              padding: "10px 12px",
              minWidth: 240,
              maxWidth: 320,
              boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
            }}
          >
            <div className="aito-why-title">$why factors</div>
            {factors.map((f, i) => (
              <div className="aito-factor" key={i}>
                <span className="f-token">{f.field}</span>
                <span className="f-lift">{f.lift.toFixed(1)}x</span>
                <span className="f-desc">{f.value}</span>
              </div>
            ))}
          </div>,
          document.body
        )}
    </>
  );
}

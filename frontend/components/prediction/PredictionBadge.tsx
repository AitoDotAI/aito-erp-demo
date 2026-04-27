"use client";

import { useState, useRef, useEffect } from "react";
import type { Alternative } from "@/lib/types";

interface PredictionBadgeProps {
  value: string;
  confidence: number;
  predicted?: boolean;
  alternatives?: Alternative[];
  onSelect?: (value: string) => void;
}

export default function PredictionBadge({
  value,
  confidence,
  predicted = true,
  alternatives,
  onSelect,
}: PredictionBadgeProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const badgeClass = predicted && confidence >= 0.5 ? "b-gold" : "b-gray";
  const prefix = predicted ? "\uD83E\uDD16 " : "";

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
      <span
        className={`badge ${badgeClass}`}
        style={{ cursor: alternatives?.length ? "pointer" : "default" }}
        onClick={() => alternatives?.length && setOpen(!open)}
      >
        {prefix}{value}
      </span>

      {open && alternatives && alternatives.length > 0 && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            marginTop: 4,
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
            zIndex: 200,
            minWidth: 160,
            padding: "4px 0",
          }}
        >
          {alternatives.map((alt, i) => (
            <div
              key={i}
              onClick={() => {
                onSelect?.(alt.value);
                setOpen(false);
              }}
              style={{
                padding: "6px 12px",
                fontSize: 11,
                cursor: "pointer",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 12,
                transition: "background 0.1s",
              }}
              onMouseEnter={(e) =>
                ((e.target as HTMLElement).style.background = "#faf8f2")
              }
              onMouseLeave={(e) =>
                ((e.target as HTMLElement).style.background = "transparent")
              }
            >
              <span>{alt.value}</span>
              <span
                className="mono"
                style={{
                  fontSize: 10,
                  color:
                    alt.confidence >= 0.8
                      ? "var(--green)"
                      : alt.confidence >= 0.5
                      ? "var(--gold-dark)"
                      : "var(--red)",
                }}
              >
                {Math.round(alt.confidence * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

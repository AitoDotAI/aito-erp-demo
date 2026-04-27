"use client";

interface ConfidenceBarProps {
  /** Confidence as a fraction 0..1 */
  value: number;
  /** Track width in px, default 60 */
  width?: number;
}

export default function ConfidenceBar({ value, width = 60 }: ConfidenceBarProps) {
  const pct = Math.round(value * 100);
  let color: string;
  let valColor: string | undefined;

  if (value >= 0.80) {
    color = "var(--green)";
  } else if (value >= 0.50) {
    color = "var(--gold)";
  } else {
    color = "var(--red)";
    valColor = "var(--red)";
  }

  return (
    <div className="conf">
      <div className="conf-track" style={{ width }}>
        <div
          className="conf-fill"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="conf-val" style={valColor ? { color: valColor } : undefined}>
        {pct}%
      </span>
    </div>
  );
}

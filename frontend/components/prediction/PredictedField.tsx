"use client";

import { useState } from "react";
import WhyTooltip from "./WhyTooltip";
import type { WhyFactor } from "@/lib/types";

interface PredictedFieldProps {
  label: string;
  value: string;
  confidence: number;
  predicted?: boolean;
  why?: WhyFactor[];
  onChange?: (value: string) => void;
  readOnly?: boolean;
}

export default function PredictedField({
  label,
  value,
  confidence,
  predicted = true,
  why,
  onChange,
  readOnly = false,
}: PredictedFieldProps) {
  const [currentValue, setCurrentValue] = useState(value);
  const [overridden, setOverridden] = useState(false);

  const isPredicted = predicted && !overridden;
  const pct = Math.round(confidence * 100);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value;
    setCurrentValue(v);
    setOverridden(v !== value);
    onChange?.(v);
  }

  return (
    <div className="form-group">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <label className="form-label">{label}</label>
        {isPredicted && why && why.length > 0 && <WhyTooltip factors={why} />}
      </div>
      <input
        type="text"
        className={`form-input${isPredicted ? " predicted" : ""}`}
        value={currentValue}
        onChange={handleChange}
        readOnly={readOnly}
      />
      {isPredicted && (
        <div className="predicted-label">
          Predicted {pct}% confidence
        </div>
      )}
    </div>
  );
}

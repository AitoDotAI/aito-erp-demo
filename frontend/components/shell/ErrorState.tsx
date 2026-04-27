"use client";

interface ErrorStateProps {
  title?: string;
  message?: string;
  command?: string;
}

export default function ErrorState({
  title = "Something went wrong",
  message = "Unable to load data. Please try again.",
  command,
}: ErrorStateProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "60px 24px",
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 32, marginBottom: 16, opacity: 0.4 }}>
        &#x26A0;&#xFE0F;
      </div>
      <h3
        style={{
          fontFamily: "'DM Serif Display', serif",
          fontSize: 18,
          color: "var(--ink)",
          marginBottom: 8,
        }}
      >
        {title}
      </h3>
      <p
        style={{
          fontSize: 13,
          color: "var(--mid)",
          maxWidth: 400,
          lineHeight: 1.5,
          marginBottom: command ? 16 : 0,
        }}
      >
        {message}
      </p>
      {command && (
        <code
          style={{
            fontFamily: "'DM Mono', monospace",
            fontSize: 11,
            background: "#f0ede6",
            padding: "6px 12px",
            borderRadius: 5,
            color: "var(--mid)",
          }}
        >
          {command}
        </code>
      )}
    </div>
  );
}

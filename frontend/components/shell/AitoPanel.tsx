"use client";

import { useState } from "react";
import { AitoPanelConfig } from "@/lib/types";

interface AitoPanelProps {
  config: AitoPanelConfig;
}

export default function AitoPanel({ config }: AitoPanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <>
      <button
        className={`aito-toggle${collapsed ? " collapsed" : ""}`}
        onClick={() => setCollapsed((v) => !v)}
        title={collapsed ? "Expand prediction panel" : "Collapse prediction panel"}
        aria-label="Toggle prediction panel"
      >
        {collapsed ? "◀" : "▶"}
      </button>
      <aside className={`aito-side${collapsed ? " collapsed" : ""}`}>
      <div className="aito-side-header">
        <div className="aito-side-top">
          <div className="aito-side-brand">
            <img
              src="/assets/aito-logo-theme.svg"
              alt="Aito.ai"
              className="aito-side-logo"
            />
            <span className="aito-side-tagline">The Predictive DB</span>
          </div>
          <span className="aito-side-label">{config.operation}</span>
        </div>

        {config.stats && config.stats.length > 0 && (
          <div className="aito-side-stats">
            {config.stats.map((stat, i) => (
              <div className="aito-stat" key={i}>
                <div className="aito-stat-val">{stat.value}</div>
                <div className="aito-stat-label">{stat.label}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="aito-side-body">
        {config.query && (
          <div
            className="aito-query-block"
            dangerouslySetInnerHTML={{ __html: config.query }}
          />
        )}

        {config.description && (
          <>
            <div className="aito-section">How it works</div>
            <div
              className="aito-note"
              dangerouslySetInnerHTML={{ __html: config.description }}
            />
          </>
        )}

        {config.links && config.links.length > 0 && (
          <>
            <div className="aito-section">Learn more</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {config.links.map((link, i) => (
                <a
                  key={i}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "10.5px",
                    color: "var(--aito-teal)",
                    textDecoration: "none",
                  }}
                >
                  {link.label} &rarr;
                </a>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Collapsed strip — visible when aside has .collapsed class */}
      <div className="aito-tab-strip">
        <div className="aito-strip-label">aito.. prediction</div>
      </div>
    </aside>
    </>
  );
}

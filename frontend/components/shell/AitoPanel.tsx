"use client";

import { useState, type ReactNode } from "react";
import { AitoPanelConfig } from "@/lib/types";

interface AitoPanelProps {
  config: AitoPanelConfig;
}

/**
 * Right-rail prediction panel — mirrors aito-demo's ContextPanel
 * (src/aito-demo/src/app/components/ContextPanel.{js,css}). Same
 * vertical structure: brand header → stat row → endpoint pills →
 * description → example query → resource links → bottom CTA.
 *
 * Mobile (≤ 768px): the side `<aside>` is hidden; a floating round
 * info button lives in the bottom-right corner. Tap → backdrop +
 * bottom sheet slides up with the same content. Pattern copied from
 * aito-demo's ContextPanel mobile mode.
 *
 * The "Try Aito" CTA used to live in the bottom-left Nav. The aito-
 * demo pattern parks it here on the right rail instead, next to the
 * page-specific Aito context — same place a CTO finishes reading
 * "this is the query" and decides whether to click "Start free
 * trial".
 */
export default function AitoPanel({ config }: AitoPanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // The body block is rendered both in the desktop `<aside>` and inside
  // the mobile bottom sheet — extract once so the markup stays in one
  // place and the mobile copy doesn't drift from the desktop one.
  const body: ReactNode = (
    <>
      {config.endpoints && config.endpoints.length > 0 && (
        <div className="aito-endpoints">
          {config.endpoints.map((ep) => (
            <span key={ep} className="aito-endpoint-pill">
              {ep}
            </span>
          ))}
        </div>
      )}

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
          <div className="aito-links">
            {config.links.map((link, i) => (
              <a
                key={i}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="aito-link"
              >
                <span className="aito-link-icon" aria-hidden="true">
                  {link.kind === "github" ? "{ }" : link.kind === "doc" ? "📖" : "↗"}
                </span>
                {link.label}
              </a>
            ))}
          </div>
        </>
      )}
    </>
  );

  const cta: ReactNode = (
    <div className="aito-side-cta">
      <a
        href="https://aito.ai"
        target="_blank"
        rel="noopener noreferrer"
        className="aito-side-cta-link"
      >
        Start free trial <span aria-hidden="true">→</span>
      </a>
    </div>
  );

  return (
    <>
      {/* Desktop collapse toggle — hidden under mobile media query. */}
      <button
        className={`aito-toggle${collapsed ? " collapsed" : ""}`}
        onClick={() => setCollapsed((v) => !v)}
        title={collapsed ? "Expand prediction panel" : "Collapse prediction panel"}
        aria-label="Toggle prediction panel"
      >
        {collapsed ? "◀" : "▶"}
      </button>

      {/* Desktop side rail — hidden under mobile media query. */}
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

        <div className="aito-side-body">{body}</div>

        {cta}

        {/* Collapsed strip — visible when aside has .collapsed class */}
        <div className="aito-tab-strip">
          <div className="aito-strip-label">aito.. prediction</div>
        </div>
      </aside>

      {/* ───────── Mobile: floating button + bottom sheet ─────────
          Only visible at ≤ 768px (display rules in globals.css).
          Pattern copied from aito-demo's ContextPanel mobile mode. */}
      <button
        type="button"
        className="aito-mobile-toggle"
        onClick={() => setMobileOpen((v) => !v)}
        aria-label="Open prediction panel"
        aria-expanded={mobileOpen}
      >
        <img
          src="/assets/aito-favicon.svg"
          alt=""
          className="aito-mobile-toggle-icon"
          aria-hidden="true"
        />
      </button>

      {mobileOpen && (
        <div
          className="aito-mobile-overlay"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <div
        className={`aito-mobile-sheet${mobileOpen ? " aito-mobile-sheet--open" : ""}`}
        role="dialog"
        aria-hidden={!mobileOpen}
      >
        <div className="aito-mobile-sheet-header">
          <span className="aito-mobile-sheet-title">{config.operation}</span>
          <button
            type="button"
            className="aito-mobile-sheet-close"
            onClick={() => setMobileOpen(false)}
            aria-label="Close prediction panel"
          >
            ×
          </button>
        </div>
        <div className="aito-mobile-sheet-body">
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
          {body}
          {cta}
        </div>
      </div>
    </>
  );
}

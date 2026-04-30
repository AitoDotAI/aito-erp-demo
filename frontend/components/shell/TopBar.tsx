"use client";

import TenantSwitcher from "./TenantSwitcher";
import { NAV_OPEN_EVENT } from "./Nav";

interface TopBarProps {
  title: string;
  subtitle?: string;
  breadcrumb?: string;
  kpis?: Array<{ icon: string; label: string }>;
  live?: boolean;
}

export default function TopBar({ title, subtitle, breadcrumb, kpis, live }: TopBarProps) {
  /** Open the side nav drawer on mobile — Nav listens for this event
   *  on window. Decoupled this way so TopBar doesn't have to thread a
   *  setter through context. */
  const openNav = () => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event(NAV_OPEN_EVENT));
    }
  };

  return (
    <div className="topbar">
      <div className="topbar-left">
        {/* Mobile hamburger — visible only at ≤ 768px (CSS hides on desktop) */}
        <button
          type="button"
          className="topbar-hamburger"
          onClick={openNav}
          aria-label="Open navigation"
        >
          <span aria-hidden="true">☰</span>
        </button>
        {breadcrumb && (
          <>
            <span className="topbar-sub">{breadcrumb}</span>
            <span className="topbar-sep">&rsaquo;</span>
          </>
        )}
        <span className="topbar-title">{title}</span>
        {subtitle && (
          <>
            <span className="topbar-sep">&rsaquo;</span>
            <span className="topbar-sub">{subtitle}</span>
          </>
        )}
      </div>
      <div className="topbar-right">
        {live && (
          <span className="topbar-live">
            <span className="topbar-live-dot" />
            Live
          </span>
        )}
        {kpis?.map((kpi, i) => (
          <span className="topbar-kpi" key={i}>
            {kpi.icon} {kpi.label}
          </span>
        ))}
        <TenantSwitcher />
      </div>
    </div>
  );
}

"use client";

import TenantSwitcher from "./TenantSwitcher";

interface TopBarProps {
  title: string;
  subtitle?: string;
  breadcrumb?: string;
  kpis?: Array<{ icon: string; label: string }>;
  live?: boolean;
}

export default function TopBar({ title, subtitle, breadcrumb, kpis, live }: TopBarProps) {
  return (
    <div className="topbar">
      <div className="topbar-left">
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

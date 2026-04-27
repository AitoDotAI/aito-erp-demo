"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect, useMemo } from "react";
import { useTenant } from "@/lib/tenant-context";

interface NavItem {
  label: string;
  href: string;
  badge?: number;
  badgeRed?: boolean;
}

interface NavSection {
  header: string;
  emoji: string;
  items: NavItem[];
}

/**
 * Sidebar matches the aito-demo NavBar pattern:
 *   - Aito logo at the top, click goes home
 *   - Section headers with emoji + uppercase label
 *   - Active item: orange accent (--aito-accent) on left border + text
 *   - Collapsible to 56px (just keeps emojis + initial letters)
 *   - "Try Aito" CTA at the bottom (the Aito-demo signup)
 */
const SECTIONS: NavSection[] = [
  {
    header: "Procurement",
    emoji: "\u{1F4DD}",
    items: [
      { label: "PO Queue", href: "/po-queue", badge: 14 },
      { label: "Smart Entry", href: "/smart-entry" },
      { label: "Approval Routing", href: "/approval", badge: 6 },
    ],
  },
  {
    header: "Intelligence",
    emoji: "\u{1F50D}",
    items: [
      { label: "Anomaly Detection", href: "/anomalies", badge: 3, badgeRed: true },
      { label: "Supplier Intel", href: "/supplier" },
      { label: "Rule Mining", href: "/rules" },
    ],
  },
  {
    header: "Product",
    emoji: "\u{1F4E6}",
    items: [
      { label: "Catalog Intelligence", href: "/catalog", badge: 69, badgeRed: true },
      { label: "Price Intelligence", href: "/pricing" },
      { label: "Demand Forecast", href: "/demand" },
      { label: "Inventory Intelligence", href: "/inventory", badge: 2, badgeRed: true },
      { label: "Recommendations", href: "/recommendations" },
    ],
  },
  {
    header: "Operations",
    emoji: "\u{1F465}",
    items: [
      { label: "Project Portfolio", href: "/projects" },
      { label: "Utilization", href: "/utilization" },
    ],
  },
  {
    header: "Overview",
    emoji: "\u{1F4CA}",
    items: [
      { label: "Automation Overview", href: "/overview" },
    ],
  },
];

export default function Nav() {
  const pathname = usePathname();
  const { isVisible, tenant } = useTenant();
  const [collapsed, setCollapsed] = useState(false);

  // Filter sections + items by the current tenant. Empty sections drop out.
  const sections = useMemo(() => {
    return SECTIONS
      .map((s) => ({ ...s, items: s.items.filter((i) => isVisible(i.href)) }))
      .filter((s) => s.items.length > 0);
  }, [isVisible]);

  // Persist collapsed preference (matches aito-demo behaviour)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = localStorage.getItem("sidebarCollapsed") === "true";
    setCollapsed(stored);
  }, []);

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        localStorage.setItem("sidebarCollapsed", String(next));
      }
      return next;
    });
  };

  const isActive = (href: string) => {
    if (href === "/po-queue" && (pathname === "/" || pathname === "/po-queue" || pathname === "/po-queue/")) return true;
    return pathname === href || pathname === href + "/";
  };

  return (
    <aside className={`NavBar__sidebar${collapsed ? " NavBar__sidebar--collapsed" : ""}`}>
      <div className="NavBar__sidebarTop">
        <div className="NavBar__logoRow">
          <Link href="/po-queue" className="NavBar__logoLink" aria-label="Predictive ERP home">
            <img
              src="/assets/predictive-erp-icon.svg"
              alt=""
              className="NavBar__logoIcon"
              aria-hidden="true"
            />
            {!collapsed && (
              <span className="NavBar__logoText">
                <span className="NavBar__logoTitle">Predictive ERP</span>
                <span className="NavBar__logoSub">Powered by Aito.ai</span>
              </span>
            )}
          </Link>
          <button
            className="NavBar__collapseBtn"
            onClick={toggle}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? "›" : "‹"}
          </button>
        </div>

        {!collapsed && (
          <div className="NavBar__brandTag">
            {tenant.name}{" "}
            <span className="NavBar__brandTagDim">· {tenant.tagline}</span>
          </div>
        )}

        <nav className="NavBar__sidebarNav">
          {sections.map((section) => (
            <div className="NavBar__section" key={section.header}>
              <div className="NavBar__sectionHeader">
                <span className="NavBar__sectionEmoji" aria-hidden="true">{section.emoji}</span>
                {!collapsed && (
                  <span className="NavBar__sectionLabel">{section.header}</span>
                )}
              </div>
              {section.items.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`NavBar__menuItem${isActive(item.href) ? " NavBar__menuItem--active" : ""}`}
                  title={collapsed ? item.label : undefined}
                >
                  {collapsed ? (
                    <span className="NavBar__menuInitial">{item.label.charAt(0)}</span>
                  ) : (
                    <>
                      <span className="NavBar__menuLabel">{item.label}</span>
                      {item.badge != null && (
                        <span className={`NavBar__menuBadge${item.badgeRed ? " NavBar__menuBadge--red" : ""}`}>
                          {item.badge}
                        </span>
                      )}
                    </>
                  )}
                </Link>
              ))}
            </div>
          ))}
        </nav>
      </div>

      <div className="NavBar__signupCTA">
        <a
          href="https://aito.ai"
          target="_blank"
          rel="noopener noreferrer"
          className="NavBar__signupLink"
          title="Try Aito"
        >
          {collapsed ? (
            <span aria-hidden="true">→</span>
          ) : (
            <>
              <span className="NavBar__signupText">Try Aito</span>
              <span className="NavBar__signupArrow" aria-hidden="true">→</span>
            </>
          )}
        </a>
      </div>
    </aside>
  );
}

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
 *   - The "Try Aito" CTA lives in the right-rail AitoPanel — see
 *     aito-demo/src/app/components/ContextPanel.{js,css} for the
 *     pattern this mirrors.
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

/** Event the TopBar's mobile hamburger dispatches to open the drawer.
 *  Decoupled this way so Nav doesn't need to know about TopBar — the
 *  same Nav instance works for any caller that fires the event. */
export const NAV_OPEN_EVENT = "aito:open-nav";

export default function Nav() {
  const pathname = usePathname();
  const { isVisible, tenant } = useTenant();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

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

  // Listen for the TopBar hamburger's open event.
  useEffect(() => {
    const handler = () => setMobileOpen(true);
    window.addEventListener(NAV_OPEN_EVENT, handler);
    return () => window.removeEventListener(NAV_OPEN_EVENT, handler);
  }, []);

  // Close the mobile drawer whenever the route changes — tapping a
  // nav item should land you on the new page, not stuck in the open
  // drawer with the page rendered behind it.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

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
    <>
      {/* Mobile backdrop — tap to close the drawer. Only visible when
          mobileOpen is true (CSS hides the element on desktop). */}
      {mobileOpen && (
        <div
          className="NavBar__mobileOverlay"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={[
          "NavBar__sidebar",
          collapsed ? "NavBar__sidebar--collapsed" : "",
          mobileOpen ? "NavBar__sidebar--mobile-open" : "",
        ].filter(Boolean).join(" ")}
      >
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

      {/* "Try Aito" CTA used to live here; moved to the right-rail
          AitoPanel to match aito-demo's ContextPanel placement. */}
    </aside>
    </>
  );
}

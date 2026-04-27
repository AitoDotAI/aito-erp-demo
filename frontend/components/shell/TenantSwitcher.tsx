"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { TENANTS } from "@/lib/tenants";
import { useTenant } from "@/lib/tenant-context";

/** Compact dropdown shown in the TopBar — lets a sales conversation
 * switch the demo's audience profile without reloading. */
export default function TenantSwitcher() {
  const { tenant, setTenantId } = useTenant();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!open) return;
    const handle = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  return (
    <div className="tenant-switcher" ref={ref}>
      <button
        type="button"
        className="tenant-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        title={tenant.audience}
      >
        <span
          className="tenant-dot"
          style={{ background: tenant.accent }}
          aria-hidden="true"
        />
        <span className="tenant-name">{tenant.name}</span>
        <span className="tenant-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="tenant-menu" role="listbox">
          <li className="tenant-menu-label">Demo profile</li>
          {TENANTS.map((t) => {
            const active = t.id === tenant.id;
            return (
              <li
                key={t.id}
                role="option"
                aria-selected={active}
                className={`tenant-menu-item${active ? " active" : ""}`}
                onClick={() => {
                  setTenantId(t.id);
                  setOpen(false);
                  // If the current view is now hidden for the new
                  // profile, hop to that profile's default route.
                  if (
                    typeof window !== "undefined" &&
                    t.hideRoutes.some((r) =>
                      window.location.pathname.startsWith(r),
                    )
                  ) {
                    router.push(t.defaultRoute);
                  }
                }}
              >
                <span
                  className="tenant-dot"
                  style={{ background: t.accent }}
                  aria-hidden="true"
                />
                <span className="tenant-menu-text">
                  <span className="tenant-menu-name">{t.name}</span>
                  <span className="tenant-menu-sub">{t.tagline}</span>
                  <span className="tenant-menu-aud">{t.audience}</span>
                </span>
                {active && <span className="tenant-check">✓</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

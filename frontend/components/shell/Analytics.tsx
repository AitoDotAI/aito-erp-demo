"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { initAnalytics, trackPage } from "@/lib/analytics";

/**
 * Initialize Segment on first mount and emit a `page()` event on
 * every client-side route change. The Next.js App Router doesn't
 * fire a real navigation for SPA route changes, so without this
 * only the initial landing page would show up in Segment.
 *
 * Mirrors aito-accounting-demo's component verbatim so all three
 * Aito demo properties report the same way.
 */
export default function Analytics() {
  const pathname = usePathname();

  useEffect(() => {
    initAnalytics();
  }, []);

  useEffect(() => {
    if (!pathname) return;
    trackPage(pathname);
  }, [pathname]);

  return null;
}

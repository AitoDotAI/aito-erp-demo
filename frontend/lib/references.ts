/**
 * GitHub source + use-case-doc references for the Aito side panel.
 *
 * Mirrors the pattern aito-demo and aito-accounting-demo use: every
 * page's right-rail panel gets two extra links — one to the source
 * file backing that page, and one to the prose use-case overview in
 * `docs/use-cases/`. CTOs reading the panel can step from "this is
 * what's on screen" to "this is the code" to "this is why we built
 * it" without leaving the link rail.
 */

const REPO = "https://github.com/AitoDotAI/aito-erp-demo";
const BRANCH = "main";

export interface PanelLink {
  label: string;
  url: string;
  kind?: "doc" | "github" | "external";
}

interface PageRef {
  /** Slug of the use-case doc under `docs/use-cases/`, e.g. "01-po-queue".
   *  Pass `null` to skip the use-case link (e.g. for the landing page). */
  useCase?: string | null;
  /** Path under repo root to the primary backend source file, e.g.
   *  "src/po_service.py". Use the service module for service-backed
   *  views; use the page.tsx for UI-only views. */
  source?: string | null;
}

/** Return the standard `Use case overview` + `Source code` links for
 *  a page. Order matches the existing accounting-demo convention:
 *  use-case first (the conceptual context), source second (the code).
 */
export function referenceLinks({ useCase, source }: PageRef): PanelLink[] {
  const out: PanelLink[] = [];
  if (useCase) {
    out.push({
      label: "Use case overview",
      url: `${REPO}/blob/${BRANCH}/docs/use-cases/${useCase}.md`,
      kind: "doc",
    });
  }
  if (source) {
    out.push({
      label: "Source code",
      url: `${REPO}/blob/${BRANCH}/${source}`,
      kind: "github",
    });
  }
  return out;
}

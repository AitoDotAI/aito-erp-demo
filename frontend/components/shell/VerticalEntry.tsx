"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTenant } from "@/lib/tenant-context";
import { TenantId } from "@/lib/tenants";

export interface VerticalFeature {
  /** Human-readable name; matches the side-nav label. */
  label: string;
  /** Route to push when the card is tapped. */
  href: string;
  /** One-sentence pitch shown under the label. */
  pitch: string;
  /** Tiny stat or claim shown as a chip. */
  stat?: string;
}

export interface VerticalEntryConfig {
  /** Tenant id this vertical maps to — set on the persisted profile
   *  so subsequent navigation goes to the right Aito DB. */
  tenant: TenantId;
  /** Brand accent for the hero pill. */
  accent: string;
  /** Big headline ("Predictive ERP for ..."). */
  headline: string;
  /** Sub-headline — the three-verb summary. */
  subheadline: string;
  /** Two-sentence framing of the vertical's pain + Aito's answer. */
  framing: string;
  /** Three curated "start here" features — the hero set for this
   *  vertical. Order matters: first one is the hero. */
  hero: VerticalFeature[];
  /** Other features available in this profile. Rendered as a
   *  smaller secondary list. */
  supporting: VerticalFeature[];
  /** Where the bottom CTA routes (typically the first hero href). */
  defaultRoute: string;
  /** Concrete buyer hint for sales context (e.g. "Lemonsoft, IFS"). */
  audienceHint: string;
}

/**
 * Vertical entry page — three of these (industrial / retail /
 * services) live alongside the persona picker on `/`. They exist
 * because the CPO criticism is right: persona switching alone reads
 * as cosmetic, but a buyer thinks of these as different products.
 *
 * What this page does differently from the home picker:
 *   - One vertical, framed unambiguously: "Predictive ERP for X"
 *   - Three hero features called out as the *order* a buyer in this
 *     vertical should explore them in
 *   - Sales can drop a CTO straight into `erp.aito.ai/industrial`
 *     with confidence about what they'll see first
 *
 * The route side-effect: tenant id is written to localStorage so
 * subsequent navigation (clicking a feature card) opens the matching
 * Aito DB. We don't auto-redirect — visitors should land here, read
 * the framing, then click. Auto-redirecting would defeat the purpose.
 */
export default function VerticalEntry({ config }: { config: VerticalEntryConfig }) {
  const router = useRouter();
  const { setTenantId } = useTenant();

  // Pin the tenant on mount so any subsequent click on a feature
  // card opens the right Aito DB. (We don't redirect — the page
  // *is* the value here.)
  useEffect(() => {
    setTenantId(config.tenant);
  }, [config.tenant, setTenantId]);

  const open = (href: string) => {
    setTenantId(config.tenant);
    router.push(href);
  };

  return (
    <div className="vertical-entry">
      <div className="vertical-entry-inner">
        <header className="vertical-entry-hero">
          <Link href="/" className="vertical-entry-back">
            ← All three profiles
          </Link>
          <span
            className="vertical-entry-pill"
            style={{ borderColor: config.accent, color: config.accent }}
          >
            {config.audienceHint}
          </span>
          <h1 className="vertical-entry-headline">{config.headline}</h1>
          <p className="vertical-entry-sub">{config.subheadline}</p>
          <p className="vertical-entry-framing">{config.framing}</p>
        </header>

        <section className="vertical-entry-hero-grid">
          <div className="vertical-entry-section-label">
            Start here — in this order
          </div>
          <div className="vertical-entry-cards">
            {config.hero.map((f, i) => (
              <button
                key={f.href}
                type="button"
                className="vertical-entry-card"
                style={{ borderTop: `3px solid ${config.accent}` }}
                onClick={() => open(f.href)}
              >
                <div className="vertical-entry-card-number">{i + 1}</div>
                <div className="vertical-entry-card-name">{f.label}</div>
                <div className="vertical-entry-card-pitch">{f.pitch}</div>
                {f.stat && (
                  <div
                    className="vertical-entry-card-stat"
                    style={{ color: config.accent }}
                  >
                    {f.stat}
                  </div>
                )}
              </button>
            ))}
          </div>
        </section>

        {config.supporting.length > 0 && (
          <section className="vertical-entry-supporting">
            <div className="vertical-entry-section-label">Plus</div>
            <ul className="vertical-entry-list">
              {config.supporting.map((f) => (
                <li key={f.href}>
                  <Link href={f.href} onClick={() => setTenantId(config.tenant)}>
                    <strong>{f.label}</strong>
                    <span className="vertical-entry-list-pitch">{f.pitch}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="vertical-entry-cta-row">
          <button
            type="button"
            className="vertical-entry-cta"
            style={{ background: config.accent }}
            onClick={() => open(config.defaultRoute)}
          >
            Open the demo →
          </button>
        </div>
      </div>
    </div>
  );
}

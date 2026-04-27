"use client";

import { useRouter } from "next/navigation";
import { TENANTS, TenantProfile } from "@/lib/tenants";
import { useTenant } from "@/lib/tenant-context";

/** Per-persona pitch shown on the landing tiles. Hardcoded marketing
 * copy rather than computed from the persona spec — these strings
 * exist to convince a first-time visitor to click in, not to track
 * runtime data. */
interface TenantPitch {
  id: string;
  hero: string;                // headline that appears below the brand name
  whatYoullSee: string[];      // 3-4 bulleted highlights
  sampleSuppliers: string[];   // recognisable names from the persona's data
  audienceHint: string;        // for whom this persona is the right fit
}

const PITCHES: Record<string, TenantPitch> = {
  metsa: {
    id: "metsa",
    hero: "Industrial maintenance & construction",
    whatYoullSee: [
      "PO Queue: 1,983 POs auto-coded with predicted cost-centre and approver",
      "Project Portfolio: success forecasts for active maintenance & construction work",
      "Staffing simulator: swap a person on a project, see P(success) move",
      "Anomaly detection on PO coding mistakes",
    ],
    sampleSuppliers: ["Wärtsilä", "ABB", "Caverion", "NCC", "Konecranes", "Neste"],
    audienceHint:
      "If you're evaluating an ERP for an industrial buyer (Lemonsoft, IFS, Epicor) — start here.",
  },
  aurora: {
    id: "aurora",
    hero: "Multi-channel retail · 24 stores",
    whatYoullSee: [
      "Recommendations: cross-sell & similar products via _search + _match",
      "Demand Forecast: SKU-level seasonality across 1,800 products",
      "Inventory Intelligence: predicted stockouts and tied-capital flags",
      "Catalog Intelligence: missing attributes filled in by Aito",
    ],
    sampleSuppliers: ["Valio", "Marimekko", "Iittala", "L'Oréal", "Verkkokauppa", "Posti"],
    audienceHint:
      "If you're evaluating an ERP for a retail buyer (Oscar Software, ERPly, Lightspeed) — start here.",
  },
  studio: {
    id: "studio",
    hero: "Professional services · 42 consultants",
    whatYoullSee: [
      "Project Portfolio: success forecasts for 55 active client engagements",
      "Utilization & Capacity: per-consultant load with at-risk allocation flagged",
      "What-if forecast: Aito predicts role + allocation for any person × project type",
      "Smart Entry on consultant-level vendor invoices (AWS, Adobe, Figma)",
    ],
    sampleSuppliers: ["Adobe", "AWS", "Microsoft", "Figma", "Slack", "Eficode"],
    audienceHint:
      "If you're evaluating a horizontal ERP for a services firm (Severa, Workday, Visma Severa) — start here.",
  },
};


export default function LandingPage() {
  const router = useRouter();
  const { setTenantId } = useTenant();

  const enter = (tenant: TenantProfile) => {
    setTenantId(tenant.id);
    router.push(tenant.defaultRoute);
  };

  return (
    <div className="landing">
      <div className="landing-inner">
        <header className="landing-hero">
          <div className="landing-brand">
            <img
              src="/assets/predictive-erp-icon.svg"
              alt=""
              className="landing-logo-icon"
              aria-hidden="true"
            />
            <div className="landing-brand-text">
              <span className="landing-brand-title">Predictive ERP</span>
              <span className="landing-brand-sub">Powered by Aito.ai</span>
            </div>
          </div>
          <h1 className="landing-headline">
            One ERP, three audiences, zero model training.
          </h1>
          <p className="landing-sub">
            A reference demo of <strong>Aito.ai</strong>'s predictive database
            applied to ERP workflows. Pick the tenant whose shape matches your
            world — same code, same Aito API, but the data, vocabulary, and
            views are tailored to that audience.
          </p>
        </header>

        <div className="landing-tiles">
          {TENANTS.map((t) => {
            const pitch = PITCHES[t.id];
            if (!pitch) return null;
            return (
              <button
                key={t.id}
                type="button"
                className="landing-tile"
                style={{
                  borderTop: `4px solid ${t.accent}`,
                }}
                onClick={() => enter(t)}
              >
                <div
                  className="landing-tile-accent"
                  style={{ background: t.accent }}
                  aria-hidden="true"
                />
                <div className="landing-tile-name">{t.name}</div>
                <div className="landing-tile-tagline">{pitch.hero}</div>

                <div className="landing-tile-audience">{pitch.audienceHint}</div>

                <ul className="landing-tile-list">
                  {pitch.whatYoullSee.map((point, i) => (
                    <li key={i}>{point}</li>
                  ))}
                </ul>

                <div className="landing-tile-suppliers">
                  <div className="landing-tile-label">In this dataset</div>
                  <div className="landing-tile-pills">
                    {pitch.sampleSuppliers.map((s) => (
                      <span
                        key={s}
                        className="landing-tile-pill"
                        style={{ borderColor: t.accent, color: t.accent }}
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </div>

                <div
                  className="landing-tile-cta"
                  style={{ background: t.accent }}
                >
                  Open this demo →
                </div>
              </button>
            );
          })}
        </div>

        <footer className="landing-foot">
          <div className="landing-foot-row">
            <span>
              <strong>Built on Aito.ai</strong> — a predictive database that
              answers <code>_predict</code>, <code>_relate</code>,{" "}
              <code>_match</code>, and <code>_search</code> queries directly,
              with no model training and no MLOps pipeline.
            </span>
          </div>
          <div className="landing-foot-row landing-foot-meta">
            <a href="https://aito.ai" target="_blank" rel="noopener noreferrer">
              aito.ai →
            </a>
            <a
              href="https://github.com/AitoDotAI"
              target="_blank"
              rel="noopener noreferrer"
            >
              source on GitHub →
            </a>
            <span className="landing-foot-disclaimer">
              All data shown is fictional · no PII · API keys are read-only
            </span>
          </div>
        </footer>
      </div>
    </div>
  );
}

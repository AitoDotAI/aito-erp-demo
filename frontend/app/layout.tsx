import "./globals.css";
import Script from "next/script";
import { TenantProvider } from "@/lib/tenant-context";
import Analytics from "@/components/shell/Analytics";

export const metadata = {
  title: "Predictive ERP — by Aito",
  description:
    "Open-source reference: 11 procurement workflows powered by Aito.ai's predictive database. " +
    "PO coding, approval routing, anomaly detection, demand forecast, inventory replenishment — " +
    "no model training, no MLOps.",
  icons: {
    icon: "/assets/aito-favicon.svg",
  },
};

// Without this, mobile browsers fall back to the legacy 980px viewport
// and shrink-to-fit, defeating every `@media (max-width: 768px)` rule
// in globals.css. Same setting aito-demo's index.html uses.
export const viewport = {
  width: "device-width",
  initialScale: 1,
};

// Same GA4 property as the other Aito demos so events land in the same
// view. Hardcoded literal — measurement ID is public anyway (visible in
// the deployed bundle since GA4 was launched).
const GA_MEASUREMENT_ID = "G-FDTBRCMZWJ";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <TenantProvider>
          <div className="app">
            {children}
          </div>
          {/* Amplitude page-view emit on every client-side route change */}
          <Analytics />
        </TenantProvider>

        {/* Google Analytics 4 — same property as the other Aito demos.
            `afterInteractive` keeps the script off the critical path. */}
        <Script
          src={`https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`}
          strategy="afterInteractive"
        />
        <Script id="ga-init" strategy="afterInteractive">
          {`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', '${GA_MEASUREMENT_ID}', {
              anonymize_ip: true,
              cookie_expires: 0,
            });
          `}
        </Script>
      </body>
    </html>
  );
}

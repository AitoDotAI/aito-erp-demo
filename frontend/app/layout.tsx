import "./globals.css";
import { TenantProvider } from "@/lib/tenant-context";
import LatencyPill from "@/components/shell/LatencyPill";

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

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <TenantProvider>
          <div className="app">
            {children}
          </div>
          <LatencyPill />
        </TenantProvider>
      </body>
    </html>
  );
}

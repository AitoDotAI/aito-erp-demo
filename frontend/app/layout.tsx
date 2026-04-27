import "./globals.css";
import { TenantProvider } from "@/lib/tenant-context";

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

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <TenantProvider>
          <div className="app">
            {children}
          </div>
        </TenantProvider>
      </body>
    </html>
  );
}

import VerticalEntry, {
  type VerticalEntryConfig,
} from "@/components/shell/VerticalEntry";
import { getTenant } from "@/lib/tenants";

export const metadata = {
  title: "Predictive ERP for Multi-Channel Retail — Aito",
  description:
    "Forecast SKU demand, optimize inventory, run cross-sell live. " +
    "Demo runs on 3.2K SKUs, 8K shopping baskets and 22K months of product sales.",
};

const config: VerticalEntryConfig = {
  tenant: "aurora",
  accent: getTenant("aurora").accent,
  headline: "Predictive ERP for multi-channel retail.",
  subheadline:
    "Forecast demand · optimize inventory · run cross-sell on the same data.",
  framing:
    "Retail buyers care about three things in parallel: what's selling, what's about " +
    "to stock out, and what to recommend at the checkout. Aurora's profile loads " +
    "3.2K SKUs across Beauty / Fashion / Electronics / Groceries, 8K shopping " +
    "baskets and 22K months of product sales — and every view reports how it " +
    "measured against the plain rule a buyer already has.",
  audienceHint: "For Oscar Software / ERPly / Lightspeed-style buyers",
  hero: [
    {
      label: "Demand Forecast",
      href: "/demand",
      pitch:
        "_estimate forecasts six held-out months, shown next to what actually " +
        "sold, last year and the trailing reorder rule.",
      stat: "22% less error than the reorder rule",
    },
    {
      label: "Inventory Intelligence",
      href: "/inventory",
      pitch:
        "Will stock plus deliveries cover the lead time? Asked with Aito's " +
        "forecast and with the reorder rule, each checked against what sold.",
    },
    {
      label: "Recommendations",
      href: "/recommendations",
      pitch:
        "Bought together: one _relate over baskets, ranked by lift, with the " +
        "basket counts behind every ratio.",
      stat: "at parity with counting",
    },
  ],
  supporting: [
    {
      label: "Catalog Intelligence",
      href: "/catalog",
      pitch: "Missing product attributes filled in by Aito.",
    },
    {
      label: "Price Intelligence",
      href: "/pricing",
      pitch: "Fair-price estimation + quote scoring against history.",
    },
    {
      label: "PO Queue",
      href: "/po-queue",
      pitch: "Auto-routed POs from the supply side of the business.",
    },
    {
      label: "Anomaly Detection",
      href: "/anomalies",
      pitch: "Surfaces unusual transactions across all channels.",
    },
  ],
  defaultRoute: "/demand",
};

export default function RetailEntryPage() {
  return <VerticalEntry config={config} />;
}

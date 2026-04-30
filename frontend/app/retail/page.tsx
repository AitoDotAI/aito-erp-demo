import VerticalEntry, {
  type VerticalEntryConfig,
} from "@/components/shell/VerticalEntry";
import { getTenant } from "@/lib/tenants";

export const metadata = {
  title: "Predictive ERP for Multi-Channel Retail — Aito",
  description:
    "Forecast SKU demand, optimize inventory, run cross-sell live. " +
    "Demo runs on 3.2K SKUs, 18K orders, 6.7K browsing impressions.",
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
    "3.2K SKUs across Beauty / Fashion / Electronics / Groceries, 18K historical " +
    "orders, and 6.7K browsing impressions — enough density to make every prediction " +
    "credible without faking the volume.",
  audienceHint: "For Oscar Software / ERPly / Lightspeed-style buyers",
  hero: [
    {
      label: "Demand Forecast",
      href: "/demand",
      pitch:
        "Per-SKU month-ahead forecast via _predict + _search aggregation. " +
        "Picks up seasonality without a model file.",
      stat: "549 SKUs forecast",
    },
    {
      label: "Inventory Intelligence",
      href: "/inventory",
      pitch:
        "Days-of-supply + reorder recommendations driven by the demand forecast. " +
        "Stockout flags surface before they bite.",
      stat: "2 critical now",
    },
    {
      label: "Recommendations",
      href: "/recommendations",
      pitch:
        "Cross-sell via _recommend with goal:{clicked:true} on the impressions " +
        "table. One call, full product row, sub-second.",
      stat: "P(click) calibrated",
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

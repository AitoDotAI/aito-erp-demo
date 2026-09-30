import VerticalEntry, {
  type VerticalEntryConfig,
} from "@/components/shell/VerticalEntry";
import { getTenant } from "@/lib/tenants";

export const metadata = {
  title: "Predictive ERP for Industrial Maintenance — Aito",
  description:
    "Auto-route POs, forecast project success, catch coding anomalies. " +
    "Live demo with 3.3K purchase orders and 238 maintenance / construction projects.",
};

const config: VerticalEntryConfig = {
  tenant: "metsa",
  accent: getTenant("metsa").accent,
  headline: "Predictive ERP for industrial maintenance.",
  subheadline:
    "Auto-route POs · forecast project success · catch coding anomalies before close.",
  framing:
    "Industrial buyers spend their day routing POs from a long tail of suppliers " +
    "(Wärtsilä, ABB, Caverion, NCC) and worrying about projects that slip. " +
    "The demo runs on 3.3K POs and 238 projects so you can see Aito's predictions " +
    "compose across the buying-and-building lifecycle, not just isolated cards.",
  audienceHint: "For Lemonsoft / IFS / Epicor-style buyers",
  hero: [
    {
      label: "PO Queue",
      href: "/po-queue",
      pitch:
        "Aito codes account, cost centre and approver on every PO; the weakest " +
        "of the three decides whether a person reviews it.",
    },
    {
      label: "Anomaly Detection",
      href: "/anomalies",
      pitch:
        "Inverse _predict: a coding the history finds unlikely surfaces " +
        "before it hits the close.",
    },
    {
      label: "Project Portfolio",
      href: "/projects",
      pitch:
        "Predicted success per active maintenance & construction project, with " +
        "the factors that move outcomes mined from completed-project history.",
      stat: "18 in flight · 220 completed",
    },
  ],
  supporting: [
    {
      label: "Smart Entry",
      href: "/smart-entry",
      pitch: "One supplier pick fills 4 fields, each with its own confidence.",
    },
    {
      label: "Approval Routing",
      href: "/approval",
      pitch: "Predicted approver + escalation level on every PO.",
    },
    {
      label: "Supplier Intel",
      href: "/supplier",
      pitch: "Spend overview + delivery risk via _relate.",
    },
    {
      label: "Rule Mining",
      href: "/rules",
      pitch: "Patterns Aito discovered in your routing decisions.",
    },
  ],
  defaultRoute: "/po-queue",
};

export default function IndustrialEntryPage() {
  return <VerticalEntry config={config} />;
}

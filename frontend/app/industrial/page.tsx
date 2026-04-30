import VerticalEntry, {
  type VerticalEntryConfig,
} from "@/components/shell/VerticalEntry";
import { getTenant } from "@/lib/tenants";

export const metadata = {
  title: "Predictive ERP for Industrial Maintenance — Aito",
  description:
    "Auto-route POs, forecast project success, catch coding anomalies. " +
    "Live demo with 3.2k purchase orders and 285 maintenance / construction projects.",
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
    "The demo runs on 3.2K POs and 285 projects so you can see Aito's predictions " +
    "compose across the buying-and-building lifecycle, not just isolated cards.",
  audienceHint: "For Lemonsoft / IFS / Epicor-style buyers",
  hero: [
    {
      label: "PO Queue",
      href: "/po-queue",
      pitch:
        "47 POs received today; Aito auto-codes account, cost-centre, and approver. " +
        "71% land without anyone touching them.",
      stat: "82% auto-coded MTD",
    },
    {
      label: "Anomaly Detection",
      href: "/anomalies",
      pitch:
        "_evaluate scores combinations against history. Mis-coded POs surface " +
        "before they hit the close.",
      stat: "3 flagged this week",
    },
    {
      label: "Project Portfolio",
      href: "/projects",
      pitch:
        "Predicted success per active maintenance & construction project, with " +
        "people-as-staffing-factors mined from completed-project history.",
      stat: "65 active projects",
    },
  ],
  supporting: [
    {
      label: "Smart Entry",
      href: "/smart-entry",
      pitch: "One supplier pick fills 5 fields in one round-trip.",
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

import VerticalEntry, {
  type VerticalEntryConfig,
} from "@/components/shell/VerticalEntry";
import { getTenant } from "@/lib/tenants";

export const metadata = {
  title: "Predictive ERP for Professional Services — Aito",
  description:
    "Forecast project success, plan utilization, code SaaS invoices automatically. " +
    "Demo runs on 435 client engagements and 2.1K consultant assignments.",
};

const config: VerticalEntryConfig = {
  tenant: "studio",
  accent: getTenant("studio").accent,
  headline: "Predictive ERP for professional services.",
  subheadline:
    "Forecast project success · plan capacity · code SaaS invoices on autopilot.",
  framing:
    "Services firms run on people: who's billable, which engagements are at risk, " +
    "and whether the bench has room for the next project. Studio's profile loads " +
    "435 engagements and 2.1K assignments so the project-success forecast and " +
    "utilization view sit on real density — not stubbed numbers.",
  audienceHint: "For Severa / Workday / Visma Severa-style buyers",
  hero: [
    {
      label: "Project Portfolio",
      href: "/projects",
      pitch:
        "Predicted success for every active engagement, plus people-as-staffing-" +
        "factors mined from completed-project history via _relate.",
      stat: "55 active engagements",
    },
    {
      label: "Utilization & Capacity",
      href: "/utilization",
      pitch:
        "Per-consultant load with at-risk allocation flagged. " +
        "What-if: pick a person and project type, get role + allocation.",
      stat: "42 consultants",
    },
    {
      label: "Smart Entry",
      href: "/smart-entry",
      pitch:
        "Vendor invoices (Adobe, AWS, Figma) auto-coded — one supplier pick fills " +
        "cost-centre, account, project, approver in one round-trip.",
      stat: "5 fields per pick",
    },
  ],
  supporting: [
    {
      label: "PO Queue",
      href: "/po-queue",
      pitch: "Live queue of incoming SaaS + consultant invoices.",
    },
    {
      label: "Anomaly Detection",
      href: "/anomalies",
      pitch: "Catches unusual SaaS spend before it slips into close.",
    },
    {
      label: "Supplier Intel",
      href: "/supplier",
      pitch: "Spend overview across software vendors and contractors.",
    },
  ],
  defaultRoute: "/projects",
};

export default function ServicesEntryPage() {
  return <VerticalEntry config={config} />;
}

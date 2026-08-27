import type { LucideIcon } from "lucide-react";
import { BarChart3, CreditCard, GitCompare, History, LayoutDashboard, ScanSearch } from "lucide-react";

export interface NavLink {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_LINKS: NavLink[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/dashboard/upload", label: "Scan a letter", icon: ScanSearch },
  { href: "/dashboard/history", label: "History", icon: History },
  { href: "/dashboard/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/dashboard/compare", label: "Compare offers", icon: GitCompare },
  { href: "/dashboard/plans", label: "Plans", icon: CreditCard },
];

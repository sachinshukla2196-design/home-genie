import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Truck } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import VendorDispatch from "@/pages/vendor/VendorDispatch";
import VendorReturns from "@/pages/vendor/VendorReturns";

/** Shipping & Returns: dispatch with tracking, and return requests. Both lists are the existing pages. */
export default function VendorShipping() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const tab = params.get("tab") === "returns" ? "returns" : "dispatch";
  const tabs = [["dispatch", "vx.nav.dispatch", "/vendor/shipping"], ["returns", "vx.nav.returns", "/vendor/shipping?tab=returns"]];
  return (
    <div className="space-y-6" data-testid="vendor-shipping">
      <PageHeader title={t("vx.nav.shipping")} subtitle={t("vx.ship.sub")} icon={Truck} />
      <nav className="flex flex-wrap gap-2" aria-label={t("vx.nav.shipping")}>
        {tabs.map(([k, label, to]) => (
          <Link key={k} to={to} aria-current={tab === k ? "page" : undefined} data-testid={`shipping-tab-${k}`}
            className={`rounded-full px-3.5 py-1.5 text-xs font-medium ${tab === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{t(label)}</Link>
        ))}
      </nav>
      {tab === "returns" ? <VendorReturns embedded /> : <VendorDispatch embedded />}
    </div>
  );
}

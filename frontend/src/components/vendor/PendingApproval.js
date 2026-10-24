import React from "react";
import { Link, useLocation } from "react-router-dom";
import { Hourglass } from "lucide-react";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { NAV_GROUPS } from "@/components/VendorLayout";
import { Pill } from "@/components/vendor/kit";
import { useI18n } from "@/context/I18nContext";

/** Shown inside the vendor portal in place of an approval-only page, so a Draft or pending vendor can still see the menu. */
export function PendingApproval({ vendor }) {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const status = vendor ? vendor.status : null;
  const item = NAV_GROUPS.flatMap((g) => g.items).find((i) => pathname === i.to || pathname.startsWith(i.to + "/"));
  return (
    <div className="space-y-6" data-testid="vendor-gate-page">
      <PageHeader title={item ? t(item.key) : t("vx.gate.title")} subtitle={t("vx.gate.title")} icon={item ? item.icon : Hourglass} />
      <SectionCard title={t("vx.gate.title")} icon={Hourglass} testid="vendor-gate">
        <p className="text-sm text-muted2">{t(status ? "vx.gate.body" : "vx.gate.noProfile")}</p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {status && <Pill tone="warn" testid="vendor-gate-status">{t(`vp.st.${status}`)}</Pill>}
          <Link to="/vendor/profile" className="hg-btn inline-flex h-10 items-center rounded-full px-5 text-sm font-semibold">{t("vx.gate.cta")}</Link>
        </div>
      </SectionCard>
    </div>
  );
}

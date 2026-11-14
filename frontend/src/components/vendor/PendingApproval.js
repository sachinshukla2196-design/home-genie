import React from "react";
import { Link, useLocation } from "react-router-dom";
import { Hourglass } from "lucide-react";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { NAV_GROUPS } from "@/components/VendorLayout";
import { Pill } from "@/components/vendor/kit";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";

/** Shown inside the vendor portal in place of an approval-only page, so a Draft or pending vendor can still see the menu. */
export function PendingApproval({ vendor }) {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const { user } = useAuth();
  const status = vendor ? vendor.status : null;
  const staffOff = !vendor && user?.role === "vendor_staff";      // the backend refused this staff member: access is off, not "no profile"
  const item = NAV_GROUPS.flatMap((g) => g.items).find((i) => pathname === i.to || pathname.startsWith(i.to + "/"));
  // Vendor Pillar: an applicant whose registration HOME GENIES is preparing (or has decided) follows it here; no self-edit button.
  const onboarding = vendor && (["onboarding", "ready_for_review"].includes(status) || (vendor.onboarding_path && status === "rejected"));
  if (onboarding) {
    const text = status === "rejected"
      ? `Your application was not taken forward.${vendor.rejection_reason ? " Reason: " + vendor.rejection_reason : ""} Contact HOME GENIES if you have questions.`
      : status === "ready_for_review"
        ? "Your registration is complete and waiting for final approval by HOME GENIES. Products, orders and payouts open as soon as it is approved."
        : "Thank you for applying. Our partner team is reviewing your application and completing your registration with you. Products, orders and payouts open once HOME GENIES approves it.";
    return (
      <div className="space-y-6" data-testid="vendor-gate-page">
        <PageHeader title={item ? t(item.key) : "Your application"} subtitle="Vendor registration" icon={item ? item.icon : Hourglass} />
        <SectionCard title={status === "rejected" ? "Application not approved" : "Your application is in progress"} icon={Hourglass} testid="vendor-gate">
          <p className="text-sm text-muted2" data-testid="vendor-gate-message">{text}</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Pill tone={status === "rejected" ? "bad" : "warn"} testid="vendor-gate-status">{t(`vp.st.${status}`)}</Pill>
            <span className="text-xs text-muted2">{vendor.vendor_code} · {vendor.business_name}</span>
          </div>
        </SectionCard>
      </div>
    );
  }
  return (
    <div className="space-y-6" data-testid="vendor-gate-page">
      <PageHeader title={item ? t(item.key) : t("vx.gate.title")} subtitle={t("vx.gate.title")} icon={item ? item.icon : Hourglass} />
      <SectionCard title={t(staffOff ? "vx.staff.accessOffTitle" : "vx.gate.title")} icon={Hourglass} testid="vendor-gate">
        <p className="text-sm text-muted2">{t(staffOff ? "vx.staff.accessOff" : status ? "vx.gate.body" : "vx.gate.noProfile")}</p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {status && <Pill tone="warn" testid="vendor-gate-status">{t(`vp.st.${status}`)}</Pill>}
          <Link to="/vendor/profile" className="hg-btn inline-flex h-10 items-center rounded-full px-5 text-sm font-semibold">{t("vx.gate.cta")}</Link>
        </div>
      </SectionCard>
    </div>
  );
}

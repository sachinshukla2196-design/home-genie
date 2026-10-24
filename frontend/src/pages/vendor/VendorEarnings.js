import React from "react";
import { useI18n } from "@/context/I18nContext";
import VendorFinance from "@/pages/vendor/VendorFinance";

/** Earnings & Settlements: the existing finance page (ledger, settlements, statements) under the portal's own title. */
export default function VendorEarnings() {
  const { t } = useI18n();
  return <VendorFinance title={t("vx.nav.earnings")} />;
}

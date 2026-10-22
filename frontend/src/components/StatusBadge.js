import React from "react";
import { useI18n } from "@/context/I18nContext";

export function StatusBadge({ status, size = "md" }) {
  const { t } = useI18n();
  const green = status === "green";
  const pad = size === "sm" ? "px-2.5 py-0.5 text-[11px]" : "px-3 py-1 text-xs";
  return (
    <span
      data-testid="status-badge"
      className={`inline-flex items-center gap-1.5 rounded-full font-semibold ring-1 ${pad} ${
        green ? "bg-hg-success/15 text-hg-success ring-hg-success/30" : "bg-hg-gold/15 text-hg-gold ring-hg-gold/30"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${green ? "bg-hg-success" : "bg-hg-gold"}`} />
      {green ? t("status.green") : t("status.red")}
    </span>
  );
}

import React from "react";
import { useI18n } from "@/context/I18nContext";

export function StatusBadge({ status, size = "md" }) {
  const { t } = useI18n();
  const green = status === "green";
  const pad = size === "sm" ? "px-2.5 py-0.5 text-[11px]" : "px-3 py-1 text-xs";
  return (
    <span
      data-testid="status-badge"
      className={`inline-flex items-center gap-1.5 rounded-full font-semibold ${pad} ${
        green ? "bg-brand-50 text-brand-700" : "bg-danger/10 text-danger"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${green ? "bg-brand" : "bg-danger"}`} />
      {green ? t("status.green") : t("status.red")}
    </span>
  );
}

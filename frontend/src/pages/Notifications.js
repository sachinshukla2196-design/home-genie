import React, { useEffect, useState } from "react";
import { Bell, CheckCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

export default function Notifications() {
  const { t, lang } = useI18n();
  const [items, setItems] = useState(null);

  const load = () => API.get("/notifications").then(({ data }) => setItems(data.items)).catch(() => setItems([]));
  useEffect(() => { load(); }, []);

  const readAll = async () => { await API.post("/notifications/read-all"); load(); };

  if (!items) return <Skeleton className="h-64 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.notifications")}</h1>
        {items.length > 0 && <Button onClick={readAll} variant="outline" className="rounded-full border-forest/20 text-forest" data-testid="read-all-btn"><CheckCheck size={15} className="mr-1.5" /> Mark all read</Button>}
      </div>
      {items.length === 0 ? <EmptyState icon={Bell} title={t("empty.notifications")} testid="notif-empty" /> : (
        <div className="space-y-2">
          {items.map((n) => (
            <div key={n.id} className={`flex gap-3 rounded-2xl border p-4 ${n.read ? "border-brand-50 bg-white" : "border-gold/30 bg-gold-light/40"}`} data-testid={`notif-${n.id}`}>
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand"><Bell size={16} /></div>
              <div className="flex-1">
                <div className="font-medium text-ink">{lang === "hi" ? n.title_hi : n.title}</div>
                <div className="text-sm text-muted2">{lang === "hi" ? n.message_hi : n.message}</div>
                <div className="mt-1 text-xs text-muted2">{(n.created_at || "").slice(0, 16).replace("T", " ")}</div>
              </div>
              {!n.read && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-gold" />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

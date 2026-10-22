import React, { useEffect, useState } from "react";
import { Bell, CheckCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";
import { Stagger, StaggerItem } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

export default function Notifications() {
  const { t, lang } = useI18n();
  const [items, setItems] = useState(null);

  const load = () => API.get("/notifications").then(({ data }) => setItems(data.items)).catch(() => setItems([]));
  useEffect(() => { load(); }, []);

  const readAll = async () => { await API.post("/notifications/read-all"); load(); };

  if (!items) return <div className="space-y-2.5">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 rounded-2xl" />)}</div>;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title={t("nav.notifications")} icon={Bell}
        actions={items.length > 0 && <Button onClick={readAll} variant="outline" className="h-11 rounded-full border-brand-50 bg-transparent px-5 text-ink" data-testid="read-all-btn"><CheckCheck size={15} className="mr-1.5" /> Mark all read</Button>} />
      {items.length === 0 ? <EmptyState icon={Bell} title={t("empty.notifications")} testid="notif-empty" /> : (
        <Stagger className="space-y-2.5">
          {items.map((n) => (
            <StaggerItem key={n.id} layout
              className={`hg-card relative flex gap-3 overflow-hidden p-4 transition-colors ${n.read ? "" : "bg-hg-violet/[0.06] ring-1 ring-hg-lavender/25"}`} data-testid={`notif-${n.id}`}>
              {!n.read && <span className="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-hg-violet to-hg-pink" />}
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 ${n.read ? "bg-brand-50 text-muted2 ring-brand-50" : "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/25"}`}><Bell size={16} /></span>
              <div className="min-w-0 flex-1">
                <div className={`break-words ${n.read ? "font-medium text-ink" : "font-semibold text-ink"}`}>{lang === "hi" ? n.title_hi : n.title}</div>
                <div className="break-words text-sm text-muted2">{lang === "hi" ? n.message_hi : n.message}</div>
                <div className="mt-1 text-xs text-muted2">{(n.created_at || "").slice(0, 16).replace("T", " ")}</div>
              </div>
              {!n.read && <span className="relative mt-1.5 flex h-2.5 w-2.5 shrink-0"><span className="h-2.5 w-2.5 rounded-full bg-hg-pink shadow-[0_0_8px_rgba(237,155,234,0.8)]" /></span>}
            </StaggerItem>
          ))}
        </Stagger>
      )}
    </div>
  );
}

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/PageHeader";
import { Pager } from "@/components/Pager";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";
import { Pill, StateBlock, fmtDateTime, useAction, usePaged } from "@/components/vendor/kit";

const TYPES = ["", "order", "stock", "vendor", "points", "security"];
const SELECT = "h-10 rounded-full bg-white/5 px-4 text-sm text-ink ring-1 ring-white/15";

function linkFor(n) {
  const m = n.meta || {};
  if (m.return_case) return `/vendor/returns?open=${m.return_case}`;
  if (m.ticket) return `/vendor/support?open=${m.ticket}`;
  if (m.order_id) return `/vendor/orders?open=${m.order_id}`;
  if (m.product_id) return "/vendor/inventory";
  return null;
}

export default function VendorNotifications() {
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const [unread, setUnread] = useState(false);
  const [type, setType] = useState("");
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/notifications", { unread: unread || undefined, type: type || undefined }, 20);
  const [run, busy] = useAction();
  const markAll = () => run(async () => { await API.post("/notifications/read-all"); reload(); }, { success: t("vx.noti.allRead") });
  const open = (n) => run(async () => { if (!n.read) await API.post(`/notifications/${n.id}/read`); const l = linkFor(n); if (l) nav(l); else reload(); });
  return (
    <div className="space-y-5">
      <PageHeader title={t("vx.nav.notifications")} icon={Bell} actions={<Button variant="outline" className="h-10 rounded-full" onClick={markAll} disabled={busy || !data?.unread} data-testid="noti-read-all"><CheckCheck size={15} /> {t("vx.noti.markAll")}</Button>} />
      <p className="flex gap-2 rounded-xl bg-white/5 p-3 text-xs text-muted2" role="note"><Info size={14} className="mt-0.5 shrink-0" aria-hidden /> {t("vx.noti.inAppOnly")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={unread} onChange={(e) => setUnread(e.target.checked)} data-testid="noti-unread-only" /> {t("vx.noti.unreadOnly")}</label>
        <label className="sr-only" htmlFor="noti-type">{t("vx.fin.type")}</label>
        <select id="noti-type" className={SELECT} value={type} onChange={(e) => setType(e.target.value)} data-testid="noti-type">{TYPES.map((x) => <option key={x} value={x}>{x ? t(`vx.noti.type.${x}`) : t("vp.o.all")}</option>)}</select>
        {data && <span className="ml-auto text-xs text-muted2" data-testid="noti-unread-count">{t("vx.unread", { n: data.unread })}</span>}
      </div>
      <StateBlock loading={loading} error={error} onRetry={reload} testid="noti" empty={items && items.length === 0} emptyIcon={Bell} emptyTitle={t("vx.noti.empty")}>
        <ul className="space-y-2">{(items || []).map((n) => (
          <li key={n.id}>
            <button onClick={() => open(n)} className={`hg-tile flex w-full items-start gap-3 p-3 text-left hover:bg-brand-50/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-hg-violet ${n.read ? "opacity-70" : ""}`} data-testid={`noti-${n.id}`}>
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.read ? "bg-white/20" : "bg-hg-violet"}`} aria-hidden />
              <span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-ink">{lang === "hi" ? n.title_hi || n.title : n.title}</span>{!n.read && <Pill tone="violet">{t("vx.noti.new")}</Pill>}</span>
                <span className="mt-0.5 block text-sm text-muted2">{lang === "hi" ? n.message_hi || n.message : n.message}</span><span className="mt-1 block text-[11px] text-muted2">{fmtDateTime(n.created_at, lang)}</span></span>
            </button>
          </li>))}</ul>
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="noti-pager" />}
    </div>
  );
}

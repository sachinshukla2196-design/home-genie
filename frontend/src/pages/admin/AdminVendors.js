import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Store, UserPlus, PackageSearch, Check, X, Ban, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { VENDOR_STATUS_TONE } from "@/components/VendorLayout";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const inr = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

export default function AdminVendors() {
  const { t } = useI18n();
  const [vendors, setVendors] = useState(null);
  const [queue, setQueue] = useState(null);
  const [invite, setInvite] = useState("");
  const [reasons, setReasons] = useState({});

  const load = useCallback(() => {
    API.get("/admin/vendors").then(({ data }) => setVendors(data)).catch(() => setVendors([]));
    API.get("/admin/vendor-products?status=pending").then(({ data }) => setQueue(data)).catch(() => setQueue([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const act = async (url, body, okMsg) => {
    try { await API.post(url, body); toast.success(okMsg); load(); }
    catch (err) { toast.error(apiError(err)); }
  };
  const reason = (id) => reasons[id] || "";

  return (
    <div className="space-y-6">
      <PageHeader title={t("av.title")} icon={Store} />

      <SectionCard title={t("av.invite")} icon={UserPlus}>
        <form className="flex flex-col gap-3 sm:flex-row" onSubmit={(e) => { e.preventDefault(); act("/admin/vendors/invite", { identifier: invite }, t("av.inviteBtn") + " ✓").then(() => setInvite("")); }}>
          <Input value={invite} onChange={(e) => setInvite(e.target.value)} placeholder={t("av.invitePh")} className="flex-1" data-testid="av-invite-input" />
          <Button type="submit" disabled={invite.trim().length < 3} className="hg-btn h-11 rounded-full px-6" data-testid="av-invite-btn">{t("av.inviteBtn")}</Button>
        </form>
      </SectionCard>

      <SectionCard title={t("av.applications")} icon={Store}>
        {!vendors ? <Skeleton className="h-32 rounded-2xl" /> : vendors.length === 0 ? <p className="hg-tile p-6 text-center text-sm text-muted2">{t("av.none")}</p> : (
          <div className="space-y-3">
            {vendors.map((v) => (
              <div key={v.id} className="hg-tile p-4" data-testid={`av-vendor-${v.vendor_code}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-ink">{v.business_name}</span>
                      <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${VENDOR_STATUS_TONE[v.status]}`} data-testid={`av-status-${v.vendor_code}`}>{t(`vp.st.${v.status}`)}</span>
                    </div>
                    <div className="mt-0.5 text-xs text-muted2">{v.vendor_code} · {v.contact_person} · {v.phone} · {v.account?.email || v.account?.mobile}</div>
                    <div className="mt-0.5 text-xs text-muted2">{(v.categories || []).join(", ")} · GSTIN {v.gstin || "—"} · {v.bank_account_name} {v.bank_account} / {v.ifsc} · {v.product_count} products</div>
                    {v.status_reason && <div className="mt-1 text-xs text-danger">{v.status_reason}</div>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {["submitted", "rejected", "approved"].includes(v.status) && (
                      <Input value={reason(v.id)} onChange={(e) => setReasons({ ...reasons, [v.id]: e.target.value })} placeholder={t("av.reasonPh")} className="h-9 w-56 text-xs" />
                    )}
                    {["submitted", "rejected"].includes(v.status) && <Btn icon={Check} onClick={() => act(`/admin/vendors/${v.id}/decision`, { action: "approve" }, t("av.approve") + " ✓")} label={t("av.approve")} primary testid={`av-approve-${v.vendor_code}`} />}
                    {v.status === "submitted" && <Btn icon={X} onClick={() => act(`/admin/vendors/${v.id}/decision`, { action: "reject", reason: reason(v.id) }, t("av.reject") + " ✓")} label={t("av.reject")} testid={`av-reject-${v.vendor_code}`} />}
                    {v.status === "approved" && <Btn icon={Ban} onClick={() => act(`/admin/vendors/${v.id}/decision`, { action: "suspend", reason: reason(v.id) }, t("av.suspend") + " ✓")} label={t("av.suspend")} testid={`av-suspend-${v.vendor_code}`} />}
                    {v.status === "suspended" && <Btn icon={RotateCcw} onClick={() => act(`/admin/vendors/${v.id}/decision`, { action: "reinstate" }, t("av.reinstate") + " ✓")} label={t("av.reinstate")} primary testid={`av-reinstate-${v.vendor_code}`} />}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title={`${t("av.productsQueue")}${queue ? ` · ${queue.length}` : ""}`} icon={PackageSearch}>
        {!queue ? <Skeleton className="h-32 rounded-2xl" /> : queue.length === 0 ? <p className="hg-tile p-6 text-center text-sm text-muted2">{t("av.noPending")}</p> : (
          <div className="grid gap-3 md:grid-cols-2">
            {queue.map((p) => (
              <div key={p.id} className="hg-tile flex min-w-0 flex-col gap-3 p-4" data-testid={`av-product-${p.sku}`}>
                <div className="flex gap-3">
                  {p.images?.[0] && <img src={p.images[0]} alt="" className="h-16 w-16 shrink-0 rounded-xl object-cover ring-1 ring-brand-50" />}
                  <div className="min-w-0">
                    <div className="truncate font-medium text-ink">{p.name}</div>
                    <div className="truncate text-xs text-muted2">{p.vendor_name} · {p.sku} · {p.category}</div>
                    <div className="mt-1 text-sm"><b className="text-ink">{inr(p.selling_price)}</b> <span className="text-muted2 line-through">{inr(p.mrp)}</span> · GST {p.gst_percent}% · stock {p.stock}</div>
                  </div>
                </div>
                {p.description && <p className="line-clamp-3 text-xs text-muted2">{p.description}</p>}
                <div className="flex flex-wrap gap-2">
                  <Input value={reason(p.id)} onChange={(e) => setReasons({ ...reasons, [p.id]: e.target.value })} placeholder={t("av.reasonPh")} className="h-9 min-w-0 flex-1 text-xs" />
                  <Btn icon={Check} primary label={t("av.approve")} onClick={() => act(`/admin/vendor-products/${p.id}/decision`, { action: "approve" }, t("av.approve") + " ✓")} testid={`av-papprove-${p.sku}`} />
                  <Btn icon={X} label={t("av.reject")} onClick={() => act(`/admin/vendor-products/${p.id}/decision`, { action: "reject", reason: reason(p.id) }, t("av.reject") + " ✓")} testid={`av-preject-${p.sku}`} />
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}

function Btn({ icon: Icon, label, onClick, primary, testid }) {
  return (
    <Button onClick={onClick} size="sm" data-testid={testid}
      className={`h-9 rounded-full px-3.5 ${primary ? "hg-btn" : "border border-danger/40 bg-transparent text-danger hover:bg-danger/10"}`}>
      <Icon size={14} /> {label}
    </Button>
  );
}

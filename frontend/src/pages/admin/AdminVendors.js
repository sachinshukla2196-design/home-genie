import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Ban, Check, ClipboardList, Inbox, PackageSearch, RotateCcw, Store, X } from "lucide-react";
import { VButton, VCard, VInput, VStatus } from "@/components/vendor/VendorUI";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";
import { VendorAccountForm } from "@/pages/admin/AdminVendorCreate";

// The server enforces all of this; hiding controls is only a convenience.
const MANAGE = ["super_admin", "admin"];                         // onboarding, suspension, product decisions
const ONBOARDING = ["onboarding", "ready_for_review"];
const inr = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

export default function AdminVendors() {
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const isSuper = user?.role === "super_admin";                  // final approval, final rejection and reinstatement
  const [vendors, setVendors] = useState(null);
  const [queue, setQueue] = useState(null);
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
  const reasonBox = (id) => (
    <VInput aria-label="Reason" value={reason(id)} onChange={(e) => setReasons({ ...reasons, [id]: e.target.value })} placeholder="Reason (shown to the vendor)" className="!mt-0 sm:!w-64" />
  );

  return (
    <div className="hgv-surface -mx-1 space-y-5 rounded-[1.75rem] p-3 ring-1 ring-aurum-400/40 sm:mx-0 sm:p-6" data-testid="admin-vendors-page">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-aurum-700">Vendor Pillar</p>
          <h1 className="hgv-title mt-1 text-3xl font-bold">Vendors</h1>
          <p className="hgv-muted mt-1 text-sm">Applications → onboarding → super admin approval → owner invitation → operations.</p>
        </div>
        <VButton variant="gold" icon={Inbox} to="/admin/vendor-applications" data-testid="to-vendor-applications">Vendor applications</VButton>
      </div>

      {canManage && <VendorAccountForm onCreated={load} />}

      <VCard className="p-5 sm:p-6">
        <h2 className="hgv-title flex items-center gap-2 text-xl font-semibold"><Store size={19} className="text-aurum-600" aria-hidden /> All vendors</h2>
        {!vendors ? <p className="hgv-muted mt-4 text-sm">Loading…</p> : vendors.length === 0 ? <p className="hgv-muted mt-4 text-sm">No vendors yet.</p> : (
          <div className="mt-4 space-y-3">
            {vendors.map((v) => {
              const inOnboarding = ONBOARDING.includes(v.status) || (v.onboarding_path && ["rejected", "approved", "active"].includes(v.status));
              return (
                <div key={v.id} className="hgv-card p-4" data-testid={`av-vendor-${v.vendor_code}`}>
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-choco-900">{v.business_name}</span>
                        <span data-testid={`av-status-${v.vendor_code}`}><VStatus status={v.status} /></span>
                      </div>
                      <div className="hgv-muted mt-0.5 text-xs">{v.vendor_code} · {v.contact_person || "—"} · {v.phone || v.account?.mobile} · {v.account?.email || "no email"}</div>
                      <div className="hgv-muted mt-0.5 text-xs">{(v.categories || []).join(", ") || "No categories yet"} · {v.product_count} products{v.bank_account ? ` · bank ${v.bank_account}` : ""}</div>
                      {v.status_reason && !ONBOARDING.includes(v.status) && <div className="mt-1 text-xs font-semibold text-[#9B2C1C]">{v.status_reason}</div>}
                    </div>
                    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center lg:justify-end">
                      {inOnboarding && <VButton size="sm" variant={v.status === "ready_for_review" && isSuper ? "gold" : "secondary"} icon={ClipboardList} to={`/admin/vendors/${v.id}/onboarding`} data-testid={`av-open-${v.vendor_code}`}>
                        {v.status === "ready_for_review" ? (isSuper ? "Final review" : "View registration") : "Open registration"}</VButton>}
                      {/* legacy self-onboarding applications: the final decision is super admin only */}
                      {isSuper && ["submitted", "under_review", "rejected"].includes(v.status) && !v.onboarding_path && (<>
                        <VButton size="sm" variant="primary" icon={Check} onClick={() => act(`/admin/vendors/${v.id}/decision`, { action: "approve" }, "Vendor approved")} data-testid={`av-approve-${v.vendor_code}`}>Approve</VButton>
                        {v.status !== "rejected" && <>{reasonBox(v.id)}<VButton size="sm" variant="danger" icon={X} disabled={reason(v.id).trim().length < 5} onClick={() => act(`/admin/vendors/${v.id}/decision`, { action: "reject", reason: reason(v.id) }, "Vendor rejected")} data-testid={`av-reject-${v.vendor_code}`}>Reject</VButton></>}
                      </>)}
                      {canManage && ["approved", "active"].includes(v.status) && (<>
                        {reasonBox(v.id)}
                        <VButton size="sm" variant="danger" icon={Ban} disabled={reason(v.id).trim().length < 5} onClick={() => act(`/admin/vendors/${v.id}/decision`, { action: "suspend", reason: reason(v.id) }, "Vendor suspended")} data-testid={`av-suspend-${v.vendor_code}`}>Suspend</VButton>
                      </>)}
                      {isSuper && v.status === "suspended" && <VButton size="sm" variant="primary" icon={RotateCcw} onClick={() => act(`/admin/vendors/${v.id}/decision`, { action: "reinstate" }, "Vendor reinstated")} data-testid={`av-reinstate-${v.vendor_code}`}>Reinstate</VButton>}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </VCard>

      <VCard className="p-5 sm:p-6">
        <h2 className="hgv-title flex items-center gap-2 text-xl font-semibold"><PackageSearch size={19} className="text-aurum-600" aria-hidden /> Products awaiting review {queue ? `· ${queue.length}` : ""}</h2>
        {!queue ? <p className="hgv-muted mt-4 text-sm">Loading…</p> : queue.length === 0 ? <p className="hgv-muted mt-4 text-sm">No products are waiting for review.</p> : (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {queue.map((p) => (
              <div key={p.id} className="hgv-card flex min-w-0 flex-col gap-3 p-4" data-testid={`av-product-${p.sku}`}>
                <div className="flex gap-3">
                  {p.images?.[0] && <img src={p.images[0]} alt="" className="h-16 w-16 shrink-0 rounded-xl object-cover ring-1 ring-aurum-400/40" />}
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-choco-900">{p.name}</div>
                    <div className="hgv-muted truncate text-xs">{p.vendor_name} · {p.sku} · {p.category}</div>
                    <div className="mt-1 text-sm"><b className="text-choco-900">{inr(p.selling_price)}</b> <span className="hgv-muted line-through">{inr(p.mrp)}</span> · GST {p.gst_percent}% · stock {p.stock}</div>
                  </div>
                </div>
                {p.description && <p className="hgv-muted line-clamp-3 text-xs">{p.description}</p>}
                {canManage && (
                  <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                    {reasonBox(p.id)}
                    <VButton size="sm" variant="primary" icon={Check} onClick={() => act(`/admin/vendor-products/${p.id}/decision`, { action: "approve" }, "Product approved")} data-testid={`av-papprove-${p.sku}`}>Approve</VButton>
                    <VButton size="sm" variant="danger" icon={X} disabled={reason(p.id).trim().length < 5} onClick={() => act(`/admin/vendor-products/${p.id}/decision`, { action: "reject", reason: reason(p.id) }, "Product rejected")} data-testid={`av-preject-${p.sku}`}>Reject</VButton>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </VCard>
    </div>
  );
}

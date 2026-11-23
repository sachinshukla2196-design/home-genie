import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Briefcase, Home, Loader2, MapPin, Pencil, Plus, Star, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const EMPTY = { label: "home", full_name: "", mobile: "", line1: "", line2: "", locality: "", landmark: "", city: "", district: "", state: "", pincode: "", make_default: false };
const ICON = { home: Home, work: Briefcase, other: MapPin };
const SELECT = "h-11 w-full rounded-xl bg-white px-3 text-sm text-ink ring-1 ring-brand-100 dark:bg-white/5 dark:ring-white/15";

/** Batch 13, Phase 7A: the customer's address book. Every rule is enforced by the server (GET/POST/PUT/DELETE /api/addresses). */
export default function Addresses() {
  const { t } = useI18n();
  const [d, setD] = useState(null);
  const [edit, setEdit] = useState(null);       // null | {id?, ...fields}
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({});

  const load = useCallback(() => API.get("/addresses").then(({ data }) => setD(data)).catch((e) => toast.error(apiError(e))), []);
  useEffect(() => { load(); }, [load]);

  const problems = (f) => ({
    full_name: f.full_name.trim().length < 2 ? t("addr.errName") : null,
    mobile: /^[6-9]\d{9}$/.test(f.mobile.replace(/[\s-]/g, "").replace(/^\+91/, "")) ? null : t("addr.errMobile"),
    line1: f.line1.trim().length < 3 ? t("addr.errLine1") : null,
    city: f.city.trim().length < 2 ? t("addr.errCity") : null,
    state: f.state ? null : t("addr.errState"),
    pincode: /^[1-9]\d{5}$/.test(f.pincode.trim()) ? null : t("addr.errPin"),
  });

  const save = async () => {
    const p = problems(edit);
    setErrors(p);
    if (Object.values(p).some(Boolean)) return;
    setBusy(true);
    try {
      const body = { ...edit };
      delete body.id; delete body.is_default; delete body.created_at; delete body.updated_at; delete body.last_used_at; delete body.country;
      if (edit.id) await API.put(`/addresses/${edit.id}`, body); else await API.post("/addresses", body);
      toast.success(t("addr.saved"));
      setEdit(null); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const act = async (fn, msg) => { try { const { data } = await fn(); setD(data); if (msg) toast.success(msg); } catch (e) { toast.error(apiError(e)); } };

  if (!d) return <Loader2 className="animate-spin text-muted2" />;
  const set = (k) => (e) => setEdit({ ...edit, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const F = ({ k, label, req, ...rest }) => (
    <div>
      <label htmlFor={`ad-${k}`} className="text-sm font-medium text-ink">{label}{!req && <span className="font-normal text-muted2"> ({t("addr.optional")})</span>}</label>
      <Input id={`ad-${k}`} className="mt-1.5 h-11 rounded-xl" value={edit[k] || ""} onChange={set(k)} aria-invalid={errors[k] ? "true" : undefined} data-testid={`ad-${k}`} {...rest} />
      {errors[k] && <p role="alert" className="mt-1 text-xs text-danger">{errors[k]}</p>}
    </div>
  );

  return (
    <div className="space-y-5">
      <PageHeader title={t("addr.title")} subtitle={t("addr.sub")} icon={MapPin}
        actions={d.items.length < d.max && <Button onClick={() => { setErrors({}); setEdit({ ...EMPTY }); }} className="hg-btn h-11 rounded-full px-5" data-testid="ad-add"><Plus size={16} /> {t("addr.add")}</Button>} />
      {d.items.length === 0 ? <EmptyState icon={MapPin} title={t("addr.none")} ctaLabel={t("addr.add")} onCta={() => setEdit({ ...EMPTY })} testid="ad-empty" /> : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {d.items.map((a) => {
            const Icon = ICON[a.label] || MapPin;
            return (
              <li key={a.id} className={`hg-card p-5 ${a.is_default ? "ring-2 ring-hg-gold/50" : ""}`} data-testid={`ad-card-${a.id}`}>
                <div className="flex items-center gap-2 text-sm font-semibold capitalize text-ink"><Icon size={16} /> {t(`addr.label.${a.label}`)}
                  {a.is_default && <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-hg-gold/15 px-2.5 py-0.5 text-[11px] font-semibold text-hg-gold"><Star size={11} /> {t("addr.default")}</span>}</div>
                <p className="mt-2 text-sm text-ink">{a.full_name}</p>
                <p className="text-sm text-muted2">{[a.line1, a.line2, a.locality, a.landmark].filter(Boolean).join(", ")}</p>
                <p className="text-sm text-muted2">{[a.city, a.district, a.state].filter(Boolean).join(", ")} {a.pincode}</p>
                <p className="text-sm text-muted2">{a.mobile}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" className="rounded-full" onClick={() => { setErrors({}); setEdit({ ...a }); }}><Pencil size={14} /> {t("addr.edit")}</Button>
                  {!a.is_default && <Button variant="outline" size="sm" className="rounded-full" onClick={() => act(() => API.post(`/addresses/${a.id}/default`), t("addr.defaultSet"))} data-testid={`ad-default-${a.id}`}><Star size={14} /> {t("addr.makeDefault")}</Button>}
                  <Button variant="ghost" size="sm" className="rounded-full text-danger" onClick={() => window.confirm(t("addr.confirmDelete")) && act(() => API.delete(`/addresses/${a.id}`), t("addr.deleted"))} data-testid={`ad-delete-${a.id}`}><Trash2 size={14} /> {t("addr.delete")}</Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-xs text-muted2">{t("addr.note")}</p>

      <Dialog open={!!edit} onOpenChange={(o) => !o && !busy && setEdit(null)}>
        <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto rounded-3xl" data-testid="ad-dialog">
          <DialogHeader><DialogTitle>{edit?.id ? t("addr.edit") : t("addr.add")}</DialogTitle><DialogDescription>{t("addr.indiaOnly")}</DialogDescription></DialogHeader>
          {edit && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2 flex gap-2" role="radiogroup" aria-label={t("addr.type")}>
                {(d.labels || ["home", "work", "other"]).map((l) => (
                  <button type="button" key={l} role="radio" aria-checked={edit.label === l} onClick={() => setEdit({ ...edit, label: l })}
                    className={`h-10 rounded-full px-4 text-sm font-semibold ${edit.label === l ? "hg-chip-on text-white" : "hg-chip-off"}`}>{t(`addr.label.${l}`)}</button>
                ))}
              </div>
              {F({ k: "full_name", label: t("addr.name"), req: true, maxLength: 80, autoComplete: "name" })}
              {F({ k: "mobile", label: t("addr.mobile"), req: true, inputMode: "numeric", maxLength: 14, autoComplete: "tel-national" })}
              <div className="sm:col-span-2">{F({ k: "line1", label: t("addr.line1"), req: true, maxLength: 120, autoComplete: "address-line1" })}</div>
              <div className="sm:col-span-2">{F({ k: "line2", label: t("addr.line2"), maxLength: 120, autoComplete: "address-line2" })}</div>
              {F({ k: "locality", label: t("addr.locality"), maxLength: 120 })}
              {F({ k: "landmark", label: t("addr.landmark"), maxLength: 120 })}
              {F({ k: "city", label: t("addr.city"), req: true, maxLength: 60, autoComplete: "address-level2" })}
              {F({ k: "district", label: t("addr.district"), maxLength: 120 })}
              <div>
                <label htmlFor="ad-state" className="text-sm font-medium text-ink">{t("addr.state")}</label>
                <select id="ad-state" className={`${SELECT} mt-1.5`} value={edit.state} onChange={set("state")} data-testid="ad-state">
                  <option value="">{t("addr.choose")}</option>{d.states.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                {errors.state && <p role="alert" className="mt-1 text-xs text-danger">{errors.state}</p>}
              </div>
              {F({ k: "pincode", label: t("addr.pincode"), req: true, inputMode: "numeric", maxLength: 6, autoComplete: "postal-code" })}
              {!edit.is_default && <label className="sm:col-span-2 flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={!!edit.make_default} onChange={set("make_default")} /> {t("addr.makeDefault")}</label>}
              <div className="sm:col-span-2 flex justify-end gap-2 pt-2">
                <Button variant="outline" className="h-11 rounded-full" onClick={() => setEdit(null)} disabled={busy}>{t("addr.cancel")}</Button>
                <Button className="hg-btn h-11 rounded-full px-6" onClick={save} disabled={busy} data-testid="ad-save">{busy ? <Loader2 size={16} className="animate-spin" /> : t("addr.save")}</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

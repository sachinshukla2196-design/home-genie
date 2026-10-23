import React, { useRef, useState } from "react";
import { toast } from "sonner";
import { ImagePlus, Trash2, Upload, ArrowUp, ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const ALLOWED = ["image/jpeg", "image/png", "image/webp"];
const MAX_BYTES = 5 * 1024 * 1024;

/** Posts the file straight to Cloudinary using a server-signed request. Returns the https URL. Reports progress 0-100. */
export function uploadSigned(file, sig, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("api_key", sig.api_key);
    fd.append("signature", sig.signature);
    Object.entries(sig.params).forEach(([k, v]) => fd.append(k, v));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", sig.upload_url);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      try {
        const j = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300 && j.secure_url) resolve(j.secure_url);
        else reject(new Error(j?.error?.message || "Upload failed"));
      } catch { reject(new Error("Upload failed")); }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(fd);
  });
}

/** Gallery editor: reorder / remove / add by https link or by (server-authorised) upload. Existing image paths are kept as they are. */
export function ImageInput({ value, onChange, max = 8, testid = "images" }) {
  const { t } = useI18n();
  const [link, setLink] = useState("");
  const [progress, setProgress] = useState(null);
  const file = useRef(null);
  const add = (u) => { const v = u.trim(); if (v && !value.includes(v) && value.length < max) onChange([...value, v]); };
  const move = (i, d) => { const a = [...value]; const j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; onChange(a); };

  const pick = async (e) => {
    const f = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!f) return;
    if (!ALLOWED.includes(f.type)) { toast.error(t("vx.img.type")); return; }
    if (f.size > MAX_BYTES) { toast.error(t("vx.img.size")); return; }
    setProgress(0);
    try {
      const { data: sig } = await API.post("/vendor/uploads/sign", { kind: "product" });
      add(await uploadSigned(f, sig, setProgress));
      toast.success(t("vx.img.uploaded"));
    } catch (err) {
      const status = err?.response?.status;
      toast.error(status === 503 ? t("vx.img.notConfigured") : status === 429 ? t("vx.img.tooMany") : (apiError(err) || t("vx.img.failed")));
    } finally { setProgress(null); }
  };

  return (
    <div className="space-y-3" data-testid={testid}>
      {value.length > 0 && (
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {value.map((u, i) => (
            <li key={u} className="hg-tile relative overflow-hidden p-1.5" data-testid={`${testid}-item-${i}`}>
              <img src={u} alt={t("vx.img.alt", { n: i + 1 })} className="h-24 w-full rounded-lg object-cover" loading="lazy" />
              {i === 0 && <span className="absolute left-2 top-2 rounded-full bg-hg-violet px-2 py-0.5 text-[10px] font-bold text-white">{t("vx.img.main")}</span>}
              <div className="mt-1 flex justify-between">
                <span className="flex gap-1">
                  <button type="button" onClick={() => move(i, -1)} disabled={i === 0} aria-label={t("vx.img.up")} className="hg-icon-btn !h-8 !w-8 disabled:opacity-30"><ArrowUp size={14} /></button>
                  <button type="button" onClick={() => move(i, 1)} disabled={i === value.length - 1} aria-label={t("vx.img.down")} className="hg-icon-btn !h-8 !w-8 disabled:opacity-30"><ArrowDown size={14} /></button>
                </span>
                <button type="button" onClick={() => onChange(value.filter((x) => x !== u))} aria-label={t("vx.img.remove")} className="hg-icon-btn !h-8 !w-8 text-danger"><Trash2 size={14} /></button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {value.length < max && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[12rem] flex-1">
            <label htmlFor={`${testid}-link`} className="text-xs text-muted2">{t("vx.img.link")}</label>
            <Input id={`${testid}-link`} value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://…" className="mt-1" data-testid={`${testid}-link`}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add(link), setLink(""))} />
          </div>
          <Button type="button" variant="outline" className="h-10 rounded-full" onClick={() => { add(link); setLink(""); }} data-testid={`${testid}-add`}><ImagePlus size={15} /> {t("vx.add")}</Button>
          <Button type="button" variant="outline" className="h-10 rounded-full" onClick={() => file.current && file.current.click()} disabled={progress !== null} data-testid={`${testid}-upload`}>
            <Upload size={15} /> {progress === null ? t("vx.img.upload") : `${progress}%`}
          </Button>
          <input ref={file} type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={pick} aria-label={t("vx.img.upload")} />
        </div>
      )}
      <p className="text-xs text-muted2">{t("vx.img.hint", { max })}</p>
    </div>
  );
}

import React, { useRef, useState, useEffect } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Mail, Phone, MapPin, LifeBuoy, Camera, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

function resizeImage(file, max = 400) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        let { width, height } = img;
        if (width > height) { if (width > max) { height = (height * max) / width; width = max; } }
        else { if (height > max) { width = (width * max) / height; height = max; } }
        const c = document.createElement("canvas");
        c.width = width; c.height = height;
        c.getContext("2d").drawImage(img, 0, 0, width, height);
        c.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("resize failed"))), "image/jpeg", 0.85);
      };
      img.onerror = reject;
      img.src = reader.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function Profile() {
  const { t } = useI18n();
  const { user, logout, refresh } = useAuth();
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [rank, setRank] = useState(null);
  useEffect(() => { API.get("/rank").then(({ data }) => setRank(data)).catch(() => {}); }, []);
  const initials = (user?.full_name || "U").slice(0, 2).toUpperCase();

  const onPick = () => fileRef.current?.click();

  const onPhoto = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) { toast.error("Please choose an image file."); return; }
    if (file.size > 10 * 1024 * 1024) { toast.error("Please choose an image under 10MB."); return; }
    setUploading(true);
    try {
      const blob = await resizeImage(file, 400);
      const fd = new FormData();
      fd.append("file", blob, "photo.jpg");
      const { data } = await API.post("/uploads/profile-photo", fd);
      await API.put("/auth/profile/photo", { photo: data.url });
      await refresh();
      toast.success("Profile photo updated");
    } catch (err) { toast.error(apiError(err)); }
    finally { setUploading(false); e.target.value = ""; }
  };

  const removePhoto = async () => {
    setUploading(true);
    try { await API.put("/auth/profile/photo", { photo: "" }); await refresh(); toast.success("Photo removed"); }
    catch (err) { toast.error(apiError(err)); }
    finally { setUploading(false); }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.profile")}</h1>
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <div className="flex items-center gap-4">
          <div className="relative">
            <button onClick={onPick} className="group relative block h-20 w-20 overflow-hidden rounded-full ring-2 ring-brand-50" data-testid="profile-photo-btn" title="Change photo">
              {user?.photo
                ? <img src={user.photo} alt="" className="h-full w-full object-cover" />
                : <span className="flex h-full w-full items-center justify-center bg-forest font-display text-xl font-semibold text-white">{initials}</span>}
              <span className="absolute inset-0 flex items-center justify-center bg-forest/60 opacity-0 transition-opacity group-hover:opacity-100">
                {uploading ? <Loader2 size={20} className="animate-spin text-white" /> : <Camera size={20} className="text-white" />}
              </span>
            </button>
            <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onPhoto} data-testid="profile-photo-input" />
          </div>
          <div>
            <div className="font-display text-xl font-semibold text-ink">{user?.full_name}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm"><span className="font-semibold text-forest" data-testid="profile-distributor-id">{user?.distributor_id}</span>{rank && <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-semibold text-forest" data-testid="profile-rank">Rank: {rank.code}</span>}</div>
            <div className="mt-2 flex items-center gap-3">
              <button onClick={onPick} className="text-xs font-medium text-brand hover:underline" data-testid="change-photo-link">{user?.photo ? "Change photo" : "Add photo"}</button>
              {user?.photo && <button onClick={removePhoto} className="inline-flex items-center gap-1 text-xs font-medium text-danger hover:underline" data-testid="remove-photo-link"><Trash2 size={12} /> Remove</button>}
            </div>
          </div>
        </div>
        <div className="mt-6 space-y-3 text-sm">
          <Row icon={Mail} value={user?.email} />
          <Row icon={Phone} value={user?.mobile} />
          <Row icon={MapPin} value={[user?.address, user?.city, user?.state, user?.pincode].filter(Boolean).join(", ") || "—"} />
        </div>
        {user?.sponsor_id && <div className="mt-4 rounded-lg bg-brand-50 px-4 py-2.5 text-sm text-forest">Sponsor: <b>{user.sponsor_id}</b></div>}
      </motion.div>

      {rank && (
        <div className="rounded-2xl border border-brand-50 bg-white p-5 shadow-card" data-testid="profile-rank-progress">
          <div className="flex items-center justify-between">
            <div><div className="text-xs uppercase tracking-wide text-muted2">Current Rank</div><div className="font-display text-lg font-semibold text-forest">{rank.code} — {rank.current}</div></div>
            <div className="text-right"><div className="text-xs uppercase tracking-wide text-muted2">{rank.is_max ? "Top Rank" : "Next Rank"}</div><div className="font-display text-lg font-semibold text-gold">{rank.is_max ? "★" : `${rank.next_code} — ${rank.next}`}</div></div>
          </div>
          <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-brand-50"><div className="h-full rounded-full bg-forest" style={{ width: `${rank.progress}%` }} data-testid="profile-rank-bar" /></div>
          <div className="mt-2 flex items-center justify-between text-xs text-muted2"><span data-testid="profile-rank-bv">BV {Number(rank.current_bv).toLocaleString("en-IN")}{!rank.is_max && ` / ${Number(rank.next_bv).toLocaleString("en-IN")}`}</span><span className="font-semibold text-forest">{rank.progress}%</span></div>
        </div>
      )}

      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <div className="flex items-center gap-2 font-medium text-ink"><LifeBuoy size={18} className="text-brand" /> {t("nav.support")}</div>
        <p className="mt-1 text-sm text-muted2">{t("trust.support.d")}</p>
        <a href="/legal/support" className="mt-3 inline-block text-sm font-medium text-brand hover:underline" data-testid="support-link">{t("legal.support")}</a>
      </div>

      <Button onClick={logout} variant="outline" className="w-full rounded-full border-danger/30 text-danger hover:bg-danger/10" data-testid="profile-logout">{t("nav.logout")}</Button>
    </div>
  );
}

function Row({ icon: Icon, value }) {
  return <div className="flex items-center gap-3 text-muted2"><Icon size={16} className="text-brand" /> <span className="text-ink">{value}</span></div>;
}

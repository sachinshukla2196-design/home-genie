import React, { useRef, useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import {
  MapPin, Camera, Loader2, Trash2, Package, Coins, Banknote, Share2, Bell, Globe, Palette,
  Shield, FileText, Mail, ChevronRight, LogOut,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { API, apiError } from "@/lib/api";
import { CountUp, listVariants, itemVariants } from "@/components/motion";

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
  const { t, lang, setLang } = useI18n();
  const { user, logout, refresh } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  useEffect(() => { API.get("/dashboard").then(({ data }) => setD(data)).catch(() => {}); }, []);
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const initials = (user?.full_name || "U").split(" ").filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

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

  const menu = [
    { icon: Package, title: t("profile.menu.orders"), sub: t("profile.menu.ordersSub"), go: "/app/orders", id: "orders" },
    { icon: Coins, title: t("profile.menu.points"), sub: t("profile.menu.pointsSub"), go: "/app/wallet", id: "points" },
    { icon: Banknote, title: t("profile.menu.withdraw"), sub: t("profile.menu.withdrawSub"), go: "/app/withdrawals", id: "withdraw" },
    { icon: Share2, title: t("profile.menu.share"), sub: t("profile.menu.shareSub"), go: "/app/referral", id: "share" },
    { icon: Bell, title: t("profile.menu.notifications"), sub: t("profile.menu.notificationsSub"), go: "/app/notifications", id: "notifications" },
    { icon: Globe, title: t("profile.menu.language"), sub: lang === "hi" ? "हिन्दी" : "English", act: () => setLang(lang === "hi" ? "en" : "hi"), id: "language" },
    { icon: Palette, title: t("profile.menu.theme"), sub: theme === "dark" ? t("theme.dark") : t("theme.light"), act: toggle, id: "theme" },
    { icon: Shield, title: t("profile.menu.privacy"), go: "/legal/privacy", id: "privacy" },
    { icon: FileText, title: t("profile.menu.terms"), go: "/legal/terms", id: "terms" },
    { icon: Mail, title: t("profile.menu.support"), sub: t("profile.menu.supportSub"), go: "/legal/support", id: "support" },
  ];

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.profile")}</h1>
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="hg-card relative overflow-hidden p-6 text-center" data-testid="profile-card">
        <span className="hg-orb left-1/2 -top-10 h-40 w-56 -translate-x-1/2 bg-hg-violet/25" />
        <motion.div className="relative mx-auto w-fit" initial={{ scale: 0.85, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 260, damping: 20, delay: 0.05 }}>
          {/* Slowly rotating gold ring around the avatar */}
          <motion.span aria-hidden className="absolute -inset-[5px] rounded-full"
            style={{ background: "conic-gradient(from 0deg, #FACC15, #F59E0B, #FDE68A, #FACC15)" }}
            animate={{ rotate: 360 }} transition={{ duration: 10, ease: "linear", repeat: Infinity }} />
          <button onClick={onPick} className="group relative block h-28 w-28 overflow-hidden rounded-full border-4 border-white dark:border-hg-bg2" data-testid="profile-photo-btn" title="Change photo">
            {user?.photo
              ? <img src={user.photo} alt="" className="h-full w-full object-cover" />
              : <span className="flex h-full w-full items-center justify-center bg-[#F5F0FF] font-display text-4xl font-semibold text-ink dark:bg-hg-deep">{initials}</span>}
            <span className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 transition-opacity group-hover:opacity-100">
              {uploading ? <Loader2 size={22} className="animate-spin text-white" /> : <Camera size={22} className="text-white" />}
            </span>
          </button>
          <span className="absolute bottom-0.5 right-0.5 flex h-8 w-8 items-center justify-center rounded-full bg-hg-violet text-white shadow-lg ring-2 ring-white dark:ring-hg-bg2"><Camera size={15} /></span>
          <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onPhoto} data-testid="profile-photo-input" />
        </motion.div>
        <div className="relative mt-4 font-display text-2xl font-semibold text-ink">{user?.full_name}</div>
        <span className="relative mt-1.5 inline-block rounded-full bg-brand-50 px-3 py-0.5 text-sm font-semibold text-forest" data-testid="profile-distributor-id">{user?.distributor_id}</span>
        {user?.email && <div className="mt-1 text-muted2">{user.email}</div>}
        {user?.mobile && <div className="text-muted2">{user.mobile}</div>}
        {(user?.city || user?.state) && <div className="mt-1 inline-flex items-center gap-1 text-sm text-muted2"><MapPin size={14} /> {[user?.city, user?.state].filter(Boolean).join(", ")}</div>}
        <div className="mt-2 flex items-center justify-center gap-3">
          <button onClick={onPick} className="text-xs font-medium text-brand hover:underline" data-testid="change-photo-link">{user?.photo ? "Change photo" : "Add photo"}</button>
          {user?.photo && <button onClick={removePhoto} className="inline-flex items-center gap-1 text-xs font-medium text-danger hover:underline" data-testid="remove-photo-link"><Trash2 size={12} /> Remove</button>}
        </div>

        <div className="relative mt-6 grid grid-cols-3 divide-x divide-brand-50 border-t border-brand-50 pt-5">
          <div><div className="font-display text-2xl font-semibold tabular-nums text-ink">{d ? <CountUp value={d.stats.total_orders} /> : "—"}</div><div className="text-sm text-muted2">{t("profile.orders")}</div></div>
          <div><div className="font-display text-2xl font-semibold tabular-nums text-hg-gold">{d ? <CountUp value={d.wallet.available_balance} /> : "—"}</div><div className="text-sm text-muted2">{t("profile.points")}</div></div>
          <div className="flex flex-col items-center">
            <span className="rounded-full bg-hg-gold/15 px-3 py-1 text-sm font-semibold text-hg-gold">{d?.badge?.badge || "—"}</span>
            <div className="mt-1 text-sm text-muted2">{t("profile.badge")}</div>
          </div>
        </div>
      </motion.div>

      <motion.div className="hg-card overflow-hidden" data-testid="profile-menu" variants={listVariants} initial="hidden" animate="show">
        {menu.map((m, i) => (
          <motion.button key={m.id} variants={itemVariants} whileTap={{ scale: 0.98 }} onClick={() => (m.act ? m.act() : navigate(m.go))} data-testid={`profile-menu-${m.id}`}
            className={`group flex w-full items-center gap-4 px-5 py-3.5 text-left transition-colors hover:bg-brand-50/60 dark:hover:bg-white/5 ${i ? "border-t border-brand-50" : ""}`}>
            <span className="hg-icon-chip transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6"><m.icon size={20} /></span>
            <span className="min-w-0 flex-1">
              <span className="block text-base font-medium text-ink">{m.title}</span>
              {m.sub && (
                <AnimatePresence mode="wait" initial={false}>
                  <motion.span key={m.sub} className="block truncate text-sm text-muted2" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>{m.sub}</motion.span>
                </AnimatePresence>
              )}
            </span>
            <ChevronRight size={20} className="shrink-0 text-muted2 transition-transform duration-300 group-hover:translate-x-1" />
          </motion.button>
        ))}
      </motion.div>

      <Button onClick={logout} variant="outline" className="h-12 w-full rounded-full border-danger/30 bg-transparent text-danger hover:bg-danger/10" data-testid="profile-logout"><LogOut size={18} className="mr-2" />{t("nav.logout")}</Button>
    </div>
  );
}

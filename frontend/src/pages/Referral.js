import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import QRCode from "qrcode";
import { Copy, Share2, MessageCircle, Mail, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";

export default function Referral() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [info, setInfo] = useState(null);
  const [qr, setQr] = useState("");
  const link = `${window.location.origin}/register?ref=${user?.distributor_id}`;

  useEffect(() => { API.get("/referral").then(({ data }) => setInfo(data)).catch(() => {}); }, []);
  useEffect(() => {
    QRCode.toDataURL(link, { margin: 1, width: 240, color: { dark: "#2E1065", light: "#ffffff" } })
      .then(setQr).catch(() => {});
  }, [link]);

  const copy = () => { navigator.clipboard.writeText(link); toast.success(t("referral.copied")); };
  const isGreen = user?.status === "green";
  const msg = encodeURIComponent(`Shop with me on HOME GENIES — useful products for your home and family: ${link}`);

  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("referral.title")}</h1>

      {!isGreen && (
        <div className="flex items-center gap-3 rounded-2xl border border-gold/30 bg-gold-light p-4 text-forest" data-testid="referral-locked">
          <Lock size={20} /> <span className="text-sm font-medium">{t("referral.lockedNote")}</span>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted2">{t("referral.code")}</div>
            <div className="mt-1 font-display text-3xl font-semibold text-forest" data-testid="referral-code">{user?.distributor_id}</div>
            <div className="mt-5 text-xs font-semibold uppercase tracking-wide text-muted2">{t("referral.link")}</div>
            <div className="mt-2 flex items-center gap-2">
              <input readOnly value={link} className="flex-1 rounded-lg border border-brand-50 bg-background px-3 py-2.5 text-sm text-ink" data-testid="referral-link" />
              <Button onClick={copy} className="rounded-lg bg-forest hover:bg-brand" data-testid="copy-link-btn"><Copy size={16} /></Button>
            </div>
            <div className="mt-5 flex flex-wrap gap-2">
              <a href={`https://wa.me/?text=${msg}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-4 py-2 text-sm font-medium text-forest hover:bg-brand-50/70" data-testid="share-whatsapp"><MessageCircle size={16} /> WhatsApp</a>
              <a href={`mailto:?subject=Shop with me on HOME GENIES&body=${msg}`} className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-4 py-2 text-sm font-medium text-forest hover:bg-brand-50/70" data-testid="share-email"><Mail size={16} /> Email</a>
              <a href={`sms:?body=${msg}`} className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-4 py-2 text-sm font-medium text-forest hover:bg-brand-50/70" data-testid="share-sms"><Share2 size={16} /> SMS</a>
            </div>
          </div>

          {info && (
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-2xl border border-brand-50 bg-white p-5 shadow-card"><div className="text-xs uppercase tracking-wide text-muted2">{t("dash.referralCount")}</div><div className="mt-1 font-display text-2xl font-semibold text-forest" data-testid="total-referrals">{info.total_referrals}</div></div>
              <div className="rounded-2xl border border-brand-50 bg-white p-5 shadow-card"><div className="text-xs uppercase tracking-wide text-muted2">{t("dash.referralCount")}</div><div className="mt-1 font-display text-2xl font-semibold text-forest" data-testid="active-referrals">{info.active_referrals}</div></div>
            </div>
          )}
        </div>

        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} className="flex h-fit flex-col items-center rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted2">{t("referral.qr")}</div>
          {qr && <img src={qr} alt="Referral QR" className="mt-4 rounded-xl border border-brand-50 p-2" data-testid="referral-qr" />}
          <p className="mt-3 text-center text-xs text-muted2">{isGreen ? t("referral.eligibleNote") : t("referral.lockedNote")}</p>
        </motion.div>
      </div>
    </div>
  );
}

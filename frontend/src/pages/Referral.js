import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import QRCode from "qrcode";
import { Copy, Check, Share2, MessageCircle, Mail, Lock, QrCode, Users, UserCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/PageHeader";
import { Stagger, StaggerItem, pressable } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";

export default function Referral() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [info, setInfo] = useState(null);
  const [qr, setQr] = useState("");
  const [copied, setCopied] = useState(false);
  const link = `${window.location.origin}/register?ref=${user?.distributor_id}`;

  useEffect(() => { API.get("/referral").then(({ data }) => setInfo(data)).catch(() => {}); }, []);
  useEffect(() => {
    QRCode.toDataURL(link, { margin: 1, width: 240, color: { dark: "#2E1065", light: "#ffffff" } })
      .then(setQr).catch(() => {});
  }, [link]);

  const copy = () => {
    navigator.clipboard.writeText(link); toast.success(t("referral.copied"));
    setCopied(true); setTimeout(() => setCopied(false), 1600);
  };
  const isGreen = user?.status === "green";
  const msg = encodeURIComponent(`Shop with me on HOME GENIES — useful products for your home and family: ${link}`);
  const shareCls = "hg-tile inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium text-ink ring-1 ring-transparent transition-colors hover:ring-hg-lavender/30";

  return (
    <div className="space-y-5">
      <PageHeader title={t("referral.title")} icon={Share2} />

      {!isGreen && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className="hg-card flex items-center gap-3 p-4 text-ink ring-1 ring-hg-gold/30" data-testid="referral-locked">
          <span className="hg-icon-chip !h-9 !w-9 shrink-0 !rounded-xl !bg-hg-gold/15 !text-hg-gold"><Lock size={17} /></span>
          <span className="text-sm font-medium">{t("referral.lockedNote")}</span>
        </motion.div>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <Stagger className="min-w-0 space-y-5 lg:col-span-2">
          <StaggerItem className="hg-card relative overflow-hidden p-5 sm:p-6">
            <span className="hg-orb -right-10 -top-12 h-32 w-32 bg-hg-violet/25" />
            <div className="relative">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted2">{t("referral.code")}</div>
              <div className="mt-1 break-all font-display text-3xl font-semibold text-hg-violet dark:text-hg-lavender" data-testid="referral-code">{user?.distributor_id}</div>
              <div className="mt-5 text-xs font-semibold uppercase tracking-wide text-muted2">{t("referral.link")}</div>
              <div className="mt-2 flex min-w-0 items-center gap-2">
                <input readOnly value={link} aria-label={t("referral.link")} onFocus={(e) => e.target.select()}
                  className="hg-tile h-11 min-w-0 flex-1 rounded-xl px-3 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-hg-violet" data-testid="referral-link" />
                <motion.div {...pressable} className="shrink-0">
                  <Button onClick={copy} aria-label={t("cta.copy")} className="hg-btn h-11 w-11 overflow-hidden rounded-xl p-0 sm:w-auto sm:px-4" data-testid="copy-link-btn">
                    <AnimatePresence mode="wait" initial={false}>
                      <motion.span key={copied ? "ok" : "copy"} className="inline-flex items-center gap-1.5" initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.6, opacity: 0 }} transition={{ duration: 0.18 }}>
                        {copied ? <Check size={16} /> : <Copy size={16} />}
                        <span className="hidden sm:inline">{t("cta.copy")}</span>
                      </motion.span>
                    </AnimatePresence>
                  </Button>
                </motion.div>
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                <motion.a {...pressable} href={`https://wa.me/?text=${msg}`} target="_blank" rel="noreferrer" className={shareCls} data-testid="share-whatsapp"><MessageCircle size={16} className="text-hg-success" /> WhatsApp</motion.a>
                <motion.a {...pressable} href={`mailto:?subject=Shop with me on HOME GENIES&body=${msg}`} className={shareCls} data-testid="share-email"><Mail size={16} className="text-hg-lavender" /> Email</motion.a>
                <motion.a {...pressable} href={`sms:?body=${msg}`} className={shareCls} data-testid="share-sms"><Share2 size={16} className="text-hg-pink" /> SMS</motion.a>
              </div>
            </div>
          </StaggerItem>

          {info && (
            <StaggerItem className="grid grid-cols-1 gap-4 min-[380px]:grid-cols-2">
              <div className="hg-card relative overflow-hidden p-5">
                <span className="hg-orb -right-8 -top-10 h-24 w-24 bg-hg-violet/20" />
                <div className="relative flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold uppercase tracking-[0.08em] text-muted2">{t("dash.referralCount")}</div>
                    <div className="mt-2 font-display text-2xl font-semibold tabular-nums text-ink" data-testid="total-referrals">{info.total_referrals}</div>
                  </div>
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-hg-violet/15 text-hg-lavender ring-1 ring-hg-lavender/25"><Users size={18} /></span>
                </div>
              </div>
              <div className="hg-card relative overflow-hidden p-5">
                <span className="hg-orb -right-8 -top-10 h-24 w-24 bg-hg-success/15" />
                <div className="relative flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold uppercase tracking-[0.08em] text-muted2">{t("referral.activeCustomers")}</div>
                    <div className="mt-2 font-display text-2xl font-semibold tabular-nums text-ink" data-testid="active-referrals">{info.active_referrals}</div>
                  </div>
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-hg-success/15 text-hg-success ring-1 ring-hg-success/25"><UserCheck size={18} /></span>
                </div>
              </div>
            </StaggerItem>
          )}
        </Stagger>

        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.1 }}
          className="hg-card flex h-fit flex-col items-center p-5 sm:p-6">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted2"><QrCode size={14} /> {t("referral.qr")}</div>
          <div className="relative mt-4">
            <span className="absolute -inset-3 rounded-3xl bg-hg-violet/25 blur-xl" />
            <div className="relative rounded-2xl bg-white p-3 ring-1 ring-hg-lavender/40 shadow-lg">
              {qr ? <img src={qr} alt="Referral QR" className="h-48 w-48 max-w-full rounded-lg sm:h-52 sm:w-52" data-testid="referral-qr" />
                : <div className="h-48 w-48 animate-pulse rounded-lg bg-slate-100" />}
            </div>
          </div>
          <p className="mt-4 text-center text-xs text-muted2">{isGreen ? t("referral.eligibleNote") : t("referral.lockedNote")}</p>
        </motion.div>
      </div>
    </div>
  );
}

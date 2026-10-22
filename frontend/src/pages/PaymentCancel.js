import React from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";

export default function PaymentCancel() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const fade = (d) => ({ initial: { opacity: 0, y: 10 }, animate: { opacity: 1, y: 0 }, transition: { delay: d, duration: 0.35, ease: [0.16, 1, 0.3, 1] } });
  return (
    <div className="relative isolate flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-10">
      <span aria-hidden="true" className="pointer-events-none absolute -left-24 top-16 -z-10 h-72 w-72 rounded-full bg-hg-violet/25 blur-3xl" />
      <span aria-hidden="true" className="pointer-events-none absolute -right-24 bottom-10 -z-10 h-64 w-64 rounded-full bg-hg-pink/15 blur-3xl" />
      <motion.div initial={{ opacity: 0, y: 16, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="hg-glass w-full max-w-md p-6 text-center sm:p-10" data-testid="payment-cancel-card">
        <motion.div initial={{ scale: 0.4, opacity: 0, rotate: 12 }} animate={{ scale: 1, opacity: 1, rotate: 0 }} transition={{ type: "spring", stiffness: 320, damping: 14, delay: 0.08 }}
          className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-danger/10 ring-1 ring-danger/25">
          <XCircle className="text-danger" size={44} />
        </motion.div>
        <motion.h1 {...fade(0.15)} className="mt-6 font-display text-2xl font-semibold text-ink">Payment cancelled</motion.h1>
        <motion.p {...fade(0.2)} className="mt-2 leading-relaxed text-muted2">Your payment was cancelled. Your cart is safe — you can try again anytime.</motion.p>
        <motion.div {...fade(0.27)} className="mt-7 flex flex-col gap-2.5">
          <Button onClick={() => navigate("/app/products")} className="hg-btn h-11 rounded-full px-6" data-testid="cancel-shop-btn">{t("cta.shopNow")}</Button>
          <Button onClick={() => navigate("/app/dashboard")} variant="outline" className="h-11 rounded-full border-brand-50 bg-transparent">{t("nav.dashboard")}</Button>
        </motion.div>
      </motion.div>
    </div>
  );
}

import React, { useEffect, useRef, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Loader2, XCircle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";

export default function PaymentSuccess() {
  const { t } = useI18n();
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const sessionId = params.get("session_id");
  const [state, setState] = useState("polling"); // polling, paid, failed
  const [orderId, setOrderId] = useState(null);
  const attempts = useRef(0);

  useEffect(() => {
    if (!sessionId) { setState("failed"); return; }
    let timer;
    const poll = async () => {
      attempts.current += 1;
      try {
        const { data } = await API.get(`/payments/status/${sessionId}`);
        setOrderId(data.order_id);
        if (data.payment_status === "paid") { setState("paid"); await refresh(); return; }
        if (data.payment_status === "failed" || data.payment_status === "expired") { setState("failed"); return; }
      } catch (err) { console.error("payment status poll failed", err); }
      if (attempts.current >= 12) { setState("failed"); return; }
      timer = setTimeout(poll, 2000);
    };
    poll();
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const pop = { initial: { scale: 0.4, opacity: 0, rotate: -12 }, animate: { scale: 1, opacity: 1, rotate: 0 }, transition: { type: "spring", stiffness: 320, damping: 14, delay: 0.08 } };
  const fade = (d) => ({ initial: { opacity: 0, y: 10 }, animate: { opacity: 1, y: 0 }, transition: { delay: d, duration: 0.35, ease: [0.16, 1, 0.3, 1] } });

  return (
    <div className="relative isolate flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-10">
      <span aria-hidden="true" className="pointer-events-none absolute -left-24 top-16 -z-10 h-72 w-72 rounded-full bg-hg-violet/25 blur-3xl" />
      <span aria-hidden="true" className="pointer-events-none absolute -right-24 bottom-10 -z-10 h-64 w-64 rounded-full bg-hg-pink/15 blur-3xl" />
      <motion.div initial={{ opacity: 0, y: 16, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="hg-glass w-full max-w-md p-6 text-center sm:p-10" data-testid="payment-success-card">
        <AnimatePresence mode="wait">
        {state === "polling" && (<motion.div key="polling" exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
          <div className="relative mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-hg-violet/15 ring-1 ring-hg-lavender/25">
            <span aria-hidden="true" className="hg-logo-glow absolute inset-0 -z-10 rounded-full bg-hg-violet/30 blur-xl" />
            <Loader2 className="animate-spin text-hg-lavender" size={40} />
          </div>
          <h1 className="mt-6 font-display text-2xl font-semibold text-ink">Verifying payment…</h1>
          <p className="mt-2 leading-relaxed text-muted2">Please wait while we confirm your payment securely.</p>
        </motion.div>)}
        {state === "paid" && (<motion.div key="paid">
          <motion.div {...pop} className="relative mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-hg-success/15 ring-1 ring-hg-success/30">
            <span aria-hidden="true" className="absolute inset-0 -z-10 rounded-full bg-hg-success/25 blur-xl" />
            <CheckCircle2 className="text-hg-success" size={44} />
          </motion.div>
          <motion.h1 {...fade(0.15)} className="mt-6 font-display text-2xl font-semibold text-ink">Payment successful!</motion.h1>
          <motion.p {...fade(0.2)} className="mt-2 leading-relaxed text-muted2">Your order is confirmed and your invoice is ready.</motion.p>
          <motion.div {...fade(0.27)} className="mt-7 flex flex-col gap-2.5">
            {orderId && <Button onClick={() => navigate(`/app/orders/${orderId}`)} className="hg-btn h-11 rounded-full px-6" data-testid="view-invoice-btn">{t("order.invoice")} <ArrowRight size={16} className="ml-1.5" /></Button>}
            <Button onClick={() => navigate("/app/dashboard")} variant="outline" className="h-11 rounded-full border-brand-50 bg-transparent" data-testid="success-dashboard-btn">{t("nav.dashboard")}</Button>
          </motion.div>
        </motion.div>)}
        {state === "failed" && (<motion.div key="failed">
          <motion.div {...pop} className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-danger/10 ring-1 ring-danger/25">
            <XCircle className="text-danger" size={44} />
          </motion.div>
          <motion.h1 {...fade(0.15)} className="mt-6 font-display text-2xl font-semibold text-ink">Payment not confirmed</motion.h1>
          <motion.p {...fade(0.2)} className="mt-2 leading-relaxed text-muted2">We couldn't confirm your payment yet. If money was deducted, it will reflect shortly.</motion.p>
          <motion.div {...fade(0.27)} className="mt-7 flex flex-col">
            <Button onClick={() => navigate("/app/orders")} className="hg-btn h-11 rounded-full px-6" data-testid="failed-orders-btn">{t("nav.orders")}</Button>
          </motion.div>
        </motion.div>)}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}

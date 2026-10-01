import React, { useEffect, useRef, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
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

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-md rounded-3xl border border-brand-50 bg-white p-10 text-center shadow-soft" data-testid="payment-success-card">
        {state === "polling" && (<><Loader2 className="mx-auto animate-spin text-brand" size={48} /><h1 className="mt-5 font-display text-2xl font-semibold text-ink">Verifying payment…</h1><p className="mt-2 text-muted2">Please wait while we confirm your payment securely.</p></>)}
        {state === "paid" && (<>
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-brand-50"><CheckCircle2 className="text-brand" size={40} /></div>
          <h1 className="mt-5 font-display text-2xl font-semibold text-forest">Payment successful!</h1>
          <p className="mt-2 text-muted2">Your order is confirmed and your invoice is ready. If this was a qualifying purchase, your distributor account is now activated.</p>
          <div className="mt-7 flex flex-col gap-2">
            {orderId && <Button onClick={() => navigate(`/app/orders/${orderId}`)} className="rounded-full bg-forest hover:bg-brand" data-testid="view-invoice-btn">{t("order.invoice")} <ArrowRight size={16} className="ml-1.5" /></Button>}
            <Button onClick={() => navigate("/app/dashboard")} variant="outline" className="rounded-full border-forest/20 text-forest" data-testid="success-dashboard-btn">{t("nav.dashboard")}</Button>
          </div>
        </>)}
        {state === "failed" && (<>
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-danger/10"><XCircle className="text-danger" size={40} /></div>
          <h1 className="mt-5 font-display text-2xl font-semibold text-ink">Payment not confirmed</h1>
          <p className="mt-2 text-muted2">We couldn't confirm your payment yet. If money was deducted, it will reflect shortly.</p>
          <Button onClick={() => navigate("/app/orders")} className="mt-7 rounded-full bg-forest hover:bg-brand" data-testid="failed-orders-btn">{t("nav.orders")}</Button>
        </>)}
      </motion.div>
    </div>
  );
}

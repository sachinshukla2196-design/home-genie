import React from "react";
import { useNavigate } from "react-router-dom";
import { XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";

export default function PaymentCancel() {
  const { t } = useI18n();
  const navigate = useNavigate();
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md rounded-3xl border border-brand-50 bg-white p-10 text-center shadow-soft" data-testid="payment-cancel-card">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-danger/10"><XCircle className="text-danger" size={40} /></div>
        <h1 className="mt-5 font-display text-2xl font-semibold text-ink">Payment cancelled</h1>
        <p className="mt-2 text-muted2">Your payment was cancelled. Your cart is safe — you can try again anytime.</p>
        <div className="mt-7 flex flex-col gap-2">
          <Button onClick={() => navigate("/app/products")} className="rounded-full bg-forest hover:bg-brand" data-testid="cancel-shop-btn">{t("cta.shopNow")}</Button>
          <Button onClick={() => navigate("/app/dashboard")} variant="outline" className="rounded-full border-forest/20 text-forest">{t("nav.dashboard")}</Button>
        </div>
      </div>
    </div>
  );
}

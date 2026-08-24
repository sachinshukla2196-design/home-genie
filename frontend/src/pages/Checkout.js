import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { CreditCard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

export default function Checkout() {
  const { t, lang } = useI18n();
  const { items, subtotal, clear } = useCart();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [showQr, setShowQr] = useState(null);
  const [addr, setAddr] = useState({
    full_name: user?.full_name || "", mobile: user?.mobile || "", line1: user?.address || "",
    city: user?.city || "", state: user?.state || "", pincode: user?.pincode || "",
  });
  const sym = "₹";
  const money = (v) => `${sym}${Number(v).toLocaleString("en-IN")}`;
  const gst = Math.round(subtotal * 0.05);
  const total = subtotal + gst;
  const set = (k) => (e) => setAddr((a) => ({ ...a, [k]: e.target.value }));

  useEffect(() => {
    if (items.length === 0 && !showQr) navigate("/app/products");
  }, [items.length, showQr, navigate]);

  const placeOrder = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const orderItems = items.map((i) => ({ product_id: i.product_id, quantity: i.quantity }));
      const { data: order } = await API.post("/orders", { items: orderItems, address: addr });
      const { data: checkout } = await API.post("/payments/checkout", { order_id: order.id, origin_url: window.location.origin });
      clear();
      window.location.href = checkout.checkout_url;
    } catch (err) {
      toast.error(apiError(err));
      setLoading(false);
    }
  };

  const upiPay = async () => {
    setLoading(true);
    try {
      const orderItems = items.map((i) => ({ product_id: i.product_id, quantity: i.quantity }));
      const { data: order } = await API.post("/orders", { items: orderItems, address: addr });
      await API.post("/payments/upi-claim", { order_id: order.id });
      clear();
      setShowQr(order);
      toast.success(`Order ${order.order_number} placed — scan the QR to pay`);
    } catch (err) { toast.error(apiError(err)); } finally { setLoading(false); }
  };

  if (showQr) return (
    <div className="mx-auto max-w-md text-center" data-testid="upi-qr-panel">
      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <h1 className="font-display text-xl font-semibold text-ink">Scan & Pay via PhonePe / UPI</h1>
        <p className="mt-1 text-sm text-muted2">Pay <b className="text-forest">{money(showQr.total)}</b> for order <b>{showQr.order_number}</b></p>
        <img src="/phonepe-qr.webp" alt="PhonePe QR" className="mx-auto mt-4 w-64 rounded-xl border border-brand-50" data-testid="phonepe-qr" />
        <p className="mt-3 rounded-lg bg-brand-50 px-4 py-2.5 text-xs text-forest">After paying, our admin will verify the payment and activate your account. You'll be notified — no need to pay again.</p>
        <Button onClick={() => navigate("/app/orders")} className="mt-5 w-full rounded-full btn-grad" data-testid="upi-done-btn">I've paid — View my orders</Button>
      </div>
    </div>
  );

  if (items.length === 0) return null;

  return (
    <div>
      <h1 className="mb-6 font-display text-2xl font-semibold text-ink">{t("checkout.title")}</h1>
      <form onSubmit={placeOrder} className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="rounded-2xl border border-brand-50 bg-white p-6">
            <h3 className="mb-4 font-display text-lg font-medium text-ink">{t("checkout.shipping")}</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <F label={t("auth.fullName")} value={addr.full_name} onChange={set("full_name")} req testid="co-name" />
              <F label={t("auth.mobile")} value={addr.mobile} onChange={set("mobile")} req testid="co-mobile" />
              <div className="sm:col-span-2"><F label={t("auth.address")} value={addr.line1} onChange={set("line1")} req testid="co-line1" /></div>
              <F label={t("auth.city")} value={addr.city} onChange={set("city")} req testid="co-city" />
              <F label={t("auth.state")} value={addr.state} onChange={set("state")} req testid="co-state" />
              <F label={t("auth.pincode")} value={addr.pincode} onChange={set("pincode")} req testid="co-pincode" />
            </div>
          </div>
        </div>
        <div className="h-fit rounded-2xl border border-brand-50 bg-white p-6">
          <h3 className="font-display text-lg font-medium text-ink">{t("cart.summary")}</h3>
          <div className="mt-4 space-y-2 text-sm">
            {items.map((i) => (
              <div key={i.product_id} className="flex justify-between text-muted2"><span className="line-clamp-1">{(lang === "hi" && i.name_hi ? i.name_hi : i.name)} ×{i.quantity}</span><span>{money(i.price * i.quantity)}</span></div>
            ))}
            <div className="my-2 border-t border-brand-50" />
            <div className="flex justify-between text-muted2"><span>{t("order.subtotal")}</span><span>{money(subtotal)}</span></div>
            <div className="flex justify-between text-muted2"><span>{t("order.gst")} (5%)</span><span>{money(gst)}</span></div>
            <div className="my-2 border-t border-brand-50" />
            <div className="flex justify-between font-display text-lg font-semibold text-forest"><span>{t("order.total")}</span><span>{money(total)}</span></div>
          </div>
          <Button type="submit" disabled={loading} className="mt-6 w-full rounded-full bg-forest hover:bg-brand" data-testid="place-order-btn">
            <CreditCard size={16} className="mr-1.5" /> {loading ? t("common.loading") : t("checkout.placeOrder")}
          </Button>
          <p className="mt-3 text-center text-xs text-muted2">Test card: 4242 4242 4242 4242</p>
          <div className="mt-4 border-t border-brand-50 pt-4">
            <div className="mb-2 text-center text-xs font-medium uppercase tracking-wide text-muted2">or pay directly</div>
            <Button type="button" onClick={upiPay} disabled={loading} variant="outline" className="w-full rounded-full border-forest/30 text-forest hover:bg-brand-50" data-testid="upi-pay-btn">
              Pay via PhonePe / UPI (QR)
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}

function F({ label, value, onChange, req, testid }) {
  return <div><Label className="text-sm text-ink">{label}</Label><Input value={value} onChange={onChange} required={req} className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid={testid} /></div>;
}

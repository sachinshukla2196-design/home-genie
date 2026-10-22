import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import { CreditCard, Banknote, Check, MapPin, ShieldCheck, Wallet, QrCode } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/PageHeader";
import { Stagger, StaggerItem, pressable } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";
import { getSellerRef } from "@/lib/sellerRef";

export default function Checkout() {
  const { t, lang } = useI18n();
  const { items, subtotal, clear } = useCart();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [method, setMethod] = useState("online");
  const [showQr, setShowQr] = useState(null);
  const [cfg, setCfg] = useState({ currency_symbol: "₹", gst_percent: 5 });
  const [addr, setAddr] = useState({
    full_name: user?.full_name || "", mobile: user?.mobile || "", line1: user?.address || "",
    city: user?.city || "", state: user?.state || "", pincode: user?.pincode || "",
  });
  const sym = cfg.currency_symbol || "₹";
  const money = (v) => `${sym}${Number(v).toLocaleString("en-IN")}`;
  const gstPct = Number(cfg.gst_percent ?? 5);
  const codFee = Number(cfg.cod_fee ?? 0);
  const gst = Math.round(subtotal * gstPct / 100);
  const total = subtotal + gst;
  const set = (k) => (e) => setAddr((a) => ({ ...a, [k]: e.target.value }));

  useEffect(() => {
    API.get("/settings/public").then(({ data }) => setCfg((c) => ({ ...c, ...data }))).catch(() => {});
  }, []);

  useEffect(() => {
    if (items.length === 0 && !showQr) navigate("/app/products");
  }, [items.length, showQr, navigate]);

  const placeOrder = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const orderItems = items.map((i) => ({ product_id: i.product_id, quantity: i.quantity, variant: i.variant || null }));
      const { data: order } = await API.post("/orders", { items: orderItems, address: addr, seller_ref: getSellerRef(), payment_method: method });
      if (method === "cod") {
        clear();
        toast.success(t("checkout.codPlaced"));
        navigate("/app/orders");
        return;
      }
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
      const orderItems = items.map((i) => ({ product_id: i.product_id, quantity: i.quantity, variant: i.variant || null }));
      const { data: order } = await API.post("/orders", { items: orderItems, address: addr, seller_ref: getSellerRef(), payment_method: method });
      await API.post("/payments/upi-claim", { order_id: order.id });
      clear();
      setShowQr(order);
      toast.success(`Order ${order.order_number} placed`);
    } catch (err) { toast.error(apiError(err)); } finally { setLoading(false); }
  };

  const loadRzp = () => new Promise((res) => {
    if (window.Razorpay) return res(true);
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => res(true); s.onerror = () => res(false);
    document.body.appendChild(s);
  });

  const razorpayPay = async () => {
    setLoading(true);
    try {
      const orderItems = items.map((i) => ({ product_id: i.product_id, quantity: i.quantity, variant: i.variant || null }));
      const { data: order } = await API.post("/orders", { items: orderItems, address: addr, seller_ref: getSellerRef(), payment_method: method });
      const { data: rzp } = await API.post("/payments/razorpay/order", { order_id: order.id });
      const ok = await loadRzp();
      if (!ok) { toast.error("Could not load payment gateway."); setLoading(false); return; }
      const rz = new window.Razorpay({
        key: rzp.key_id, amount: rzp.amount, currency: rzp.currency,
        name: "HOME GENIES", description: `Order ${rzp.order_number}`,
        order_id: rzp.razorpay_order_id,
        prefill: { name: rzp.name, email: rzp.email, contact: rzp.contact },
        theme: { color: "#0B4D2E" },
        handler: async (resp) => {
          try {
            await API.post("/payments/razorpay/verify", {
              razorpay_order_id: resp.razorpay_order_id,
              razorpay_payment_id: resp.razorpay_payment_id,
              razorpay_signature: resp.razorpay_signature });
            clear();
            toast.success("Payment successful!");
            navigate(`/app/orders/${order.id}`);
          } catch (e) { toast.error(apiError(e)); }
        },
        modal: { ondismiss: () => setLoading(false) },
      });
      rz.open();
    } catch (err) { toast.error(apiError(err)); setLoading(false); }
  };

  if (showQr) return (
    <div className="mx-auto max-w-md text-center" data-testid="upi-qr-panel">
      <motion.div initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="hg-glass relative overflow-hidden rounded-3xl p-6 sm:p-7">
        <span className="hg-orb -right-10 -top-12 h-32 w-32 bg-hg-violet/30" />
        <div className="relative">
          <span className="hg-icon-chip mx-auto !h-14 !w-14 !rounded-2xl"><QrCode size={26} /></span>
          <h1 className="mt-4 font-display text-xl font-semibold text-ink">Pay via UPI</h1>
          <p className="mt-1 break-words text-sm text-muted2">Pay <b className="text-hg-violet dark:text-hg-lavender">{money(showQr.total)}</b> for order <b className="text-ink">{showQr.order_number}</b></p>
          <div className="hg-tile mx-auto mt-5 w-full max-w-[16rem] px-4 py-6 text-sm text-muted2" data-testid="upi-not-configured">
            UPI payment is not configured yet. Your order is saved — our team will contact you to arrange payment.
          </div>
          <p className="mt-3 rounded-xl bg-hg-violet/10 px-4 py-2.5 text-xs text-ink ring-1 ring-hg-lavender/20">After paying, our admin will verify the payment and activate your account. You'll be notified — no need to pay again.</p>
          <Button onClick={() => navigate("/app/orders")} className="hg-btn mt-5 h-11 w-full rounded-full" data-testid="upi-done-btn">I've paid — View my orders</Button>
        </div>
      </motion.div>
    </div>
  );

  if (items.length === 0) return null;

  const methods = [
    { k: "online", label: t("checkout.payOnline"), icon: CreditCard },
    { k: "cod", label: t("checkout.payCod"), icon: Banknote },
  ];

  return (
    <div className="space-y-5">
      <PageHeader title={t("checkout.title")} icon={ShieldCheck} />
      <form onSubmit={placeOrder} className="grid gap-5 lg:grid-cols-3">
        <Stagger className="min-w-0 space-y-5 lg:col-span-2">
          <StaggerItem className="hg-card p-5 sm:p-6">
            <h3 className="mb-4 flex items-center gap-2.5 font-display text-lg font-semibold text-ink">
              <span className="hg-icon-chip !h-9 !w-9 !rounded-xl"><MapPin size={18} /></span> {t("checkout.shipping")}
            </h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <F label={t("auth.fullName")} value={addr.full_name} onChange={set("full_name")} req testid="co-name" />
              <F label={t("auth.mobile")} value={addr.mobile} onChange={set("mobile")} req testid="co-mobile" />
              <div className="sm:col-span-2"><F label={t("auth.address")} value={addr.line1} onChange={set("line1")} req testid="co-line1" /></div>
              <F label={t("auth.city")} value={addr.city} onChange={set("city")} req testid="co-city" />
              <F label={t("auth.state")} value={addr.state} onChange={set("state")} req testid="co-state" />
              <F label={t("auth.pincode")} value={addr.pincode} onChange={set("pincode")} req testid="co-pincode" />
            </div>
          </StaggerItem>

          <StaggerItem className="hg-card p-5 sm:p-6">
            <h3 className="mb-4 flex items-center gap-2.5 font-display text-lg font-semibold text-ink">
              <span className="hg-icon-chip !h-9 !w-9 !rounded-xl"><Wallet size={18} /></span> {t("checkout.payBy")}
            </h3>
            <div className="grid gap-3 sm:grid-cols-2" data-testid="payment-method" role="radiogroup" aria-label={t("checkout.payBy")}>
              {methods.map(({ k, label, icon: Icon }) => {
                const on = method === k;
                return (
                  <motion.button key={k} type="button" onClick={() => setMethod(k)} data-testid={`pay-method-${k}`}
                    role="radio" aria-checked={on} whileTap={{ scale: 0.98 }}
                    className={`relative flex w-full min-w-0 items-center gap-3 rounded-2xl p-4 text-left text-sm transition-all ${on ? "bg-hg-violet/15 ring-2 ring-hg-violet" : "hg-tile ring-1 ring-transparent hover:ring-hg-lavender/30"}`}>
                    <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${on ? "bg-hg-violet text-white" : "bg-brand-50 text-hg-violet dark:text-hg-lavender"}`}><Icon size={18} /></span>
                    <span className="min-w-0 flex-1">
                      <span className={`block font-semibold ${on ? "text-ink" : "text-muted2"}`}>{label}</span>
                      {k === "cod" && codFee > 0 && <span className="block text-xs text-hg-gold">+{money(codFee)} {t("checkout.codFee")}</span>}
                    </span>
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition-colors ${on ? "bg-hg-violet text-white" : "ring-1 ring-brand-50"}`}>
                      <AnimatePresence>{on && <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }}><Check size={14} strokeWidth={3} /></motion.span>}</AnimatePresence>
                    </span>
                  </motion.button>
                );
              })}
            </div>
            {method === "cod" && (
              <motion.p initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}
                className="mt-3 rounded-xl bg-hg-gold/10 px-3 py-2.5 text-xs text-ink ring-1 ring-hg-gold/25" data-testid="cod-note">{t("checkout.codNote")}</motion.p>
            )}
          </StaggerItem>
        </Stagger>

        <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.12, ease: [0.16, 1, 0.3, 1] }}
          className="hg-card h-fit min-w-0 p-5 sm:p-6 lg:sticky lg:top-24">
          <h3 className="font-display text-lg font-semibold text-ink">{t("cart.summary")}</h3>
          <div className="mt-4 space-y-2 text-sm">
            {items.map((i) => (
              <div key={i.product_id} className="flex justify-between gap-3 text-muted2"><span className="line-clamp-1 min-w-0">{(lang === "hi" && i.name_hi ? i.name_hi : i.name)} ×{i.quantity}</span><span className="shrink-0 tabular-nums">{money(i.price * i.quantity)}</span></div>
            ))}
            <div className="my-2 border-t border-brand-50" />
            <div className="flex justify-between text-muted2"><span>{t("order.subtotal")}</span><span className="tabular-nums">{money(subtotal)}</span></div>
            <div className="flex justify-between text-muted2"><span>{t("order.gst")} ({gstPct}%)</span><span className="tabular-nums">{money(gst)}</span></div>
            {method === "cod" && codFee > 0 && <div className="flex justify-between text-muted2" data-testid="cod-fee-row"><span>{t("checkout.codFee")}</span><span className="tabular-nums">{money(codFee)}</span></div>}
            <div className="my-2 border-t border-brand-50" />
            <div className="flex justify-between font-display text-lg font-semibold text-ink"><span>{t("order.total")}</span><span className="tabular-nums text-hg-violet dark:text-hg-lavender">{money(total + (method === "cod" ? codFee : 0))}</span></div>
          </div>
          <motion.div {...pressable} className="mt-6">
            <Button type="submit" disabled={loading} className="hg-btn h-11 w-full rounded-full px-6" data-testid="place-order-btn">
              <CreditCard size={16} className="mr-1.5" /> {loading ? t("common.loading") : t("checkout.placeOrder")}
            </Button>
          </motion.div>
          {method === "online" && <div className="mt-4 border-t border-brand-50 pt-4">
            <div className="mb-2 text-center text-xs font-medium uppercase tracking-wide text-muted2">{t("checkout.orPayDirectly")}</div>
            <Button type="button" onClick={razorpayPay} disabled={loading} className="hg-btn mb-2 h-auto min-h-11 w-full whitespace-normal rounded-full px-5 py-2.5" data-testid="razorpay-pay-btn">
              Pay Online (Card / UPI / Netbanking)
            </Button>
            <Button type="button" onClick={upiPay} disabled={loading} variant="outline" className="h-11 w-full rounded-full border-brand-50 bg-transparent text-ink" data-testid="upi-pay-btn">
              Pay via UPI
            </Button>
          </div>}
        </motion.div>
      </form>
    </div>
  );
}

function F({ label, value, onChange, req, testid }) {
  return <div><Label className="text-sm text-ink">{label}</Label><Input value={value} onChange={onChange} required={req} className="mt-1.5" data-testid={testid} /></div>;
}

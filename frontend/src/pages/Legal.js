import React, { useEffect, useState } from "react";
import { Link, useParams, Navigate } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

const PAGES = {
  privacy: { title: "Privacy Policy", body: [
    "We collect only the information required to register and serve distributors and customers: name, mobile number, email, address, Aadhaar/PAN for KYC, bank details for payouts, and order history.",
    "Your data is used to process orders, verify identity (KYC), credit commissions, deliver OTPs and communicate about your account. We do not sell personal data to third parties.",
    "Payments are processed by Razorpay; we never store your card or UPI credentials. OTP messages are delivered through our SMS provider.",
    "You may request correction or deletion of your personal data by contacting us using the details on the Contact Us page, subject to legal record-keeping obligations.",
  ]},
  terms: { title: "Terms & Conditions", body: [
    "By using this website you agree to these terms. Products are Ayurvedic/herbal wellness products and are not intended to diagnose, treat, cure or prevent any disease. Consult a qualified practitioner before use.",
    "Prices are shown in INR and include applicable GST at checkout. Orders are confirmed only after successful payment verification.",
    "Accounts must be registered with accurate information. Misuse, fraud or sharing of login credentials may result in suspension.",
    "We may update these terms from time to time; continued use constitutes acceptance of the updated terms.",
  ]},
  "refund-policy": { title: "Refund & Cancellation Policy", body: [
    "Orders may be cancelled before dispatch by contacting us. Once dispatched, cancellation is not possible.",
    "Refunds are considered for damaged, defective or incorrectly delivered products reported within 48 hours of delivery with photographic evidence.",
    "Approved refunds are returned to the original payment method within 7–10 working days. Any commissions credited on a refunded order are reversed.",
  ]},
  "shipping-policy": { title: "Shipping & Delivery Policy", body: [
    "Orders are dispatched within 2–5 working days after payment confirmation. Delivery timelines depend on the destination and courier partner, typically 5–10 working days within India.",
    "Shipping charges, if any, are shown at checkout. Tracking details are shared once the order is dispatched.",
  ]},
  "distributor-terms": { title: "Distributor / Direct Selling Terms", body: [
    "Distributorship is open to Indian residents aged 18 or above after admin approval and KYC verification.",
    "Commissions are paid only on genuine, successfully paid product purchases as per the company's published commission schedule. There is no payment for merely recruiting members.",
    "No income is guaranteed. Earnings depend entirely on actual product sales within your network and vary from distributor to distributor.",
    "Distributors must not make exaggerated product or income claims, and must comply with the Consumer Protection (Direct Selling) Rules, 2021.",
    "Commissions credited on orders that are later refunded, cancelled or reversed will be clawed back from the wallet.",
  ]},
  contact: { title: "Contact Us", body: [] },
};

export default function Legal() {
  const { slug } = useParams();
  const { t } = useI18n();
  const [s, setS] = useState(null);
  useEffect(() => { API.get("/settings/public").then(({ data }) => setS(data)).catch(() => {}); }, []);
  const page = PAGES[slug];
  if (!page) return <Navigate to="/" replace />;
  return (
    <div className="min-h-screen bg-cream">
      <header className="border-b border-brand-50 bg-white"><div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4 lg:px-8"><Link to="/"><Logo size="sm" /></Link><Link to="/" className="text-sm font-medium text-forest hover:underline">Home</Link></div></header>
      <main className="mx-auto max-w-3xl px-4 py-10 lg:px-8" data-testid={`legal-${slug}`}>
        <h1 className="font-display text-3xl font-semibold text-ink">{page.title}</h1>
        <p className="mt-1 text-sm text-muted2">{s?.company_name || t("brand.full")}</p>
        <div className="mt-6 space-y-4 text-sm leading-relaxed text-ink/80">
          {page.body.map((p, i) => <p key={i}>{p}</p>)}
          {slug === "contact" && (
            <div className="space-y-2">
              <p><b>Company:</b> {s?.company_name || t("brand.full")}</p>
              {s?.company_email && <p><b>Email:</b> <a className="text-forest hover:underline" href={`mailto:${s.company_email}`} data-testid="contact-email">{s.company_email}</a></p>}
              {s?.company_phone && <p><b>Phone:</b> <a className="text-forest hover:underline" href={`tel:${s.company_phone}`} data-testid="contact-phone">{s.company_phone}</a></p>}
              <p>Support hours: Monday–Saturday, 10:00 AM – 6:00 PM IST.</p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export const LEGAL_LINKS = [
  ["privacy", "Privacy Policy"], ["terms", "Terms & Conditions"], ["refund-policy", "Refund Policy"],
  ["shipping-policy", "Shipping Policy"], ["distributor-terms", "Distributor Terms"], ["contact", "Contact Us"],
];

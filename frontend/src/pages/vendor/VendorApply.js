import React, { useState } from "react";
import { Link } from "react-router-dom";
import { Building2, CheckCircle2, ClipboardCheck, Eye, EyeOff, Globe2, KeyRound, MapPin, PackageCheck, Send, ShieldCheck, Sparkles, UserRound, Users } from "lucide-react";
import { VendorPublicShell, VButton, VCard, VChips, VField, VInput, VSelect, VTextarea, VBanner } from "@/components/vendor/VendorUI";
import { API, apiError } from "@/lib/api";
import { BUSINESS_TYPES, EMAIL_RE, INDIAN_STATES, MOBILE_RE, PILLARS } from "@/lib/vendorOptions";

const EMPTY = { business_name: "", business_type: "", description: "", categories: [], contact_name: "", mobile: "", email: "",
                city: "", state: "", website: "", consent: false, password: "", confirm_password: "", company_fax: "" };

function problemsOf(f) {
  return {
    business_name: f.business_name.trim().length < 2 ? "Enter your business or brand name." : null,
    business_type: !f.business_type ? "Choose your business type." : null,
    categories: f.categories.length === 0 ? "Choose at least one category you supply." : null,
    description: f.description.trim().length < 20 ? "Tell us a little more (at least 20 characters)." : null,
    contact_name: f.contact_name.trim().length < 2 ? "Enter the contact person's name." : null,
    mobile: MOBILE_RE.test(f.mobile.trim()) ? null : "Enter a valid 10-digit Indian mobile number.",
    email: !f.email.trim() || EMAIL_RE.test(f.email.trim()) ? null : "Enter a valid email address, or leave it blank.",
    city: f.city.trim().length < 2 ? "Enter your city." : null,
    state: !f.state ? "Choose your state." : null,
    website: !f.website.trim() || /^https:\/\/\S+$/.test(f.website.trim()) ? null : "Use a full https:// address, or leave it blank.",
    password: f.password.length >= 8 && /[A-Za-z]/.test(f.password) && /\d/.test(f.password) ? null : "Use at least 8 characters with letters and numbers.",
    confirm_password: f.confirm_password && f.confirm_password === f.password ? null : "The passwords do not match.",
    consent: f.consent ? null : "Please accept the terms and privacy policy.",
  };
}

const STEPS = [
  ["Apply", "Tell us about your business", Send],
  ["Review", "Our partner team reviews it", ClipboardCheck],
  ["Onboarding", "We complete your registration with you", Building2],
  ["Approval", "Final approval by HOME GENIES", ShieldCheck],
  ["Start selling", "Sign in with your password and go live", PackageCheck],
];

export default function VendorApply() {
  const [f, setF] = useState(EMPTY);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [error, setError] = useState("");
  const [showPw, setShowPw] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const problems = problemsOf(f);
  const err = (k) => (tried ? problems[k] : null);

  const submit = async (e) => {
    e.preventDefault();
    setTried(true);
    setError("");
    if (Object.values(problems).some(Boolean) || busy) {
      const first = Object.keys(problems).find((k) => problems[k]);
      document.getElementById(`va-${first}`)?.focus();
      return;
    }
    setBusy(true);
    try {
      const { data } = await API.post("/vendor-applications", { ...f, business_name: f.business_name.trim(), description: f.description.trim(),
        contact_name: f.contact_name.trim(), mobile: f.mobile.trim(), email: f.email.trim(), city: f.city.trim(), website: f.website.trim() });
      setDone(data.message);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (ex) {
      setError(apiError(ex));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <VendorPublicShell>
        <VCard className="p-7 text-center sm:p-10" data-testid="va-done">
          <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-choco-800 text-aurum-300 shadow-lg"><CheckCircle2 size={32} aria-hidden /></span>
          <h1 className="hgv-title mt-5 text-3xl font-bold">Application received</h1>
          <p className="hgv-muted mx-auto mt-3 max-w-md text-[15px] leading-relaxed">{done}</p>
          <VBanner tone="gold" icon={ShieldCheck} className="mt-6 text-left">
            Your vendor login is not active yet. If your application moves forward, our team completes your registration with you. Once
            HOME GENIES gives final approval, sign in at Vendor login with your business mobile and the password you chose.
          </VBanner>
          <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
            <VButton to="/" variant="primary">Back to HOME GENIES</VButton>
            <VButton to="/vendor/login" variant="secondary">Vendor login</VButton>
          </div>
        </VCard>
      </VendorPublicShell>
    );
  }

  return (
    <VendorPublicShell wide>
      <div className="grid gap-8 lg:grid-cols-[0.9fr_1.1fr] lg:gap-10">
        <aside className="space-y-6">
          <div>
            <span className="hgv-pill hgv-pill-gold"><Sparkles size={13} aria-hidden /> Vendor partner programme</span>
            <h1 className="hgv-title mt-4 text-4xl font-bold leading-tight sm:text-[2.75rem]">Sell on HOME GENIES</h1>
            <p className="hgv-muted mt-3 max-w-lg text-[15px] leading-relaxed">
              Supply sarees, fashion, beauty and household essentials to families across India, through direct shoppers and a
              network of HomeGenies who recommend products they trust.
            </p>
          </div>
          <VCard className="hgv-card-dark p-5 sm:p-6">
            <h2 className="hgv-title text-lg font-semibold" style={{ color: "#F3E3B5" }}>How partnership works</h2>
            <ol className="mt-4 space-y-3">
              {STEPS.map(([title, text, Icon], i) => (
                <li key={title} className="flex items-start gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-aurum-500 text-sm font-extrabold text-choco-900">{i + 1}</span>
                  <span className="pt-0.5">
                    <span className="flex items-center gap-2 font-semibold text-cream-100"><Icon size={15} className="text-aurum-300" aria-hidden />{title}</span>
                    <span className="block text-sm text-cream-300">{text}</span>
                  </span>
                </li>
              ))}
            </ol>
          </VCard>
          <ul className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
            {[[Users, "Reach families and HomeGenies", "Your products are shared by people your customers know."],
              [PackageCheck, "You stay in control", "Manage your listings, stock and dispatch from your own panel."],
              [ShieldCheck, "Clear, fair terms", "Written agreements, transparent orders and HOME GENIES support."]].map(([Icon, t, d]) => (
              <li key={t} className="hgv-card flex items-start gap-3 p-4">
                <Icon size={20} className="mt-0.5 shrink-0 text-aurum-600" aria-hidden />
                <span><span className="block font-semibold text-choco-800">{t}</span><span className="hgv-muted block text-sm">{d}</span></span>
              </li>
            ))}
          </ul>
        </aside>

        <form onSubmit={submit} noValidate className="space-y-5" data-testid="vendor-apply-form" aria-describedby="va-intro">
          <p id="va-intro" className="hgv-muted text-sm">Takes about 3 minutes. Fields marked <span className="hgv-req !ml-0">Required</span> are needed. We never share your details.</p>
          {error && <VBanner tone="red">{error}</VBanner>}

          <VCard className="p-5 sm:p-6">
            <h2 className="hgv-title flex items-center gap-2 text-xl font-semibold"><Building2 size={19} className="text-aurum-600" aria-hidden /> 1. Your business</h2>
            <div className="mt-4 grid gap-4">
              <VField id="va-business_name" label="Business or brand name" required error={err("business_name")}>
                <VInput id="va-business_name" value={f.business_name} onChange={set("business_name")} maxLength={120} autoComplete="organization" invalid={!!err("business_name")} data-testid="va-business-name" />
              </VField>
              <VField id="va-business_type" label="Business type" required error={err("business_type")}>
                <VSelect id="va-business_type" options={BUSINESS_TYPES} value={f.business_type} onChange={set("business_type")} invalid={!!err("business_type")} data-testid="va-business-type" />
              </VField>
              <VField id="va-categories" label="What do you supply?" required error={err("categories")} help="Choose every category that applies.">
                <div id="va-categories" tabIndex={-1}><VChips options={PILLARS} value={f.categories} onChange={(v) => setF({ ...f, categories: v })} testid="va-categories" /></div>
              </VField>
              <VField id="va-description" label="About your business" required error={err("description")} help={`${f.description.trim().length}/1000 · products, brands, where you make or source them`}>
                <VTextarea id="va-description" value={f.description} onChange={set("description")} maxLength={1000} invalid={!!err("description")} data-testid="va-description" />
              </VField>
            </div>
          </VCard>

          <VCard className="p-5 sm:p-6">
            <h2 className="hgv-title flex items-center gap-2 text-xl font-semibold"><UserRound size={19} className="text-aurum-600" aria-hidden /> 2. Contact person</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <VField id="va-contact_name" label="Full name" required error={err("contact_name")} className="sm:col-span-2">
                <VInput id="va-contact_name" value={f.contact_name} onChange={set("contact_name")} maxLength={80} autoComplete="name" invalid={!!err("contact_name")} data-testid="va-contact-name" />
              </VField>
              <VField id="va-mobile" label="Business mobile" required error={err("mobile")} help="Use the business's own number.">
                <VInput id="va-mobile" value={f.mobile} onChange={set("mobile")} inputMode="numeric" maxLength={10} autoComplete="tel-national" invalid={!!err("mobile")} data-testid="va-mobile" />
              </VField>
              <VField id="va-email" label="Business email" optional error={err("email")}>
                <VInput id="va-email" type="email" value={f.email} onChange={set("email")} maxLength={120} autoComplete="email" invalid={!!err("email")} data-testid="va-email" />
              </VField>
            </div>
          </VCard>

          <VCard className="p-5 sm:p-6">
            <h2 className="hgv-title flex items-center gap-2 text-xl font-semibold"><MapPin size={19} className="text-aurum-600" aria-hidden /> 3. Location & presence</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <VField id="va-city" label="City" required error={err("city")}>
                <VInput id="va-city" value={f.city} onChange={set("city")} maxLength={60} autoComplete="address-level2" invalid={!!err("city")} data-testid="va-city" />
              </VField>
              <VField id="va-state" label="State" required error={err("state")}>
                <VSelect id="va-state" options={INDIAN_STATES} value={f.state} onChange={set("state")} invalid={!!err("state")} data-testid="va-state" />
              </VField>
              <VField id="va-website" label="Website or online store" optional error={err("website")} className="sm:col-span-2">
                <div className="relative">
                  <VInput id="va-website" value={f.website} onChange={set("website")} placeholder="https://" maxLength={200} inputMode="url" invalid={!!err("website")} data-testid="va-website" />
                  <Globe2 size={17} className="pointer-events-none absolute right-3 top-1/2 mt-0.5 -translate-y-1/2 text-choco-500" aria-hidden />
                </div>
              </VField>
            </div>
            {/* Honeypot: invisible to people and screen readers; bots that fill every field are ignored by the server. */}
            <div className="hgv-visually-hidden" aria-hidden="true">
              <label htmlFor="va-company_fax">Company fax</label>
              <input id="va-company_fax" name="company_fax" tabIndex={-1} autoComplete="off" value={f.company_fax} onChange={set("company_fax")} />
            </div>
          </VCard>

          <VCard className="p-5 sm:p-6">
            <h2 className="hgv-title flex items-center gap-2 text-xl font-semibold"><KeyRound size={19} className="text-aurum-600" aria-hidden /> 4. Your vendor login</h2>
            <p className="hgv-muted mt-1 text-sm">Choose the password for your vendor panel. It works only after HOME GENIES approves your registration; you sign in with your business mobile.</p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <VField id="va-password" label="Password" required error={err("password")} help="At least 8 characters, with letters and numbers.">
                <div className="relative">
                  <VInput id="va-password" type={showPw ? "text" : "password"} value={f.password} onChange={set("password")} autoComplete="new-password" maxLength={128}
                          className="!pr-12" invalid={!!err("password")} data-testid="va-password" />
                  <button type="button" onClick={() => setShowPw(!showPw)} aria-label={showPw ? "Hide password" : "Show password"}
                          className="absolute right-1 top-1/2 mt-0.5 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full text-choco-600 hover:bg-cream-200">
                    {showPw ? <EyeOff size={19} /> : <Eye size={19} />}</button>
                </div>
              </VField>
              <VField id="va-confirm_password" label="Confirm password" required error={err("confirm_password")}>
                <VInput id="va-confirm_password" type={showPw ? "text" : "password"} value={f.confirm_password} onChange={set("confirm_password")} autoComplete="new-password"
                        maxLength={128} invalid={!!err("confirm_password")} data-testid="va-confirm-password" />
              </VField>
            </div>
          </VCard>

          <VCard className="p-5 sm:p-6">
            <label className="flex cursor-pointer items-start gap-3 text-[15px] text-choco-800" htmlFor="va-consent">
              <input id="va-consent" type="checkbox" checked={f.consent} onChange={(e) => setF({ ...f, consent: e.target.checked })}
                     className="mt-0.5 h-6 w-6 shrink-0 accent-[#3B2417]" aria-invalid={err("consent") ? "true" : undefined} data-testid="va-consent" />
              <span>I agree to the HOME GENIES <Link to="/legal/terms" className="font-semibold underline underline-offset-2">terms</Link> and <Link to="/legal/privacy" className="font-semibold underline underline-offset-2">privacy policy</Link>, and to be contacted about this application.</span>
            </label>
            {err("consent") && <p role="alert" className="hgv-error">{err("consent")}</p>}
            <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="hgv-muted text-xs">Your login stays inactive until HOME GENIES gives final approval.</p>
              <VButton type="submit" variant="primary" icon={Send} busy={busy} className="w-full sm:w-auto" data-testid="va-submit">Submit application</VButton>
            </div>
          </VCard>
          <p className="hgv-muted text-center text-sm">Already an approved vendor? <Link to="/vendor/login" className="font-semibold text-choco-700 underline underline-offset-2">Sign in to your vendor panel</Link></p>
        </form>
      </div>
    </VendorPublicShell>
  );
}

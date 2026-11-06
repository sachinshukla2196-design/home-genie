import React from "react";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";

/**
 * Vendor Pillar design system (cream + chocolate + gold). Every class lives under `.hgv-*` in index.css, so nothing here
 * changes the homepage or other areas. Buttons are substantial, clearly clickable and have hover / pressed / focus states.
 */

export function VButton({ variant = "primary", size, icon: Icon, busy, children, className = "", to, ...props }) {
  const cls = `hgv-btn hgv-btn-${variant}${size === "sm" ? " hgv-btn-sm" : ""} ${className}`;
  const inner = (
    <>
      {busy ? <Loader2 size={17} className="animate-spin" aria-hidden /> : Icon ? <Icon size={17} aria-hidden /> : null}
      <span>{children}</span>
    </>
  );
  if (to) return <Link to={to} className={cls} {...props}>{inner}</Link>;
  return <button type="button" className={cls} disabled={busy || props.disabled} aria-busy={busy || undefined} {...props}>{inner}</button>;
}

export function VCard({ className = "", children, ...props }) {
  return <div className={`hgv-card ${className}`} {...props}>{children}</div>;
}

export function VSection({ title, icon: Icon, subtitle, action, children, className = "" }) {
  return (
    <VCard className={`p-5 sm:p-6 ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          {Icon && <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-choco-800 text-aurum-300 shadow-md"><Icon size={20} aria-hidden /></span>}
          <div className="min-w-0">
            <h2 className="hgv-title text-xl font-semibold">{title}</h2>
            {subtitle && <p className="hgv-muted mt-0.5 text-sm">{subtitle}</p>}
          </div>
        </div>
        {action}
      </div>
      <div className="mt-5">{children}</div>
    </VCard>
  );
}

/** A labelled field with REQUIRED / OPTIONAL marker, help text and an error message wired for screen readers. */
export function VField({ id, label, required, optional, help, error, children, className = "" }) {
  return (
    <div className={className}>
      <label htmlFor={id} className="hgv-label">
        {label}
        {required && <span className="hgv-req">Required</span>}
        {optional && <span className="hgv-opt">Optional</span>}
      </label>
      {children}
      {error ? <p id={`${id}-err`} role="alert" className="hgv-error">{error}</p> : help ? <p id={`${id}-help`} className="hgv-help">{help}</p> : null}
    </div>
  );
}

export const VInput = React.forwardRef(function VInput({ invalid, className = "", ...props }, ref) {
  return <input ref={ref} className={`hgv-input ${className}`} aria-invalid={invalid ? "true" : undefined} {...props} />;
});

export function VTextarea({ invalid, className = "", ...props }) {
  return <textarea className={`hgv-input ${className}`} aria-invalid={invalid ? "true" : undefined} {...props} />;
}

export function VSelect({ invalid, options, placeholder = "Choose…", className = "", ...props }) {
  const entries = Array.isArray(options) ? options.map((o) => [o, o]) : Object.entries(options || {});
  return (
    <select className={`hgv-input ${className}`} aria-invalid={invalid ? "true" : undefined} {...props}>
      <option value="">{placeholder}</option>
      {entries.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select>
  );
}

/** Toggle chips for multi-select (categories, supplier roles). Each chip is a real button with aria-pressed. */
export function VChips({ options, value = [], onChange, disabled, testid }) {
  const entries = Array.isArray(options) ? options.map((o) => [o, o]) : Object.entries(options || {});
  const toggle = (k) => onChange(value.includes(k) ? value.filter((x) => x !== k) : [...value, k]);
  return (
    <div className="mt-2 flex flex-wrap gap-2" data-testid={testid}>
      {entries.map(([k, label]) => (
        <button key={k} type="button" className="hgv-chip" aria-pressed={value.includes(k)} disabled={disabled} onClick={() => toggle(k)}>{label}</button>
      ))}
    </div>
  );
}

export function VYesNo({ value, onChange, disabled, name }) {
  return (
    <div className="mt-2 flex gap-2" role="radiogroup" aria-label={name}>
      {[[true, "Yes"], [false, "No"]].map(([v, l]) => (
        <button key={l} type="button" role="radio" aria-checked={value === v} className="hgv-chip" aria-pressed={value === v} disabled={disabled} onClick={() => onChange(v)}>{l}</button>
      ))}
    </div>
  );
}

const PILL = {
  onboarding: ["hgv-pill-gold", "Onboarding"], ready_for_review: ["hgv-pill-blue", "Ready for approval"], approved: ["hgv-pill-green", "Approved"],
  active: ["hgv-pill-green", "Approved"], rejected: ["hgv-pill-red", "Rejected"], suspended: ["hgv-pill-red", "Suspended"],
  draft: ["hgv-pill-muted", "Draft"], submitted: ["hgv-pill-blue", "Submitted"], under_review: ["hgv-pill-blue", "Under review"],
  changes_requested: ["hgv-pill-gold", "Changes requested"], pending_documents: ["hgv-pill-gold", "Documents pending"], invited: ["hgv-pill-muted", "Invited"],
  new: ["hgv-pill-gold", "New"], in_review: ["hgv-pill-blue", "In review"], converting: ["hgv-pill-blue", "Converting"], converted: ["hgv-pill-green", "Onboarding started"],
  declined: ["hgv-pill-red", "Declined"], duplicate: ["hgv-pill-muted", "Duplicate"], verified: ["hgv-pill-green", "Verified"],
};

export function VStatus({ status, label }) {
  const [cls, text] = PILL[status] || ["hgv-pill-muted", status];
  return <span className={`hgv-pill ${cls}`} data-testid="hgv-status">{label || text}</span>;
}

export function VBanner({ tone = "gold", icon: Icon, children, className = "" }) {
  return (
    <div className={`hgv-banner hgv-banner-${tone} ${className}`} role={tone === "red" ? "alert" : "status"}>
      {Icon && <Icon size={19} className="mt-0.5 shrink-0" aria-hidden />}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** The cream page shell for public vendor pages (apply, login, owner invitation). */
export function VendorPublicShell({ children, wide }) {
  return (
    <div className="hgv min-h-screen">
      <header className="hgv-band">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <Link to="/" className="flex items-center gap-3" aria-label="HOME GENIES home">
            <img src="/brand/favicon-64.png" alt="" className="h-9 w-9 rounded-xl ring-1 ring-aurum-400/50" />
            <span className="leading-tight">
              <span className="hgv-title block text-lg font-bold tracking-wide text-aurum-300" style={{ color: "#EAD394" }}>HOME GENIES</span>
              <span className="block text-[11px] font-semibold uppercase tracking-[0.18em] text-cream-300">Partner programme</span>
            </span>
          </Link>
          <nav className="flex items-center gap-2">
            <Link to="/vendor/login" className="hgv-btn hgv-btn-sm hgv-btn-on-dark" data-testid="shell-vendor-login">Vendor login</Link>
          </nav>
        </div>
      </header>
      <main className={`mx-auto w-full ${wide ? "max-w-6xl" : "max-w-xl"} px-4 py-8 sm:px-6 sm:py-12`}>{children}</main>
      <footer className="mx-auto max-w-6xl px-4 pb-10 text-center text-xs text-choco-500 sm:px-6">
        © {new Date().getFullYear()} HOME GENIES · <Link to="/legal/terms" className="underline underline-offset-2">Terms</Link> · <Link to="/legal/privacy" className="underline underline-offset-2">Privacy</Link>
      </footer>
    </div>
  );
}

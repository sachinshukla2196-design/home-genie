import React from "react";
import { motion } from "framer-motion";

/**
 * Standard page heading for app and admin screens.
 * The <h1> is hidden on phones inside the app shell (the top bar shows the title there).
 */
export function PageHeader({ title, subtitle, icon: Icon, actions, className = "" }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}
      className={`flex flex-wrap items-end justify-between gap-3 ${className}`}>
      <div className="flex min-w-0 items-center gap-3">
        {Icon && <span className="hg-icon-chip hidden lg:inline-flex"><Icon size={22} /></span>}
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold text-ink sm:text-3xl">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-muted2">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </motion.div>
  );
}

/** Glass card with an optional title row. */
export function SectionCard({ title, icon: Icon, action, children, className = "", bodyClassName = "", testid }) {
  return (
    <motion.section initial={{ opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }} className={`hg-card p-5 sm:p-6 ${className}`} data-testid={testid}>
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="flex min-w-0 items-center gap-2.5 font-display text-lg font-semibold text-ink">
            {Icon && <span className="hg-icon-chip !h-9 !w-9 !rounded-xl"><Icon size={18} /></span>}
            <span className="truncate">{title}</span>
          </h3>
          {action}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </motion.section>
  );
}

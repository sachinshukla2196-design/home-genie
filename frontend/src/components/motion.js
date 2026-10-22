import React, { useEffect, useRef, useState } from "react";
import { motion, animate, useInView, useReducedMotion } from "framer-motion";

/** Shared motion primitives for the app screens. All of them respect "reduce motion". */

const EASE = [0.16, 1, 0.3, 1];

export const listVariants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.04 } },
};

export const itemVariants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
};

/** Container that staggers its <StaggerItem> children in. */
export function Stagger({ as = "div", className, children, ...rest }) {
  const Comp = motion[as];
  return (
    <Comp variants={listVariants} initial="hidden" animate="show" className={className} {...rest}>
      {children}
    </Comp>
  );
}

export function StaggerItem({ as = "div", className, children, ...rest }) {
  const Comp = motion[as];
  return <Comp variants={itemVariants} className={className} {...rest}>{children}</Comp>;
}

/** Number that counts up from 0 the first time it scrolls into view. */
export function CountUp({ value = 0, format = (n) => Math.round(n).toLocaleString("en-IN"), duration = 1.1, className, ...rest }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true });
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? value : 0);

  useEffect(() => {
    if (!inView) return;
    if (reduce) { setShown(value); return; }
    const controls = animate(0, Number(value) || 0, { duration, ease: EASE, onUpdate: setShown });
    return () => controls.stop();
  }, [inView, value, duration, reduce]);

  return <span ref={ref} className={className} {...rest}>{format(shown)}</span>;
}

/** Progress bar whose fill grows to `pct` once visible. */
export function ProgressBar({ pct = 0, className = "", trackClassName = "bg-brand-50", testid }) {
  const width = `${Math.min(Math.max(pct, 2), 100)}%`;
  return (
    <div className={`h-2.5 w-full overflow-hidden rounded-full ${trackClassName}`}>
      <motion.div
        className={`hg-progress relative h-full rounded-full ${className}`}
        initial={{ width: 0 }}
        whileInView={{ width }}
        viewport={{ once: true }}
        transition={{ duration: 1.2, ease: EASE, delay: 0.15 }}
        data-testid={testid}
      >
        <span className="hg-progress-glint" />
      </motion.div>
    </div>
  );
}

/** Button/link wrapper with lift-on-hover and press feedback. */
export const pressable = {
  whileHover: { y: -2 },
  whileTap: { scale: 0.97 },
  transition: { type: "spring", stiffness: 420, damping: 28 },
};
